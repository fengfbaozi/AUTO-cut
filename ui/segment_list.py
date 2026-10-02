# -*- coding: utf-8 -*-
"""右侧片段目录（模仿 LosslessCut 的片段列表）：
   每一行 = 「保留」勾选框 + 缩略图 + 编号/起止时间/时长 + 镜头名输入框（可选）。

   交互（与 LosslessCut 一致）：
     - 勾选/取消勾选「保留」：标记该镜头保留或删除
     - 单击行：选中该镜头（联动时间轴）
     - 双击行：跳转并播放该镜头
     - 镜头名输入框：给镜头起个名（可选），导出时自动跟在编号后面
       （如 项目名_1_下油.mp4）；不填就只有编号
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QWidget)

from ui.timeline import display_number, fmt_time


class _SegmentRow(QWidget):
    """单个片段的展示行：勾选框 + 缩略图 + 编号/时间 + 镜头名。"""

    def __init__(self, idx, seg, num, is_keep, parent=None):
        super().__init__(parent)
        self.idx = idx
        self.seg = seg

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 3, 4, 3)
        lay.setSpacing(6)

        # 保留/删除 勾选框（LosslessCut 式 include 标记）
        self.chk = QCheckBox()
        self.chk.setChecked(seg.keep)
        self.chk.setFixedSize(18, 18)
        self.chk.setToolTip("保留/删除")
        lay.addWidget(self.chk)

        # 缩略图（异步生成；样式由全局主题 QLabel#thumb 统一管理）
        self.thumb = QLabel("…")
        self.thumb.setObjectName("thumb")
        self.thumb.setFixedSize(64, 36)
        self.thumb.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.thumb)

        # 编号 + 起止 + 时长
        self.txt = QLabel()
        self.txt.setTextFormat(Qt.PlainText)
        self.txt.setStyleSheet("font-size: 11px; line-height: 1.3;")
        self.txt.setMinimumWidth(0)
        lay.addWidget(self.txt, stretch=1)

        # 镜头名（可选）：导出时跟在编号后面，如 项目名_1_下油.mp4
        self.ed_label = QLineEdit()
        self.ed_label.setPlaceholderText("镜头名")
        self.ed_label.setMinimumWidth(72)
        self.ed_label.setFixedHeight(24)
        self.ed_label.setStyleSheet("font-size: 11px;")
        self.ed_label.setToolTip(
            "给这个镜头起个名（可以不填）\n"
            "导出时自动跟在编号后面：项目名_1_下油.mp4")
        self.ed_label.setText(seg.label)
        # 用户输入直接写回片段对象（导出/保存时都从那里读）
        self.ed_label.textEdited.connect(self._on_label_edited)
        lay.addWidget(self.ed_label)

        self.update_text(seg, num, is_keep)

    def _on_label_edited(self, text):
        self.seg.label = str(text).strip()

    def update_text(self, seg, num, is_keep):
        # 独立编号：保留段 = 镜头N，删除段 = 已删除N（互不混编）
        if is_keep:
            tag = "镜头 {:02d}".format(num)
            self.txt.setObjectName("")   # 默认亮色文字
        else:
            tag = "已删除 {:02d}".format(num)
            self.txt.setObjectName("seg_del")  # 删除的弱化为灰色
        # 切换 objectName 后需重新应用样式
        self.txt.style().unpolish(self.txt)
        self.txt.style().polish(self.txt)
        self.txt.setText(
            "{}\n{} ~ {} · {}s".format(
                tag, fmt_time(seg.start), fmt_time(seg.end),
                "{:.1f}".format(seg.duration)))
        # 只有保留镜头会导出，删除段的输入框藏起来省地方（内容仍保留）
        self.ed_label.setVisible(is_keep)

    def set_thumb_pixmap(self, png_path):
        pm = QPixmap(png_path)
        if not pm.isNull():
            self.thumb.setPixmap(pm.scaled(
                self.thumb.size(), Qt.KeepAspectRatio,
                Qt.SmoothTransformation))


class SegmentList(QListWidget):
    segClicked = Signal(int)          # 单击选中
    segDoubleClicked = Signal(int)    # 双击播放
    keepToggled = Signal(int, bool)   # 勾选框切换保留/删除
    labelEdited = Signal(int)         # 镜头名输入完成（回车/失焦）——提醒外部保存

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self._rows = {}
        self.setSelectionMode(QListWidget.SingleSelection)
        self.itemClicked.connect(self._on_clicked)
        self.itemDoubleClicked.connect(self._on_double)
        # 优化滚动灵敏度：每次滚动一行，更跟手
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(20)

    # ---------- 数据 ----------
    def set_segments(self, segments):
        self.segments = list(segments)
        self._rows = {}
        self.clear()
        for i, seg in enumerate(self.segments):
            num, is_keep = display_number(self.segments, i)
            row = _SegmentRow(i, seg, num, is_keep)
            row.chk.toggled.connect(
                lambda checked, idx=i: self.keepToggled.emit(idx, checked))
            row.ed_label.editingFinished.connect(
                lambda idx=i: self.labelEdited.emit(idx))
            item = QListWidgetItem()
            item.setData(Qt.UserRole, i)
            item.setSizeHint(row.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, row)
            self._rows[i] = row

    def refresh_all(self):
        """保留/删除状态或切点变化后，重算所有行的编号与显示（不重建列表）。"""
        for i, seg in enumerate(self.segments):
            if i in self._rows:
                row = self._rows[i]
                row.chk.blockSignals(True)
                row.chk.setChecked(seg.keep)
                row.chk.blockSignals(False)
                num, is_keep = display_number(self.segments, i)
                row.update_text(seg, num, is_keep)

    def select_index(self, idx):
        if 0 <= idx < self.count():
            self.setCurrentRow(idx)

    def set_thumbnail(self, idx, png_path):
        if idx in self._rows:
            self._rows[idx].set_thumb_pixmap(png_path)

    # ---------- 交互 ----------
    def _on_clicked(self, item):
        self.segClicked.emit(int(item.data(Qt.UserRole)))

    def _on_double(self, item):
        self.segDoubleClicked.emit(int(item.data(Qt.UserRole)))
