# -*- coding: utf-8 -*-
"""主窗口（PySide6，模仿 LosslessCut）：
   左侧多视频目录 / 中间视频播放器 / 右侧片段目录 / 下方参数 + 时间轴。

   防呆设计：
     - 会话自动保存：分析结果、手动调整实时写入本地，崩溃/误关后启动可一键恢复
     - 同一视频不重复导入；原视频被移动/删除时自动跳过，不崩溃
     - 快捷键：空格=播放/暂停，I/O=设起点/终点，Delete=保留/删除，←/→=逐帧
"""
import os
import subprocess
import sys
import tempfile
import threading

# 防呆：直接运行本文件（而非 main.py）时，也能找到项目根目录的 core/ui/utils 包
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QSettings, QSize, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QPushButton, QSplitter,
                               QVBoxLayout, QWidget)

from core import __version__
from core.exporter import export, export_segments, file_name_for
from core.models import Config
from core.motion_analyzer import analyze_motion
from core.segment_decider import decide_segments, summarize
from core.session import VideoState, load_session, save_session
from ui.export_dialog import ExportDialog
from ui.export_progress import ExportProgressDialog
from ui.player import PlayerWidget
from ui.segment_list import SegmentList
from ui.timeline import Timeline, display_number, fmt_time
from utils.ffmpeg_utils import FFMPEG, get_duration, probe_stream, run

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv",
              ".m4v", ".mpg", ".mpeg", ".ts", ".webm")


class AnalyzeWorker(QThread):
    done = Signal(object, object, object)   # config, scores, segments
    progress = Signal(float, int, int)      # 分析进度：比例、已完成块数、总块数
    failed = Signal(str)

    def __init__(self, video, cfg, parent=None):
        super().__init__(parent)
        self.video = video
        self.cfg = cfg
        self.cancel = threading.Event()   # 关窗口时置位，停止 ffmpeg 解码

    def run(self):
        try:
            scores = analyze_motion(self.video, self.cfg,
                                    progress_cb=self.progress.emit,
                                    cancel_event=self.cancel)
            segments = decide_segments(scores, self.cfg)
            self.done.emit(self.cfg, scores, segments)
        except Exception as exc:
            self.failed.emit("分析失败：{}".format(exc))


class ExportWorker(QThread):
    done = Signal(list)
    progress = Signal(float, int, int, str)   # 比例、已完成段数、总段数、当前文件名
    failed = Signal(str)
    cancelled = Signal()                     # 用户点了取消（不算出错）

    def __init__(self, video, segments, out_dir, prefix, digits, seq_start,
                 mode, ext, merge, parent=None):
        super().__init__(parent)
        self.video = video
        self.segments = segments
        self.out_dir = out_dir
        self.prefix = prefix
        self.digits = digits
        self.seq_start = seq_start
        self.mode = mode
        self.ext = ext
        self.merge = merge
        self.cancel = threading.Event()   # 取消导出：停掉 ffmpeg

    def run(self):
        try:
            if self.merge:
                out_path = os.path.join(
                    self.out_dir, "{}_成片.{}".format(self.prefix, self.ext))
                export(self.video, self.segments, out_path, mode=self.mode,
                       progress_cb=self.progress.emit,
                       cancel_event=self.cancel)
                self.done.emit([out_path])
            else:
                files = export_segments(
                    self.video, self.segments, self.out_dir, self.prefix,
                    seq_digits=self.digits, seq_start=self.seq_start,
                    mode=self.mode, ext=self.ext,
                    progress_cb=self.progress.emit,
                    cancel_event=self.cancel)
                self.done.emit(files)
        except RuntimeError as exc:
            if "取消" in str(exc):
                self.cancelled.emit()
            else:
                self.failed.emit("导出失败：{}".format(exc))
        except Exception as exc:
            self.failed.emit("导出失败：{}".format(exc))


