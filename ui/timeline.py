# -*- coding: utf-8 -*-
"""时间轴控件（PySide6 自定义 QWidget）。

参考 LosslessCut + 专业剪辑软件（Premiere/DaVinci）的操作手感：
  - 点击空白/拖动播放头：跳转播放位置
  - 点击片段：选中
  - 拖动片段左右边缘（12px 宽抓取区）：调整切点
  - 双击片段：选中并播放该片段
  - 滚轮：以鼠标为中心平滑缩放；Shift+滚轮：平移
  - 底部迷你概览图（minimap）：一眼看到全片结构，点击/拖动直接跳转视口
  - 缩放/跳转带 250ms 缓动动画，不硬跳
  - 浏览模式：删除段消失，保留段无缝拼接显示，预览成片
"""
import math
import time

from PySide6.QtCore import (QEasingCurve, QRect, QPointF, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QScrollBar, QWidget

# 时间轴专用色（直接定义 QColor，保证性能）
GREEN = QColor(76, 175, 125)          # 保留段
GREEN_HOVER = QColor(92, 191, 141)    # 保留段悬停
DEL = QColor(42, 45, 51)              # 删除段
DEL_HOVER = QColor(58, 61, 67)        # 删除段悬停
BG = QColor(11, 13, 16)               # 时间轴背景比面板稍深
RULER = QColor(154, 163, 174)         # 标尺文字
SELECT = QColor(255, 213, 79)         # 选中高亮
PLAYHEAD = QColor(255, 255, 255)      # 播放头
EDGE = QColor(255, 255, 255)
MM_BG = QColor(17, 20, 24)            # 迷你概览图背景
MM_VIEW = QColor(91, 141, 239)        # 视口框

TICKS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200]

EDGE_GRAB = 12   # 边缘抓取区宽度（像素），越宽越好拖
MIN_HIT_W = 20   # 小片段的最小可点击宽度（像素），避免太窄点不到
CHIP_TOP = 4     # 顶部片段编号条 y
CHIP_H = 26      # 顶部片段编号条高度