class MainWindow(QMainWindow):
    thumbnailReady = Signal(int, str)   # 缩略图生成完成(片段下标, png路径)
    coverReady = Signal(int, str)       # 左侧目录封面生成完成(视频下标, png路径)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoCut")

        # 无边框窗口：去掉 Windows 原生标题栏
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # 窗口 resize 相关
        self._resizing = False
        self._resize_edge = None   # 'n','s','e','w','ne','nw','se','sw'
        self._resize_start = None  # (global_pos, original_geo)
        self._border = 6           # 边缘检测宽度

        self.setMinimumSize(900, 600)

        self.video_states = []      # 所有已导入的视频状态
        self._active_idx = -1       # 当前打开的视频下标
        self.video_path = ""
        self.duration = 0.0
        self.fps = 30.0
        self.segments = []
        self._analyzer = None
        self._exporter = None
        self.thumb_root = tempfile.mkdtemp(prefix="autocut_thumb_")
        self._browse_seeking = False   # 浏览模式跳转中（防 seek 反馈循环）
        self._browse_target = -1.0     # 浏览模式当前 seek 目标秒
        self._loop_seg = None          # 循环播放的片段（点右侧切片触发；None=不循环）
        self._loop_seeking = False     # 循环跳回 seek 中（防旧位置回报反复触发）
        self._export_dlg = None        # 导出进度弹窗（导出中显示）

        self._settings = QSettings("AutoCut", "AutoCut")

        self._build_ui()
        self._wire()
        self._setup_shortcuts()
        self.thumbnailReady.connect(self.seg_list.set_thumbnail)
        self.coverReady.connect(self._on_cover_ready)
        # 会话恢复延后到窗口显示之后再弹（QTimer(0) 在事件循环启动后触发），
        # 否则恢复对话框会阻塞在主窗口显示之前，用户以为程序没打开
        QTimer.singleShot(0, self._restore_prev_session)

        # 恢复窗口状态
        self._restore_window_state()

    # ================= 界面 =================
    def _build_ui(self):
        # ========== 自定义标题栏（无边框窗口的 Header） ==========
        self.title_bar = QWidget()
        self.title_bar.setObjectName("header")
        self.title_bar.setFixedHeight(44)
        self.title_bar.setMouseTracking(True)
        title_lay = QHBoxLayout(self.title_bar)
        title_lay.setContentsMargins(12, 0, 0, 0)
        title_lay.setSpacing(8)

        # Logo 区域
        logo = QLabel("A")
        logo.setStyleSheet("font-size: 16px; font-weight: 700; color: #5B8DEF;")
        title_lay.addWidget(logo)

        title = QLabel("AutoCut")
        title.setStyleSheet("font-weight: 600; font-size: 14px; color: #F2F4F7;")
        title_lay.addWidget(title)

        # 版本号跟在软件名后面（小灰字）
        lbl_ver = QLabel("v{}".format(__version__))
        lbl_ver.setStyleSheet(
            "font-size: 11px; color: #626B76; background: transparent;")
        title_lay.addWidget(lbl_ver)

        # 分隔线
        sep0 = QLabel("│")
        sep0.setStyleSheet("color: rgba(255,255,255,0.12); background: transparent;")
        title_lay.addWidget(sep0)

        # ---- Header 功能按钮：素材库 / 设置 / 开发者信息 ----
        self.btn_library = QPushButton("素材库")
        self.btn_library.setObjectName("header_btn")
        self.btn_library.setCheckable(True)
        self.btn_library.setCursor(Qt.PointingHandCursor)
        self.btn_library.setToolTip("已导入的视频列表：点击展开 / 收起 [Esc 关闭]")
        self.btn_library.toggled.connect(self._toggle_material)
        title_lay.addWidget(self.btn_library)

        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("header_btn")
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setToolTip("软件设置")
        self.btn_settings.clicked.connect(self._show_settings_menu)
        title_lay.addWidget(self.btn_settings)

        self.btn_about = QPushButton("开发者信息")
        self.btn_about.setObjectName("header_btn")
        self.btn_about.setCursor(Qt.PointingHandCursor)
        self.btn_about.setToolTip("关于 AutoCut")
        self.btn_about.clicked.connect(self._show_about)
        title_lay.addWidget(self.btn_about)

        # 当前视频名（可伸缩）
        self.lbl_file = QLabel("未选择视频")
        self.lbl_file.setObjectName("dim")
        self.lbl_file.setStyleSheet("font-size: 12px;")
        title_lay.addWidget(self.lbl_file, stretch=1)

        # 统计信息（右侧）
        self.lbl_stats = QLabel("")
        self.lbl_stats.setObjectName("dim")
        self.lbl_stats.setStyleSheet("font-size: 11px;")
        title_lay.addWidget(self.lbl_stats)

        # 窗口控制按钮
        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("win_btn")
        self.btn_min.setToolTip("最小化")
        self.btn_min.clicked.connect(self.showMinimized)

        self.btn_max = QPushButton("□")
        self.btn_max.setObjectName("win_btn")
        self.btn_max.setToolTip("最大化 / 还原")
        self.btn_max.clicked.connect(self._toggle_max_restore)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("win_close")
        self.btn_close.setToolTip("关闭")
        self.btn_close.clicked.connect(self.close)

        title_lay.addWidget(self.btn_min)
        title_lay.addWidget(self.btn_max)
        title_lay.addWidget(self.btn_close)

        # Header 拖动支持
        self._drag_pos = None
        self.title_bar.mousePressEvent = self._title_mouse_press
        self.title_bar.mouseMoveEvent = self._title_mouse_move
        self.title_bar.mouseReleaseEvent = self._title_mouse_release
        self.title_bar.mouseDoubleClickEvent = self._title_mouse_dblclick

        # ========== 左侧收纳式素材库入口在 Header（见下方素材库按钮） ==========

        # ========== 中间工作区：播放器 + 时间轴 ==========
        workspace = QWidget()
        work_lay = QVBoxLayout(workspace)
        work_lay.setContentsMargins(0, 0, 0, 0)
        work_lay.setSpacing(0)

        # 播放器
        self.player = PlayerWidget()
        work_lay.addWidget(self.player, stretch=1)

        # 播放器下方操作栏
        action_bar = QWidget()
        action_bar.setObjectName("panel")
        action_bar.setFixedHeight(44)
        action_lay = QHBoxLayout(action_bar)
        action_lay.setContentsMargins(12, 0, 12, 0)
        action_lay.setSpacing(8)

        self.btn_analyze = QPushButton("自动分析")
        self.btn_analyze.setToolTip("自动识别废镜头并删除，保留有效镜头（约十几秒）")
        self.btn_fit = QPushButton("适应时间轴")
        self.btn_fit.setToolTip("让时间轴完整显示整个视频")
        self.btn_focus = QPushButton("聚焦镜头")
        self.btn_focus.setToolTip("把时间轴放大到选中的镜头，方便精裁")

        action_lay.addWidget(self.btn_analyze)
        action_lay.addWidget(self.btn_fit)
        action_lay.addWidget(self.btn_focus)
        action_lay.addStretch()

        # 进度条（隐藏，用状态栏文字代替）
        self.progress = QProgressBar()
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        self.progress.setMaximumWidth(200)
        action_lay.addWidget(self.progress)

        work_lay.addWidget(action_bar)

        # 时间轴区域
        timeline_area = QWidget()
        timeline_area.setObjectName("panel")
        tl_lay = QVBoxLayout(timeline_area)
        tl_lay.setContentsMargins(0, 0, 0, 0)
        tl_lay.setSpacing(0)

        # 镜头跳转按钮条（时间轴上方）
        nav_bar = QWidget()
        nav_lay = QHBoxLayout(nav_bar)
        nav_lay.setContentsMargins(12, 6, 12, 6)
        nav_lay.setSpacing(8)

        self.btn_prev_seg = QPushButton("◀")
        self.btn_prev_seg.setObjectName("nav_arrow")
        self.btn_prev_seg.setToolTip("上一个保留镜头 [↑]")
        self.btn_prev_seg.clicked.connect(self._jump_prev_seg)

        self.btn_next_seg = QPushButton("▶")
        self.btn_next_seg.setObjectName("nav_arrow")
        self.btn_next_seg.setToolTip("下一个保留镜头 [↓]")
        self.btn_next_seg.clicked.connect(self._jump_next_seg)

        nav_lay.addWidget(self.btn_prev_seg)
        nav_lay.addWidget(self.btn_next_seg)
        nav_lay.addStretch()

        # 时间轴编号条与跳转提示
        self.lbl_seg_nav = QLabel("")
        self.lbl_seg_nav.setObjectName("dim")
        nav_lay.addWidget(self.lbl_seg_nav)

        tl_lay.addWidget(nav_bar)
        self.timeline = Timeline()
        tl_lay.addWidget(self.timeline)

        # 状态栏
        status_bar = QWidget()
        status_lay = QHBoxLayout(status_bar)
        status_lay.setContentsMargins(12, 4, 12, 4)
        status_lay.setSpacing(8)

        self.lbl_status = QLabel("就绪")
        self.lbl_status.setObjectName("dim")
        status_lay.addWidget(self.lbl_status)
        status_lay.addStretch()

        tl_lay.addWidget(status_bar)
        work_lay.addWidget(timeline_area)

        # ========== 右侧：片段目录（可伸缩） ==========
        right_panel = QWidget()
        right_panel.setObjectName("panel")
        right_panel.setMinimumWidth(260)
        right_panel.setMaximumWidth(480)
        right_lay = QVBoxLayout(right_panel)
        right_lay.setContentsMargins(8, 10, 8, 10)
        right_lay.setSpacing(8)

        # 片段目录标题
        seg_title = QLabel("片段")
        seg_title.setObjectName("dim")
        seg_title.setStyleSheet("font-size: 11px; font-weight: 500; letter-spacing: 0.5px;")
        right_lay.addWidget(seg_title)

        # 片段列表
        self.seg_list = SegmentList()
        right_lay.addWidget(self.seg_list, stretch=1)

        # 导出按钮（主按钮，放在右侧面板底部）
        self.btn_export = QPushButton("导出")
        self.btn_export.setObjectName("primary")
        self.btn_export.setToolTip("按保留镜头导出（每次都会弹出设置和确认）")
        self.btn_export.setFixedHeight(40)
        right_lay.addWidget(self.btn_export)

        # ========== 素材库抽屉（布局内面板，Header「素材库」按钮切换显示） ==========
        # 放进布局而不是悬浮窗口：点开后中间区自动让位，再点收起，彻底无遮挡问题
        self.material_panel = QWidget()
        self.material_panel.setObjectName("panel_elevated")
        self.material_panel.setFixedWidth(220)
        self.material_panel.setVisible(False)   # 默认收起
        mp_lay = QVBoxLayout(self.material_panel)
        mp_lay.setContentsMargins(10, 10, 10, 10)
        mp_lay.setSpacing(8)

        # 导入按钮（主按钮样式）
        self.btn_open = QPushButton("导入视频")
        self.btn_open.setObjectName("primary")
        self.btn_open.setToolTip("导入一个或多个视频（可多选）")
        self.btn_open.setFixedHeight(34)
        mp_lay.addWidget(self.btn_open)

        mp_title = QLabel("素材库")
        mp_title.setObjectName("dim")
        mp_title.setStyleSheet(
            "font-size: 11px; font-weight: 500; letter-spacing: 0.5px;")
        mp_lay.addWidget(mp_title)

        # 完整视频列表（带文字说明）
        self.file_list = QListWidget()
        self.file_list.setIconSize(QSize(64, 36))
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.setToolTip("右键可移除视频")
        self.file_list.setSpacing(2)
        mp_lay.addWidget(self.file_list, stretch=1)

        # ========== 组装主布局 ==========
        central = QWidget()
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)
        main_lay.addWidget(self.title_bar)

        # 内容区：QSplitter（中间工作区 + 右侧面板）
        content = QSplitter(Qt.Horizontal)
        content.setObjectName("panel")
        content.setContentsMargins(6, 6, 6, 6)
        content.setHandleWidth(1)
        content.addWidget(workspace)
        content.addWidget(right_panel)

        # 初始比例：中间优先，右侧约 300px
        content.setSizes([800, 300])
        content.setStretchFactor(0, 1)  # 中间优先拉伸
        content.setStretchFactor(1, 0)  # 右侧不拉伸

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(6, 6, 6, 6)
        body_lay.setSpacing(6)
        body_lay.addWidget(self.material_panel)   # 素材库抽屉（默认隐藏）
        body_lay.addWidget(content, stretch=1)

        main_lay.addWidget(body, stretch=1)
        self.setCentralWidget(central)

        # 保存 splitter 引用以便后续操作
        self._splitter = content

        self.statusBar().showMessage("导入视频 → 自动分析 → 手动微调 → 导出")

    def _wire(self):
        self.btn_open.clicked.connect(self.open_videos)
        self.btn_analyze.clicked.connect(self.start_analysis)
        self.btn_fit.clicked.connect(self.timeline.fit)
        self.btn_focus.clicked.connect(self._focus_selected)
        self.btn_export.clicked.connect(self.start_export)

        self.player.positionChanged.connect(self.timeline.set_playhead)
        self.player.positionChanged.connect(self._on_player_pos)
        self.player.inPointPressed.connect(self._set_in_point)
        self.player.outPointPressed.connect(self._set_out_point)
        self.player.browseModeChanged.connect(self._on_browse_toggled)
        self.player.lockModeChanged.connect(self._on_lock_toggled)

        self.timeline.seekRequested.connect(self.player.seek)
        # 用户主动操作（点时间轴 / 拖播放头 / 拖进度条）→ 退出切片循环播放
        self.timeline.seekRequested.connect(self._clear_loop)
        self.timeline.scrubStarted.connect(self._clear_loop)
        self.player.userSeeked.connect(self._clear_loop)
        # 刮擦预览：拖动时间轴播放头时先暂停播放，拖动中画面跟随鼠标走，
        # 松手后停在那一帧（不强制继续播放）
        self.timeline.scrubStarted.connect(self.player.pause)
        self.timeline.segmentsEdited.connect(self._on_segments_edited)
        self.timeline.selectionChanged.connect(self._on_select)
        self.timeline.segmentPlayRequested.connect(self._play_segment)

        # 右侧片段目录：单击=选中并循环播放；双击=选中+自动聚焦+播放
        self.seg_list.segClicked.connect(self._loop_play_segment)
        self.seg_list.segDoubleClicked.connect(self._play_segment)
        self.seg_list.keepToggled.connect(self._on_keep_toggled)
        # 镜头名输入完成（回车/点到别处）时保存会话，防止程序意外退出丢名字
        self.seg_list.labelEdited.connect(self._save_session_now)

        self.file_list.itemClicked.connect(self._on_file_clicked)
        self.file_list.customContextMenuRequested.connect(self._file_menu)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Space"), self, self.player.toggle_play)
        QShortcut(QKeySequence("I"), self, self._set_in_point)
        QShortcut(QKeySequence("O"), self, self._set_out_point)
        QShortcut(QKeySequence("Delete"), self, self._delete_selected)
        QShortcut(QKeySequence(Qt.Key_Left), self,
                  lambda: self.player.step_frame(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self,
                  lambda: self.player.step_frame(1))
        # ↑↓ 跳转上一个/下一个保留镜头
        QShortcut(QKeySequence(Qt.Key_Up), self, self._jump_prev_seg)
        QShortcut(QKeySequence(Qt.Key_Down), self, self._jump_next_seg)
        # Esc 收起素材库面板（若在展开中）
        QShortcut(QKeySequence("Esc"), self, self._esc_close_material)

    # ================= 参数 =================
    def _get_config(self):
        # 固定通用参数即可：只做粗略裁剪，之后靠手动精调
        return Config()

    def _focus_selected(self):
        """把时间轴平滑放大到选中镜头（第二套：镜头内精裁）。"""
        idx = self.timeline.selected
        if not (0 <= idx < len(self.segments)):
            QMessageBox.information(
                self, "提示", "请先在时间轴或右侧列表点选一个镜头")
            return
        # 锁定：已删除片段不可精调
        if self.timeline.lock_deleted and not self.segments[idx].keep:
            self.lbl_status.setText("锁定中：已删除的废镜头不可精调，先解锁再操作")
            return
        # 精裁时退出浏览模式，避免自动跳段干扰
        if self.player.btn_browse.isChecked():
            self.player.btn_browse.setChecked(False)
        seg = self.segments[idx]
        w = max(200, self.timeline.width())
        target_pps = min(800, (w - 2 * self.timeline.margin)
                         / max(seg.duration, 0.2))
        target_vs = max(0.0, seg.start - 0.5)
        self.timeline._animate_view(target_pps, target_vs)
        num, _ = display_number(self.segments, idx)
        self.lbl_status.setText(
                "已聚焦 镜头{}：拖动时间轴边缘或按 I/O 精调切点".format(num))

    def _jump_prev_seg(self):
        """跳转到上一个保留镜头。"""
        self._jump_seg(-1)

    def _jump_next_seg(self):
        """跳转到下一个保留镜头。"""
        self._jump_seg(1)

    def _jump_seg(self, direction):
        """在保留镜头之间跳转（direction: -1=上一个, 1=下一个）。"""
        if not self.segments:
            return
        keeps = [i for i, s in enumerate(self.segments) if s.keep]
        if not keeps:
            self.lbl_status.setText("没有保留镜头")
            return
        cur = self.timeline.selected
        if cur < 0 or cur not in keeps:
            # 没选中或选中的是删除段：跳到第一个/最后一个保留镜头
            target = keeps[0] if direction > 0 else keeps[-1]
        else:
            idx = keeps.index(cur) + direction
            if idx < 0 or idx >= len(keeps):
                self.lbl_status.setText("已是第一个/最后一个保留镜头")
                return
            target = keeps[idx]
        # 选中并跳转
        self.timeline.selected = target
        self.timeline.update()
        self.seg_list.select_index(target)
        self.player.play_at(self.segments[target].start)
        num, _ = display_number(self.segments, target)
        self.lbl_status.setText("跳转到 镜头{}".format(num))
        self.lbl_seg_nav.setText("镜头 {} / {}".format(
            keeps.index(target) + 1, len(keeps)))

    # ================= 锁定（防止误触已删除片段） =================
    def _on_lock_toggled(self, checked):
        self.timeline.lock_deleted = checked
        if checked:
            self.lbl_status.setText(
                "已锁定：已删除的废镜头不可点击/拖动，放心点镜头号")
        else:
            self.lbl_status.setText("已解锁：可以再次调整删除的废镜头")

    # ================= 浏览镜头（删除段消失，保留段拼接成片连续播放） =================
    def _on_browse_toggled(self, checked):
        if not checked:
            self._browse_seeking = False
            self._browse_target = -1.0
            self.timeline.exit_browse()
            self.lbl_status.setText("已退出浏览镜头模式")
            return
        if not self.segments or not any(s.keep for s in self.segments):
            self._browse_seeking = False
            self._browse_target = -1.0
            self.timeline.exit_browse()
            self.player.btn_browse.blockSignals(True)
            self.player.btn_browse.setChecked(False)
            self.player.btn_browse.blockSignals(False)
            self.lbl_status.setText("没有可浏览的保留镜头，请先分析")
            return
        # 浏览与循环互斥：进浏览前先退出切片循环
        self._clear_loop()
        # 删除段直接消失，时间轴只显示保留段拼接成的“成片”
        self.timeline.enter_browse()
        # 从成片起点（第一个保留镜头）开始连续播放
        first = next(s.start for s in self.segments if s.keep)
        self._browse_seeking = True
        self._browse_target = first
        self.player.seek(first)
        self.lbl_status.setText(
            "浏览镜头：已隐藏废镜头，从第一个保留镜头开始连续播放")

    def _seg_at(self, seconds):
        """返回 seconds 所在的片段；不在任何片段（如片尾）返回 None。"""
        for seg in self.segments:
            if seg.start <= seconds < seg.end:
                return seg
        return None

    def _on_player_pos(self, seconds):
        """位置回报：优先处理切片循环播放，其次浏览模式跳段。

        循环播放（点右侧切片触发）：到段尾自动跳回段首继续播。
        防重入：seek 是异步的，positionChanged 生效前还会报旧位置
        （仍在段尾）。跳回前挂起 `_loop_seeking`，等位置真正回到段内再恢复，
        否则旧位置会反复触发跳回（无限循环卡在第一帧）。

        浏览模式：播放进入删除段时，自动跳到下一个保留镜头。
        同理挂起 `_browse_seeking`，等位置真正到达目标保留段后再恢复。
        """
        # ---- 切片循环：到段尾跳回段首 ----
        if self._loop_seg is not None:
            if self._loop_seeking:
                # 跳回 seek 尚未生效（回报的还是段尾旧位置）：等回到段内
                if (seconds < self._loop_seg.end - 0.05
                        and seconds >= self._loop_seg.start - 1.0):
                    self._loop_seeking = False
                return
            # 暂停时不跳（逐帧精调 / 暂停查看不受干扰），继续播放才循环；
            # 段尾就是视频结尾时播放器会自动停，此时也要拉回来续播
            if (not self.player.is_paused()
                    and seconds >= self._loop_seg.end - 0.05):
                self._loop_seeking = True
                self.player.seek(self._loop_seg.start)
                self.player.player.play()   # 视频播到末尾自动停了也能续上
                return
        # ---- 浏览模式跳段（原有逻辑） ----
        if not self.player.browse_enabled:
            return
        if self._browse_seeking:
            # seek 尚未生效：位置到达目标且落在保留段内，才算真正生效
            if seconds >= self._browse_target - 0.1:
                seg = self._seg_at(seconds)
                if seg is None or seg.keep:
                    self._browse_seeking = False
            return
        if not self.player.is_playing():
            return
        seg = self._seg_at(seconds)
        if seg is not None and not seg.keep:
            nxt = self._next_kept_start(self.segments.index(seg))
            if nxt is None:
                self.player.player.pause()
                self.lbl_status.setText("浏览结束：已看完所有保留镜头")
            else:
                self._browse_seeking = True
                self._browse_target = nxt
                self.player.seek(nxt)

    def _next_kept_start(self, from_idx):
        for seg in self.segments[from_idx + 1:]:
            if seg.keep:
                return seg.start
        return None

    # ================= 左侧多视频目录 =================
    def _active(self):
        """当前打开的视频状态。"""
        if 0 <= self._active_idx < len(self.video_states):
            return self.video_states[self._active_idx]
        return None

    def _init_state(self, st):
        st.duration = get_duration(st.path)
        _, _, fps = probe_stream(st.path)
        st.fps = fps or 30.0
        if st.duration <= 0:
            QMessageBox.warning(
                self, "提示",
                "读不到时长，可能文件损坏：\n{}".format(os.path.basename(st.path)))

    def open_videos(self):
        """一次导入一个或多个视频（防呆：不重复添加）。"""
        last = self._settings.value("lastDir", "")
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择视频（可一次选多个）", last,
            "视频文件 (*{})".format(" *".join(VIDEO_EXTS)))
        if not paths:
            return
        self._settings.setValue("lastDir", os.path.dirname(paths[0]))
        added = 0
        for p in paths:
            if any(st.path == p for st in self.video_states):
                continue
            st = VideoState(path=p)
            self._init_state(st)
            self.video_states.append(st)
            self._gen_cover(st, len(self.video_states) - 1)
            added += 1
        if added:
            # 新视频必须填进左侧列表，否则列表是空的、用户无法点击切换
            self._refresh_file_items()
            self._switch_to(len(self.video_states) - 1)
            self._save_session_now()
            self.statusBar().showMessage(
                "已导入 {} 个视频，当前：{}".format(
                    added, os.path.basename(self.video_path)))

    def _on_file_clicked(self, item):
        idx = int(item.data(Qt.UserRole))
        if idx != self._active_idx:
            self._switch_to(idx)

    def _file_menu(self, pos):
        lst = self.sender() or self.file_list   # 支持完整列表和窄条图标列表
        item = lst.itemAt(pos)
        menu = QMenu(self)
        act_remove = menu.addAction("从列表移除该视频")
        act_open = menu.addAction("打开所在文件夹")
        menu.addSeparator()
        act_clear = menu.addAction("清空列表")
        act_remove.setEnabled(item is not None)
        act_open.setEnabled(item is not None)
        chosen = menu.exec(lst.mapToGlobal(pos))
        if not chosen:
            return
        if chosen == act_remove and item is not None:
            self._remove_video(int(item.data(Qt.UserRole)))
        elif chosen == act_clear:
            self._clear_videos()
        elif chosen == act_open and item is not None:
            st = self.video_states[int(item.data(Qt.UserRole))]
            self._open_folder(os.path.dirname(st.path))

    def _remove_video(self, idx):
        if not (0 <= idx < len(self.video_states)):
            return
        del self.video_states[idx]
        if self._active_idx >= idx:
            self._active_idx -= 1
        if not self.video_states:
            self._active_idx = -1
            self.video_path = ""
            self.segments = []
            self.lbl_file.setText("  未选择视频")
            self.timeline.set_segments(1.0, [])
            self.seg_list.set_segments([])
            self._update_stats()
        else:
            self._switch_to(max(0, min(self._active_idx, len(self.video_states) - 1)))
        self._refresh_file_items()
        self._save_session_now()

    def _clear_videos(self):
        if not self.video_states:
            return
        self.video_states = []
        self._active_idx = -1
        self.video_path = ""
        self.segments = []
        self.lbl_file.setText("  未选择视频")
        self.timeline.set_segments(1.0, [])
        self.seg_list.set_segments([])
        self._update_stats()
        self._refresh_file_items()
        self._save_session_now()

    def _refresh_file_items(self):
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for i, st in enumerate(self.video_states):
            name = os.path.basename(st.path)
            if st.analyzed:
                keep = sum(1 for s in st.segments if s.keep)
                name += "  · 保留{}段".format(keep)
            item = QListWidgetItem(name)
            item.setToolTip(st.path)
            item.setData(Qt.UserRole, i)
            if st.cover:
                item.setIcon(QIcon(st.cover))
            self.file_list.addItem(item)
        if self._active_idx >= 0:
            self.file_list.setCurrentRow(self._active_idx)
        self.file_list.blockSignals(False)
        # 素材库按钮 tooltip 显示当前素材数量
        n = len(self.video_states)
        self.btn_library.setToolTip(
            "已导入 {} 个视频 · 点击展开 / 收起".format(n) if n
            else "尚未导入视频 · 点击展开")

    def _switch_to(self, idx):
        """切换到左侧第 idx 个视频，把播放器/时间轴/片段目录全部切过去。"""
        if not (0 <= idx < len(self.video_states)):
            return
        # 切换视频时退出浏览模式，避免用旧视频的片段判断新视频
        if self.player.btn_browse.isChecked():
            self.player.btn_browse.blockSignals(True)
            self.player.btn_browse.setChecked(False)
            self.player.btn_browse.blockSignals(False)
        self._browse_seeking = False
        self._browse_target = -1.0
        self._clear_loop()   # 切视频：旧片段的循环播放立即失效
        self._active_idx = idx
        st = self.video_states[idx]
        self.video_path = st.path
        self.duration = st.duration
        self.fps = st.fps
        self.segments = st.segments
        self.lbl_file.setText("  {}".format(os.path.basename(st.path)))
        self.player.load(st.path)
        # 导入/切换后自动播放，画面立刻出来（不显黑屏空）
        QTimer.singleShot(300, self.player.player.play)
        self.timeline.set_segments(st.duration, self.segments)
        self.timeline.selected = -1
        self.seg_list.set_segments(self.segments)
        for i in sorted(st.thumbs):
            png = os.path.join(st.thumb_dir, "t_{}.png".format(i))
            if os.path.exists(png):
                self.seg_list.set_thumbnail(i, png)
        self.file_list.blockSignals(True)
        self.file_list.setCurrentRow(idx)
        self.file_list.blockSignals(False)
        self._update_stats()
        if st.analyzed:
            self.statusBar().showMessage(
                "当前：{}（已分析，可手动调整）".format(os.path.basename(st.path)))
        else:
            self.statusBar().showMessage(
                "当前：{}（尚未分析，点「自动分析」）".format(os.path.basename(st.path)))

    # ================= 自动分析 =================
    def start_analysis(self):
        st = self._active()
        if st is None:
            QMessageBox.warning(self, "提示", "请先在左侧导入视频")
            return
        if self._analyzer is not None and self._analyzer.isRunning():
            return
        cfg = self._get_config()
        self._set_busy(True)
        self.lbl_status.setText("正在分析「{}」…".format(os.path.basename(st.path)))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._analyzer = AnalyzeWorker(st.path, cfg, self)
        self._analyzer.progress.connect(self._on_analysis_progress)
        self._analyzer.done.connect(self._on_analyzed)
        self._analyzer.failed.connect(self._on_failed)
        self._analyzer.start()

    def _on_analysis_progress(self, p, done=0, total=0):
        self.progress.setValue(int(max(0.0, min(1.0, p)) * 100))
        # 同步在状态栏显示文字进度，进度条没动时也能知道程序在工作
        name = os.path.basename(self.video_path) if self.video_path else ""
        if total:
            self.lbl_status.setText(
                "正在分析「{}」… {}% （第 {}/{} 段）".format(
                    name, int(max(0.0, min(1.0, p)) * 100), done, total))

    def _on_analyzed(self, _cfg, _scores, segments):
        self._set_busy(False)
        self.progress.setRange(0, 100)
        self._clear_loop()   # 重新分析后片段全是新对象，旧循环引用失效
        st = self._active()
        if st is None:
            return
        st.segments = list(segments)
        st.analyzed = True
        self.segments = st.segments
        self.timeline.set_segments(self.duration, self.segments)
        self.timeline.selected = -1
        self.seg_list.set_segments(self.segments)
        self._refresh_file_items()
        self._update_stats()
        self.lbl_status.setText("分析完成：双击镜头播放；勾选「保留」删除；拖时间轴边缘微调")
        self.statusBar().showMessage("分析完成：{}".format(os.path.basename(st.path)))
        self._save_session_now()
        self._gen_thumbnails()

    def _gen_thumbnails(self):
        st = self._active()
        if st is None or not st.analyzed:
            return
        if not st.thumb_dir:
            st.thumb_dir = os.path.join(self.thumb_root, str(len(self.video_states)))
            try:
                os.makedirs(st.thumb_dir, exist_ok=True)
            except OSError:
                pass
        keep_idx = [i for i, s in enumerate(st.segments) if s.keep]
        if not keep_idx:
            return
        video = st.path

        def work():
            for i in keep_idx:
                seg = st.segments[i]
                t = (seg.start + seg.end) / 2.0
                png = os.path.join(st.thumb_dir, "t_{}.png".format(i))
                run([FFMPEG, "-hide_banner", "-loglevel", "error",
                     "-ss", "{:.2f}".format(t), "-i", video,
                     "-frames:v", "1", "-vf", "scale=100:-2", "-y", png])
                if os.path.exists(png):
                    st.thumbs.add(i)
                    self.thumbnailReady.emit(i, png)

        threading.Thread(target=work, daemon=True).start()

    def _gen_cover(self, st, idx):
        """为左侧目录生成视频封面缩略图（后台线程，不卡界面）。"""
        if st.cover:
            return
        video = st.path
        t = min(2.0, st.duration * 0.1) if st.duration > 0 else 1.0
        if not st.thumb_dir:
            st.thumb_dir = os.path.join(self.thumb_root, str(idx))
            try:
                os.makedirs(st.thumb_dir, exist_ok=True)
            except OSError:
                pass
        png = os.path.join(st.thumb_dir, "cover.png")

        def work():
            run([FFMPEG, "-hide_banner", "-loglevel", "error",
                 "-ss", "{:.2f}".format(t), "-i", video,
                 "-frames:v", "1", "-vf", "scale=88:-1", "-y", png])
            if os.path.exists(png):
                st.cover = png
                self.coverReady.emit(idx, png)

        threading.Thread(target=work, daemon=True).start()

    def _on_cover_ready(self, idx, png):
        if 0 <= idx < self.file_list.count():
            self.file_list.item(idx).setIcon(QIcon(png))

    # ================= 交互回调 =================
    def _loop_play_segment(self, idx):
        """点击右侧切片：选中并循环播放该段（到段尾自动跳回段首）。

        退出循环的方式：点时间轴 / 拖播放头 / 拖进度条 / 双击时间轴片段。
        暂停（空格）不会退出循环，按播放继续循环。
        """
        if not (0 <= idx < len(self.segments)):
            return
        # 锁定：忽略已删除片段（防误点废镜头）
        if self.timeline.lock_deleted and not self.segments[idx].keep:
            return
        # 循环与浏览镜头互斥：点切片时退出浏览模式
        if self.player.btn_browse.isChecked():
            self.player.btn_browse.setChecked(False)
        self.timeline.selected = idx
        self.timeline.update()
        self.seg_list.select_index(idx)
        seg = self.segments[idx]
        self._loop_seg = seg
        self._loop_seeking = True   # seek 期间忽略旧位置回报，等真正回到段内
        num, _ = display_number(self.segments, idx)
        self.lbl_status.setText(
            "循环播放 镜头{}：{} ~ {}（{}s）· 点时间轴或拖进度条停止".format(
                num, fmt_time(seg.start), fmt_time(seg.end),
                "{:.1f}".format(seg.duration)))
        # 更新镜头导航显示
        keeps = [i for i, s in enumerate(self.segments) if s.keep]
        if idx in keeps:
            self.lbl_seg_nav.setText("镜头 {} / {}".format(
                keeps.index(idx) + 1, len(keeps)))
        self.player.play_at(seg.start)

    def _clear_loop(self, *args):
        """退出切片循环播放（用户主动跳转 / 切视频 / 重新分析时）。"""
        self._loop_seg = None
        self._loop_seeking = False

    def _on_select(self, idx):
        if 0 <= idx < len(self.segments):
            # 锁定：忽略已删除片段（防右侧列表误点）
            if self.timeline.lock_deleted and not self.segments[idx].keep:
                return
            self.timeline.selected = idx
            self.timeline.update()
            self.seg_list.select_index(idx)
            seg = self.segments[idx]
            self.player.seek(seg.start)
            num, _ = display_number(self.segments, idx)
            self.lbl_status.setText(
                "选中 镜头{}：{} ~ {}（{}s）".format(
                    num, fmt_time(seg.start), fmt_time(seg.end),
                    "{:.1f}".format(seg.duration)))

    def _on_segments_edited(self):
        st = self._active()
        if st is None:
            return
        sel = self.timeline.selected
        self.seg_list.refresh_all()   # 只刷新编号与时间，不重建（保留缩略图）
        if sel >= 0:
            self.seg_list.select_index(sel)
        self._update_stats()
        self._save_session_now()
        # 浏览模式下切点变化后重新拼接
        if self.player.browse_enabled:
            self.timeline.refresh_browse()

    def _play_segment(self, idx):
        """双击时间轴片段：选中并从头播放一遍（不循环，区别于右侧点击），同时自动聚焦。"""
        if 0 <= idx < len(self.segments):
            self._clear_loop()
            # 锁定：忽略已删除片段
            if self.timeline.lock_deleted and not self.segments[idx].keep:
                return
            self.timeline.selected = idx
            self.timeline.update()
            self.seg_list.select_index(idx)
            seg = self.segments[idx]
            num, _ = display_number(self.segments, idx)
            self.lbl_status.setText(
                "播放 镜头{}：{} ~ {}（{}s）".format(
                    num, fmt_time(seg.start), fmt_time(seg.end),
                    "{:.1f}".format(seg.duration)))
            # 自动聚焦到该镜头（方便精裁）
            self._focus_segment(idx)
            self.player.play_at(seg.start)

    def _focus_segment(self, idx):
        """把时间轴平滑放大到指定镜头（供双击自动聚焦调用）。"""
        if not (0 <= idx < len(self.segments)):
            return
        seg = self.segments[idx]
        w = max(200, self.timeline.width())
        target_pps = min(800, (w - 2 * self.timeline.margin)
                         / max(seg.duration, 0.2))
        target_vs = max(0.0, seg.start - 0.3)
        self.timeline._animate_view(target_pps, target_vs)

    def _on_keep_toggled(self, idx, keep):
        """右侧「保留」勾选框 / Delete 键：切换该镜头的保留/删除。"""
        if 0 <= idx < len(self.segments):
            self.segments[idx].keep = keep
            self.seg_list.refresh_all()   # 状态变化后编号重算（独立编号）
            self._update_stats()
            self.timeline.update()
            self._refresh_file_items()   # 左侧同步显示保留段数
            self._save_session_now()
            # 浏览模式下实时重建拼接视图
            if self.player.browse_enabled:
                self.timeline.refresh_browse()

    def _delete_selected(self):
        idx = self.timeline.selected
        if 0 <= idx < len(self.segments):
            self.segments[idx].keep = not self.segments[idx].keep
            self._on_keep_toggled(idx, self.segments[idx].keep)

    def _set_in_point(self):
        self._apply_in_out(out=False)

    def _set_out_point(self):
        self._apply_in_out(out=True)

    def _apply_in_out(self, out=False):
        idx = self.timeline.selected
        if idx < 0 or idx >= len(self.segments):
            QMessageBox.information(self, "提示", "请先在时间轴或列表里点选一个片段")
            return
        # 锁定：已删除片段不可用 I/O 调整
        if self.timeline.lock_deleted and not self.segments[idx].keep:
            self.lbl_status.setText("锁定中：已删除的废镜头不可调整，先解锁再操作")
            return
        seg = self.segments[idx]
        pos = self.player.player.position() / 1000.0
        if out:
            if pos > seg.start + 0.2:
                seg.end = pos
        else:
            if pos < seg.end - 0.2:
                seg.start = pos
        self._on_segments_edited()
        self.timeline.update()

    # ================= 导出 =================
    def start_export(self):
        if not self.video_path:
            QMessageBox.warning(self, "提示", "请先导入视频")
            return
        if not any(s.keep for s in self.segments):
            QMessageBox.warning(self, "提示", "没有保留片段，请先分析并保留片段")
            return
        if self._exporter is not None and self._exporter.isRunning():
            return
        # 默认输出目录 = 视频所在目录（防呆：和源文件放一起，好找）
        prefix = os.path.splitext(os.path.basename(self.video_path))[0]
        default_dir = os.path.dirname(self.video_path)
        # 记忆上次导出选择（目录/位数/格式/方式），省得每次重选
        s = self._settings
        saved = {
            "dir": s.value("export/dir", ""),
            "prefix": s.value("export/prefix", ""),
            # 新键（默认 1 位）：老键里存的是当年默认的 3 位，不迁移
            "digits": s.value("export/seq_digits", 1),
            "seq_start": s.value("export/seq_start", 1),
            "ext": s.value("export/ext", "mp4"),
            "mode": s.value("export/mode", "accurate"),
            "merge": s.value("export/merge", False),
        }
        dlg = ExportDialog(self, default_prefix=prefix, default_dir=default_dir,
                           saved=saved)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        v = dlg.values()
        # 防呆：导出前确认（命名、目录、无损说明、覆盖警告）
        if not self._confirm_export(v):
            return
        # 记住本次选择，下次导出直接填好
        s.setValue("export/dir", v["out_dir"])
        s.setValue("export/prefix", v["prefix"])
        s.setValue("export/seq_digits", v["digits"])
        s.setValue("export/seq_start", v["seq_start"])
        s.setValue("export/ext", v["ext"])
        s.setValue("export/mode", v["mode"])
        s.setValue("export/merge", v["merge"])
        self._set_busy(True)
        self.lbl_status.setText("正在导出…")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._exporter = ExportWorker(
            self.video_path, self.segments, v["out_dir"], v["prefix"],
            v["digits"], v["seq_start"], v["mode"], v["ext"], v["merge"], self)
        self._exporter.progress.connect(self._on_export_progress)
        self._exporter.done.connect(self._on_exported)
        self._exporter.failed.connect(self._on_failed)
        self._exporter.cancelled.connect(self._on_export_cancelled)
        self._exporter.start()
        # 用户友好的导出进度弹窗（大进度条 + 第 N/M 个镜头 + 取消按钮）
        self._export_dlg = ExportProgressDialog(v["mode"], self)
        self._export_dlg.cancelled.connect(self._exporter.cancel.set)
        self._export_dlg.show()

    def _on_export_progress(self, p, cur=0, total=0, fname=""):
        self.progress.setValue(int(max(0.0, min(1.0, p)) * 100))
        if self._export_dlg is not None:
            self._export_dlg.set_progress(p, cur, total, fname)
        # 状态栏同步文字进度（段内实时），进度条不动时也知道在工作
        if total:
            self.lbl_status.setText("正在导出… {}%（已完成 {}/{} 段）".format(
                int(max(0.0, min(1.0, p)) * 100), cur, total))

    def _close_export_dlg(self):
        if self._export_dlg is not None:
            self._export_dlg.close()
            self._export_dlg.deleteLater()
            self._export_dlg = None

    def _on_export_cancelled(self):
        self._close_export_dlg()
        self._set_busy(False)
        self.lbl_status.setText("已取消导出")
        self.statusBar().showMessage("已取消导出")

    def _confirm_export(self, v):
        """导出前的最后确认：检查命名、目录、覆盖情况，提示无损/有损。"""
        keep = sorted([s for s in self.segments if s.keep], key=lambda s: s.start)
        out_dir = v["out_dir"]
        ext = v["ext"]
        merge = v["merge"]
        mode = v["mode"]
        names = []
        if merge:
            names.append("{}_成片.{}".format(v["prefix"], ext))
        else:
            digits = v["digits"]
            start = v["seq_start"]
            for i in range(1, len(keep) + 1):
                names.append(file_name_for(
                    v["prefix"], "{:0{}}".format(start + i - 1, digits),
                    ext, keep[i - 1].label))
        exists = [n for n in names if os.path.exists(os.path.join(out_dir, n))]

        if mode == "fast":
            mode_note = ("切割方式：极速无损（-c copy）＝ 原画质直接裁切，画质零损失\n"
                         "⚠ 切点吸附到最近关键帧，片段头尾可能有约 0~2 秒偏差")
        else:
            mode_note = ("切割方式：精确（推荐）＝ 切点精准到帧，内容和你选的镜头完全一致\n"
                         "NVIDIA 显卡自动用硬件编码（速度快、画质近无损），无独显回退软件编码")
        parts = [
            "视频：{}".format(os.path.basename(self.video_path)),
            "保留镜头：{} 个，共 {}".format(
                len(keep), fmt_time(sum(s.duration for s in keep))),
            "输出目录：{}".format(out_dir),
            "命名：{}".format(
                "、".join(names[:3]) + (" …（共 {} 个）".format(len(names)) if len(names) > 3 else "")),
            "格式：{}（仅换容器，画质零损失）｜ 导出方式：{}".format(
                ext, "合并为一个视频" if merge else "每个镜头独立文件"),
            mode_note,
        ]
        if exists:
            parts.append("\n⚠ 目标目录已存在 {} 个同名文件，将被覆盖：\n{}".format(
                len(exists), "、".join(exists[:5])))
        box = QMessageBox(self)
        box.setWindowTitle("确认导出")
        box.setText("\n".join(parts))
        btn_yes = box.addButton("确认导出", QMessageBox.AcceptRole)
        box.addButton("返回修改", QMessageBox.RejectRole)
        box.setDefaultButton(btn_yes)
        box.exec()
        return box.clickedButton() == btn_yes

    def _on_exported(self, files):
        self._close_export_dlg()
        self._set_busy(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.lbl_status.setText("导出完成：共 {} 个文件".format(len(files)))
        out_dir = os.path.dirname(files[0]) if files else ""
        box = QMessageBox(self)
        box.setWindowTitle("导出完成")
        box.setText("导出完成，共 {} 个文件。".format(len(files)))
        btn_open = box.addButton("打开输出目录", QMessageBox.AcceptRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        box.setDefaultButton(btn_open)
        box.exec()
        if box.clickedButton() == btn_open:
            self._open_folder(out_dir)

    # ================= 会话恢复 / 通用 =================
    def _save_session_now(self):
        active = ""
        if 0 <= self._active_idx < len(self.video_states):
            active = self.video_states[self._active_idx].path
        save_session(self.video_states, active)

    def _restore_prev_session(self):
        res = load_session()
        if res is None or not res[0]:
            return
        states, active = res
        analyzed_n = sum(1 for s in states if s.analyzed)
        txt = ("检测到上次未完成的会话（{} 个视频，其中 {} 个已分析）。\n"
               "分析结果和手动调整都还在，是否恢复？"
               .format(len(states), analyzed_n))
        box = QMessageBox(self)
        box.setWindowTitle("恢复上次会话")
        box.setText(txt)
        btn_yes = box.addButton("恢复", QMessageBox.AcceptRole)
        box.addButton("不恢复", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() != btn_yes:
            return
        self.video_states = states
        # 恢复的视频必须填进左侧列表，否则无法点击切换（和导入同 bug）
        self._refresh_file_items()
        for i, st in enumerate(states):
            self._gen_cover(st, i)
        idx = 0
        for i, st in enumerate(states):
            if st.path == active:
                idx = i
                break
        self._switch_to(idx)
        st = self._active()
        if st is not None and st.analyzed:
            self._gen_thumbnails()
        self.statusBar().showMessage("已恢复上次会话（{} 个视频）".format(len(states)))

    def _on_failed(self, msg):
        self._close_export_dlg()
        self._set_busy(False)
        self.progress.setRange(0, 100)
        self.lbl_status.setText(msg)
        QMessageBox.critical(self, "出错了", msg)

    def _set_busy(self, busy):
        self.btn_analyze.setEnabled(not busy)
        self.btn_export.setEnabled(not busy)

    def _update_stats(self):
        if not self.segments:
            self.lbl_stats.setText("")
            return
        keep, deleted, ratio = summarize(self.segments, self.duration)
        self.lbl_stats.setText(" 保留 {} / 删除 {} / 压缩 {:.0f}%".format(
            fmt_time(keep), fmt_time(deleted), ratio))

    def _open_folder(self, path):
        try:
            if os.name == "nt":
                os.startfile(path)  # noqa
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    # ================= 窗口拖动 / 最大化 / 边缘 resize =================
    def _title_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def _title_mouse_move(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            if self.isMaximized():
                self.showNormal()
                # 恢复正常后重新计算位置
                self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def _title_mouse_release(self, event):
        self._drag_pos = None
        event.accept()

    def _title_mouse_dblclick(self, event):
        self._toggle_max_restore()
        event.accept()

    def _toggle_max_restore(self):
        if self.isMaximized():
            self.showNormal()
            self.btn_max.setText("□")
        else:
            self.showMaximized()
            self.btn_max.setText("❐")

    def _restore_window_state(self):
        geo = self._settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        is_max = self._settings.value("maximized", "false")
        if is_max == "true":
            self.showMaximized()
            self.btn_max.setText("❐")

    def showEvent(self, event):
        super().showEvent(event)
        # 安装事件过滤器到窗口本身（边缘 resize）
        self.setMouseTracking(True)
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self:
            etype = event.type()
            if etype == event.Type.MouseMove:
                self._handle_mouse_move(event)
            elif etype == event.Type.MouseButtonPress:
                self._handle_mouse_press(event)
            elif etype == event.Type.MouseButtonRelease:
                self._handle_mouse_release(event)
            elif etype == event.Type.Leave:
                self.unsetCursor()
        return super().eventFilter(obj, event)

    # ---------- 素材库抽屉（Header 素材库按钮切换，布局驱动） ----------
    def _toggle_material(self, checked):
        """Header「素材库」按钮：展开 / 收起左侧素材库抽屉（纯布局切换）。"""
        self.material_panel.setVisible(checked)

    def _esc_close_material(self):
        """Esc：收起素材库抽屉（若在展开中）。"""
        if self.material_panel.isVisible():
            self.btn_library.setChecked(False)   # 触发 _toggle_material 收起

    # ---------- Header 设置菜单 / 开发者信息 ----------
    def _show_settings_menu(self):
        menu = QMenu(self)
        act_reset = menu.addAction("恢复默认窗口大小")
        menu.addSeparator()
        act_about = menu.addAction("开发者信息")
        ver = menu.addAction("版本  v{}".format(__version__))
        ver.setEnabled(False)   # 只读展示
        chosen = menu.exec(self.btn_settings.mapToGlobal(
            QPoint(0, self.btn_settings.height())))
        if chosen == act_reset:
            self.showNormal()
            self.resize(1280, 800)
        elif chosen == act_about:
            self._show_about()

    def _show_about(self):
        QMessageBox.about(
            self, "开发者信息",
            "<h3>AutoCut <small>v{}</small></h3>"
            "<p>自动视频切片工具 —— 基于画面运动检测（帧差法）识别镜头边界，"
            "自动删除废镜头、保留有效片段，支持无损快速导出。</p>"
            "<p style='color:#9AA3AE;font-size:12px;'>"
            "技术栈：Python · PySide6 · OpenCV · FFmpeg</p>".format(
                __version__))

    def _resize_edge_at(self, pos):
        # pos: 相对于窗口的局部坐标
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        b = self._border
        on_w = x <= b
        on_e = x >= w - b
        on_n = y <= b
        on_s = y >= h - b
        if on_n and on_w: return 'nw'
        if on_n and on_e: return 'ne'
        if on_s and on_w: return 'sw'
        if on_s and on_e: return 'se'
        if on_n: return 'n'
        if on_s: return 's'
        if on_w: return 'w'
        if on_e: return 'e'
        return None

    def _cursor_for_edge(self, edge):
        cursors = {
            'n': Qt.CursorShape.SizeVerCursor,
            's': Qt.CursorShape.SizeVerCursor,
            'e': Qt.CursorShape.SizeHorCursor,
            'w': Qt.CursorShape.SizeHorCursor,
            'nw': Qt.CursorShape.SizeFDiagCursor,
            'se': Qt.CursorShape.SizeFDiagCursor,
            'ne': Qt.CursorShape.SizeBDiagCursor,
            'sw': Qt.CursorShape.SizeBDiagCursor,
        }
        return cursors.get(edge, Qt.CursorShape.ArrowCursor)

    def _handle_mouse_move(self, event):
        if self._resizing:
            return
        if self.isMaximized():
            self.unsetCursor()
            return
        # 检查是否在 Header 上（Header 区域不触发 resize）
        if self.title_bar.geometry().contains(event.pos()):
            self.unsetCursor()
            return
        edge = self._resize_edge_at(event.pos())
        if edge:
            self.setCursor(self._cursor_for_edge(edge))
        else:
            self.unsetCursor()

    def _handle_mouse_press(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self.isMaximized():
            return
        # 检查是否在 Header 上
        if self.title_bar.geometry().contains(event.pos()):
            return
        edge = self._resize_edge_at(event.pos())
        if edge:
            self._resizing = True
            self._resize_edge = edge
            self._resize_start = (event.globalPos(), self.geometry())
            event.accept()

    def _handle_mouse_release(self, event):
        if self._resizing:
            self._resizing = False
            self._resize_edge = None
            self._resize_start = None
            self.unsetCursor()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._resizing and self._resize_edge and self._resize_start:
            global_pos, orig_geo = self._resize_start
            dx = event.globalX() - global_pos.x()
            dy = event.globalY() - global_pos.y()
            new_geo = QRect(orig_geo)
            if 'e' in self._resize_edge:
                new_geo.setRight(new_geo.right() + dx)
            if 'w' in self._resize_edge:
                new_geo.setLeft(new_geo.left() + dx)
            if 's' in self._resize_edge:
                new_geo.setBottom(new_geo.bottom() + dy)
            if 'n' in self._resize_edge:
                new_geo.setTop(new_geo.top() + dy)
            self.setGeometry(new_geo)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def closeEvent(self, e):
        self._save_session_now()
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("maximized", "true" if self.isMaximized() else "false")
        # 通知分析/导出线程取消（会 kill 掉 ffmpeg），再限时等待，防止进程残留
        for worker in (self._analyzer, self._exporter):
            try:
                if worker is not None and worker.isRunning():
                    worker.cancel.set()
                    if not worker.wait(2000):
                        worker.terminate()
                        worker.wait(1000)
            except Exception:
                pass
        super().closeEvent(e)


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from ui.theme import DARK_QSS

    app = QApplication(sys.argv)
    app.setApplicationName("自动视频切片工具")
    app.setStyleSheet(DARK_QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