def fmt_time(t):
    t = max(0, int(round(t)))
    return "{}:{:02d}".format(t // 60, t % 60)


def display_number(segments, idx):
    """独立编号：保留段从 1 开始（镜头N），删除段从 1 开始（废N）。

    返回 (编号, 是否保留)。导出时也只按保留段从 1 编号，两边一致。
    """
    keep_n = del_n = 0
    for i, s in enumerate(segments):
        if i == idx:
            return (keep_n + 1, True) if s.keep else (del_n + 1, False)
        if s.keep:
            keep_n += 1
        else:
            del_n += 1
    return (0, False)


class _VirtSeg:
    """浏览模式下虚拟排列的保留段：start/end 为拼接后的虚拟时间。"""
    __slots__ = ("start", "end", "orig_idx", "keep")

    def __init__(self, start, end, orig_idx):
        self.start = start
        self.end = end
        self.orig_idx = orig_idx
        self.keep = True


class Timeline(QWidget):
    seekRequested = Signal(float)          # 跳转到秒（始终为原始时间）
    segmentsEdited = Signal()              # 片段被拖动/切换后
    selectionChanged = Signal(int)         # 选中片段下标（原始索引）
    segmentPlayRequested = Signal(int)     # 双击片段：播放该片段
    scrubStarted = Signal()               # 开始拖动播放头（刮擦预览：暂停播放）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(235)
        self.setMouseTracking(True)

        self.segments = []
        self.duration = 1.0
        self.playhead = 0.0
        self.selected = -1
        self._hover = -1          # 悬停的片段下标
        self._chip_hover = -1     # 悬停的编号条片段下标
        self.lock_deleted = False  # 锁定：已删除片段不可点击/拖动

        # 浏览模式（紧凑视图：删除段消失，保留段拼接）
        self.browse_mode = False
        self.virt_disp = []        # 浏览模式下的显示段列表（_VirtSeg）
        self.disp_orig = []        # 显示索引 -> 原始索引
        self.virt_duration = 0.0   # 浏览模式虚拟总时长

        self.margin = 70
        self.top = 50
        self.bottom = 175
        self.mm_top = 185         # 迷你概览图 y
        self.mm_h = 26
        self.pps = 10.0
        self.view_start = 0.0

        self._drag = None         # ('playhead',) / ('edge_left', idx) /
                                  # ('edge_right', idx) / ('mm',)
        self._anim = None
        self._last_playhead_px = -1   # 上次重绘时播放头的像素位置，用于节流
        self._last_scrub_t = 0.0       # 上次刮擦 seek 的时刻，用于节流

        self.sb = QScrollBar(Qt.Horizontal, self)
        self.sb.valueChanged.connect(self._on_scrollbar)
        self.sb.setVisible(False)

    # ---------- 显示集合（普通模式 / 浏览模式） ----------
    def _disp_segs(self):
        return self.virt_disp if self.browse_mode else self.segments

    def _disp_duration(self):
        return self.virt_duration if self.browse_mode else self.duration

    def _orig_of(self, di):
        """显示索引 -> 原始索引（浏览模式下需要映射）。"""
        if self.browse_mode:
            return self.disp_orig[di]
        return di

    def _orig_seg(self, di):
        """显示索引 -> 原始 Segment 对象。"""
        return self.segments[self._orig_of(di)]

    # ---------- 数据 ----------
    def set_segments(self, duration, segments):
        self.browse_mode = False
        self.duration = max(duration, 1.0)
        self.segments = list(segments)
        self.selected = -1
        self.fit()

    def _rebuild_virt(self):
        """重建浏览模式下的拼接显示段（只含保留段）。"""
        self.virt_disp = []
        self.disp_orig = []
        cur = 0.0
        for i, seg in enumerate(self.segments):
            if seg.keep:
                self.virt_disp.append(_VirtSeg(cur, cur + seg.duration, i))
                self.disp_orig.append(i)
                cur += seg.duration
        self.virt_duration = max(0.2, cur)

    def enter_browse(self):
        """浏览模式：删除段消失，保留段无缝拼接显示，播放头回到起点。"""
        self._rebuild_virt()
        self.browse_mode = True
        self.selected = -1
        self.playhead = 0.0
        self.fit()

    def exit_browse(self):
        self.browse_mode = False
        self.selected = -1
        self.playhead = self.virt_to_orig(self.playhead)
        self.fit()

    def refresh_browse(self):
        """浏览模式下保留/删除变化后重新拼接，尽量保持播放头位置。"""
        if not self.browse_mode:
            return
        old_playhead = self.playhead
        self._rebuild_virt()
        self.playhead = min(max(0.0, old_playhead), self.virt_duration)
        self._clamp_view()
        self._sync_scrollbar()
        self.update()

    # ---------- 虚拟<->原始 映射 ----------
    def orig_to_virt(self, t):
        if not self.browse_mode:
            return t
        virt = 0.0
        for seg in self.segments:
            if seg.keep:
                if seg.start <= t < seg.end:
                    return virt + (t - seg.start)
                virt += seg.duration
        return virt

    def virt_to_orig(self, v):
        if not self.browse_mode:
            return v
        for seg in self.virt_disp:
            if seg.start <= v <= seg.end:
                return self.segments[seg.orig_idx].start + (v - seg.start)
        if self.virt_disp:
            last = self.virt_disp[-1]
            return self.segments[last.orig_idx].end
        return 0.0

    def _emit_seek(self, t):
        """发出跳转信号（浏览模式下把虚拟时间转回原始时间）。"""
        self.seekRequested.emit(self.virt_to_orig(t))

    # ---------- 视图 ----------
    def fit(self):
        """平滑缩放到完整视频（带动画）。"""
        w = max(200, self.width())
        target_pps = max(0.2, (w - 2 * self.margin) / self._disp_duration())
        self._animate_view(target_pps, 0.0)

    def set_playhead(self, seconds):
        # 正在拖动播放头时忽略播放器回报的位置：
        # seek 是异步的，回报的往往是旧位置，会和鼠标拖动打架（播放头来回抖）
        if self._drag is not None and self._drag[0] == "playhead":
            return
        # 传入为原始视频时间；浏览模式下换算为虚拟位置再显示
        if self.browse_mode:
            seconds = self.orig_to_virt(seconds)
        self.playhead = min(max(0.0, seconds), self._disp_duration())
        # 节流：播放头像素位置没变就不重绘（播放时 positionChanged 约 20-30fps，
        # 但缩放较小时很多帧的像素位置相同，跳过可省掉大量 paintEvent）
        px = self.margin + int((self.playhead - self.view_start) * self.pps)
        if px != self._last_playhead_px:
            self._last_playhead_px = px
            self.update()

    # ---------- 平滑动画 ----------
    def _animate_view(self, target_pps, target_vs, duration=250):
        """把 pps 和 view_start 平滑过渡到目标值（OutCubic 缓动）。"""
        if self._anim is not None:
            self._anim.stop()
        from_pps = self.pps
        from_vs = self.view_start
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(
            lambda v: self._apply_view(
                from_pps + (target_pps - from_pps) * v,
                from_vs + (target_vs - from_vs) * v))
        anim.finished.connect(
            lambda: self._apply_view(target_pps, target_vs))
        self._anim = anim
        anim.start()

    def _apply_view(self, pps, view_start):
        self.pps = pps
        self.view_start = view_start
        self._clamp_view()
        self._sync_scrollbar()
        self.update()

    # ---------- 视图计算 ----------
    def _view_w(self):
        w = max(200, self.width())
        return (w - 2 * self.margin) / self.pps

    def _clamp_view(self):
        m = max(0.0, self._disp_duration() - self._view_w())
        self.view_start = min(max(0.0, self.view_start), m)

    def _tick_step(self):
        for t in TICKS:
            if t * self.pps >= 70:
                return t
        return TICKS[-1]

    def _x2t(self, x):
        return self.view_start + (x - self.margin) / self.pps

    def _t2x(self, t):
        return self.margin + (t - self.view_start) * self.pps

    # ---------- 迷你概览图 ----------
    def _mm_w(self):
        return max(200, self.width()) - 2 * self.margin

    def _mm_x2t(self, x):
        d = self._disp_duration()
        return max(0.0, min(d, (x - self.margin) / self._mm_w() * d))

    def _mm_t2x(self, t):
        return self.margin + t / self._disp_duration() * self._mm_w()

    def _mm_center_view(self, t):
        """把视口中心移动到 t（平滑动画）。"""
        self._animate_view(self.pps, t - self._view_w() / 2.0)

    def _sync_scrollbar(self):
        d = self._disp_duration()
        total_w = d * self.pps
        view_w = self._view_w()
        if total_w <= view_w:
            self.sb.setVisible(False)
        else:
            self.sb.setVisible(True)
            self.sb.setRange(0, int(total_w - view_w))
            self.sb.setPageStep(int(view_w))
            self.sb.blockSignals(True)
            self.sb.setValue(int((self.view_start / d) * total_w))
            self.sb.blockSignals(False)

    def _on_scrollbar(self, v):
        d = self._disp_duration()
        total_w = d * self.pps
        self.view_start = (v / total_w) * d
        self.update()

    # ---------- 顶部片段编号条（小片段也保证可点击） ----------
    def _chip_layout(self):
        """每个片段一个编号小方块，等宽分布，宽度不小于 24px。"""
        n = max(1, len(self._disp_segs()))
        avail = max(200, self.width()) - 2 * self.margin
        gap = 2
        w = min(46, max(24, (avail - gap * (n - 1)) / n))
        return w, gap

    def _chip_rect(self, i, w, gap):
        x = self.margin + i * (w + gap)
        return (int(x), CHIP_TOP, int(w), CHIP_H)

    def _chip_at(self, x):
        w, gap = self._chip_layout()
        for i in range(len(self._disp_segs())):
            x0, _, cw, _ = self._chip_rect(i, w, gap)
            if x0 <= x <= x0 + cw:
                return i
        return None

    # ---------- 绘制 ----------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        disp = self._disp_segs()

        # ---- 顶部片段编号条：小片段也保证有明确的点击区域 ----
        if disp:
            w, gap = self._chip_layout()
            for di, seg in enumerate(disp):
                x0, y0, cw, ch = self._chip_rect(di, w, gap)
                if x0 > self.width() - self.margin:
                    break
                if x0 + cw < self.margin:
                    continue
                color = GREEN if seg.keep else DEL
                if self._orig_of(di) == self.selected:
                    p.setPen(QPen(SELECT, 2))
                    p.setBrush(color.lighter(115))
                elif di == self._chip_hover:
                    p.setPen(QPen(QColor(220, 220, 220), 1))
                    p.setBrush(color.lighter(108))
                else:
                    p.setPen(QPen(QColor(0, 0, 0), 1))
                    p.setBrush(color)
                p.drawRoundedRect(x0, y0, cw, ch, 5, 5)
                orig_idx = self._orig_of(di)
                num, is_keep = display_number(self.segments, orig_idx)
                label = str(num) if is_keep else "废{}".format(num)
                p.setPen(QPen(QColor(240, 240, 240) if is_keep
                              else QColor(140, 140, 140), 1))
                p.drawText(QRect(x0, y0, cw, ch), Qt.AlignCenter, label)

        # 标尺
        tick = self._tick_step()
        t0 = math.floor(self.view_start / tick) * tick
        p.setPen(QPen(RULER, 1))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        while t0 <= self.view_start + self._view_w() + tick:
            x = self._t2x(t0)
            p.drawLine(x, self.top - 8, x, self.top)
            p.drawText(x + 2, self.top - 12, fmt_time(t0))
            t0 += tick

        # 片段条（悬停高亮 + 选中描边）
        for di, seg in enumerate(disp):
            x0 = self._t2x(seg.start)
            x1 = self._t2x(seg.end)
            w = self.width()
            if x1 < self.margin or x0 > w - self.margin:
                continue
            orig_idx = self._orig_of(di)
            if seg.keep:
                color = GREEN_HOVER if di == self._hover else GREEN
            else:
                color = DEL_HOVER if di == self._hover else DEL
            if self._orig_of(di) == self.selected:
                p.setPen(QPen(SELECT, 2))
            elif di == self._hover:
                p.setPen(QPen(QColor(200, 200, 200), 1))
            else:
                p.setPen(QPen(QColor(0, 0, 0), 1))
            p.setBrush(color)
            p.drawRect(int(x0), self.top, max(2, int(x1 - x0)), self.bottom - self.top)
            if x1 - x0 > 30:
                num, is_keep = display_number(self.segments, orig_idx)
                if is_keep:
                    label = str(num)
                    txt_color = QColor(235, 235, 235)
                else:
                    label = "废{}".format(num)
                    txt_color = QColor(128, 128, 128)
                p.setPen(QPen(txt_color, 1))
                p.drawText(int(x0) + 4, self.top + 18, label)
                # 边缘手柄（只有选中/悬停时加粗，平时淡）
                if di == self.selected or di == self._hover:
                    p.fillRect(int(x0) - 3, self.top, 6, self.bottom - self.top, EDGE)
                    p.fillRect(int(x1) - 3, self.top, 6, self.bottom - self.top, EDGE)
                else:
                    p.fillRect(int(x0) - 2, self.top, 4, self.bottom - self.top, QColor(180, 180, 180))
                    p.fillRect(int(x1) - 2, self.top, 4, self.bottom - self.top, QColor(180, 180, 180))

        # 播放头
        px = self._t2x(self.playhead)
        if self.margin <= px <= self.width() - self.margin:
            p.setPen(QPen(PLAYHEAD, 2))
            p.drawLine(int(px), self.top - 10, int(px), self.bottom + 6)
            p.setBrush(PLAYHEAD)
            p.drawPolygon([QPointF(px - 5, self.top - 10), QPointF(px + 5, self.top - 10),
                           QPointF(px, self.top - 16)])

        # ---- 迷你概览图（minimap） ----
        mm_w = self._mm_w()
        p.fillRect(self.margin, self.mm_top, int(mm_w), self.mm_h, MM_BG)
        for seg in disp:
            sx = self._mm_t2x(seg.start)
            ex = self._mm_t2x(seg.end)
            color = GREEN if seg.keep else DEL
            p.fillRect(int(sx), self.mm_top, max(1, int(ex - sx)), self.mm_h, color)
        # 当前视口框
        v0 = self._mm_t2x(self.view_start)
        v1 = self._mm_t2x(self.view_start + self._view_w())
        p.setPen(QPen(MM_VIEW, 1))
        p.drawRect(int(v0), self.mm_top, max(4, int(v1 - v0)), self.mm_h)
        # 播放头在概览图上的位置
        pm = self._mm_t2x(self.playhead)
        p.setPen(QPen(QColor(255, 255, 255, 140), 1))
        p.drawLine(int(pm), self.mm_top, int(pm), self.mm_top + self.mm_h)

    # ---------- 交互 ----------
    def _hit(self, pos):
        x, y = pos.x(), pos.y()
        if not (self.top - 18 <= y <= self.bottom + 8):
            return None
        if abs(self._t2x(self.playhead) - x) <= 8:
            return ("playhead",)
        disp = self._disp_segs()
        for i, seg in enumerate(disp):
            x0 = self._t2x(seg.start)
            x1 = self._t2x(seg.end)
            # 太窄的片段：对称扩大到最小可点击宽度，避免点不到
            if x1 - x0 < MIN_HIT_W:
                cx = (x0 + x1) / 2.0
                x0 = cx - MIN_HIT_W / 2.0
                x1 = cx + MIN_HIT_W / 2.0
            if x0 - EDGE_GRAB <= x <= x1 + EDGE_GRAB:
                d_l = abs(x - x0)
                d_r = abs(x - x1)
                # 浏览模式下不提供边缘拖动（预览成片用）
                if min(d_l, d_r) <= EDGE_GRAB and not self.browse_mode:
                    return ("edge_left", i) if d_l <= d_r else ("edge_right", i)
                return ("body", i)
        return ("empty",)

    def _is_locked(self, hit):
        """锁定模式下，命中已删除片段返回 True（该次交互应被忽略）。"""
        if not self.lock_deleted:
            return False
        if hit is None:
            return True
        kind = hit[0]
        if kind in ("body", "edge_left", "edge_right"):
            return not self._orig_seg(hit[1]).keep
        return False

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        x, y = e.pos().x(), e.pos().y()
        # 迷你概览图：点击跳转视口中心，并开始拖动
        if self.mm_top <= y <= self.mm_top + self.mm_h:
            self._mm_center_view(self._mm_x2t(x))
            self._drag = ("mm",)
            self.update()
            return
        # 顶部片段编号条：点击编号方块 = 选中该片段并跳转（小片段也点得到）
        if CHIP_TOP <= y <= CHIP_TOP + CHIP_H and self._disp_segs():
            di = self._chip_at(x)
            if di is not None:
                orig_idx = self._orig_of(di)
                if self.lock_deleted and not self.segments[orig_idx].keep:
                    self.update()
                    return
                self.selected = orig_idx
                self.selectionChanged.emit(orig_idx)
                self.seekRequested.emit(self.segments[orig_idx].start)
                self.update()
            return
        hit = self._hit(e.pos())
        if hit is None:
            # 点击在片段条纵向范围之外（如编号条与标尺之间的缝隙）：忽略
            self.update()
            return
        # 锁定：已删除片段不可选中/拖动，直接忽略，防误触
        if self._is_locked(hit):
            self.update()
            return
        kind = hit[0]
        if kind == "playhead":
            self._drag = ("playhead",)
            self._last_scrub_t = 0.0   # 让拖动后的第一次移动立即 seek
            self.scrubStarted.emit()   # 刮擦预览：暂停播放，松手停在那一帧
        elif kind == "edge_left":
            self.selected = self._orig_of(hit[1])
            self._drag = ("edge_left", hit[1])
            self.selectionChanged.emit(self._orig_of(hit[1]))
        elif kind == "edge_right":
            self.selected = self._orig_of(hit[1])
            self._drag = ("edge_right", hit[1])
            self.selectionChanged.emit(self._orig_of(hit[1]))
        elif kind == "body":
            self.selected = self._orig_of(hit[1])
            self.selectionChanged.emit(self._orig_of(hit[1]))
        elif kind == "empty":
            self._emit_seek(self._x2t(x))
        self.update()

    def mouseMoveEvent(self, e):
        # 拖动中
        if self._drag is not None:
            x = e.pos().x()
            kind = self._drag[0]
            if kind == "mm":
                # 拖动概览图：视口中心跟随鼠标
                self._mm_center_view(self._mm_x2t(x))
            else:
                t = min(max(0.0, self._x2t(x)), self._disp_duration())
                if kind == "playhead":
                    self.playhead = t
                    # 刮擦预览：拖动中节流 seek（约 5 次/秒），画面跟随鼠标走，
                    # 又不会因高频 seek 阻塞解码导致卡顿；松手再精确定位一次。
                    now = time.monotonic()
                    if now - self._last_scrub_t >= 0.2:
                        self._last_scrub_t = now
                        self._emit_seek(t)
                elif kind == "edge_left":
                    idx = self._drag[1]
                    self.segments[idx].start = min(t, self.segments[idx].end - 0.2)
                elif kind == "edge_right":
                    idx = self._drag[1]
                    self.segments[idx].end = max(t, self.segments[idx].start + 0.2)
            self.update()
            return
        # 顶部编号条悬停：手型光标提示可点击
        y = e.pos().y()
        if CHIP_TOP <= y <= CHIP_TOP + CHIP_H:
            ch = self._chip_at(e.pos().x())
            if ch is not None and self.lock_deleted and not self._orig_seg(ch).keep:
                ch = None
            hovered = ch if ch is not None else -1
            if hovered != self._chip_hover:
                self._chip_hover = hovered
                self.update()
            self.setCursor(Qt.PointingHandCursor if ch is not None
                           else Qt.ArrowCursor)
            return
        if self._chip_hover != -1:
            self._chip_hover = -1
            self.update()

        # 悬停状态
        hit = self._hit(e.pos())
        kind = hit[0] if hit else "empty"
        # 锁定：已删除片段视为不可交互（无手型/双向箭头光标，不高亮）
        if kind == "body" and self.lock_deleted and not self._orig_seg(hit[1]).keep:
            hover = -1
            kind = "empty"
            if hover != self._hover:
                self._hover = hover
                self.update()
            self.unsetCursor()
            return
        hover = hit[1] if kind == "body" else -1
        if hover != self._hover:
            self._hover = hover
            self.update()
        if kind in ("edge_left", "edge_right"):
            self.setCursor(Qt.SizeHorCursor)
        elif kind == "playhead":
            self.setCursor(Qt.SplitHCursor)
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            kind = self._drag[0]
            self._drag = None
            if kind == "playhead":
                # 拖动播放头松手后才执行一次 seek，避免拖动过程中高频 seek 卡顿
                self._emit_seek(self.playhead)
            elif kind not in ("mm",):
                self.segmentsEdited.emit()
        self.update()

    def mouseDoubleClickEvent(self, e):
        # 顶部编号条：双击 = 选中并播放该片段
        y = e.pos().y()
        if CHIP_TOP <= y <= CHIP_TOP + CHIP_H and self._disp_segs():
            di = self._chip_at(e.pos().x())
            if di is not None:
                orig_idx = self._orig_of(di)
                if self.lock_deleted and not self.segments[orig_idx].keep:
                    return
                self.selected = orig_idx
                self.selectionChanged.emit(orig_idx)
                self.segmentPlayRequested.emit(orig_idx)
                self.update()
            return
        hit = self._hit(e.pos())
        if hit and hit[0] == "body":
            if self.lock_deleted and not self._orig_seg(hit[1]).keep:
                return   # 锁定：忽略已删除片段
            di = hit[1]
            self.selected = self._orig_of(di)
            self.selectionChanged.emit(self._orig_of(di))
            self.segmentPlayRequested.emit(self._orig_of(di))
            self.update()

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        if e.modifiers() & Qt.ShiftModifier:
            # 平移（带动画）
            target = self.view_start + (-delta / 120.0) * self._view_w() * 0.2
            self._animate_view(self.pps, target, duration=120)
        else:
            # 以鼠标为中心平滑缩放
            factor = 1.25 if delta > 0 else 1 / 1.25
            t = self._x2t(e.position().x())
            new_pps = min(800, max(0.2, self.pps * factor))
            new_vs = t - (e.position().x() - self.margin) / new_pps
            self._animate_view(new_pps, new_vs, duration=120)
        self.update()

    def resizeEvent(self, e):
        self._clamp_view()
        self._sync_scrollbar()
        self.sb.setGeometry(0, self.height() - 14, self.width(), 14)
        super().resizeEvent(e)
