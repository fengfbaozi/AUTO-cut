# -*- coding: utf-8 -*-
"""导出进度对话框（全部用用户看得懂的话，不出现技术术语）：

   「正在导出：已完成 2 / 5 个镜头」 + 大进度条（条内显示百分比）+ 文件名 + 取消按钮。
   窗口挡住主界面防误操作，但不卡后台导出。
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout)


class ExportProgressDialog(QDialog):
    cancelled = Signal()   # 用户点了「取消导出」

    def __init__(self, mode="accurate", parent=None):
        super().__init__(parent)
        self.setWindowTitle("正在导出")
        self.setWindowModality(Qt.WindowModal)   # 挡住主窗口操作，不卡导出
        self.setMinimumWidth(480)

        self.lbl_stage = QLabel("正在准备导出…")

        self.lbl_file = QLabel("")
        self.lbl_file.setObjectName("dim")

        self.bar = QProgressBar()
        self.bar.setFixedHeight(26)
        self.bar.setFormat("%p%")          # 百分比直接显示在进度条里
        self.bar.setTextVisible(True)

        # 用大白话说明当前方式，让用户放心画质
        if mode == "fast":
            note = "极速无损导出：原画质直接裁切，速度最快"
        else:
            note = "精确导出：画面清晰度几乎无损，镜头头尾和你选的完全一致"
        self.lbl_note = QLabel(note)
        self.lbl_note.setObjectName("dim")
        self.lbl_note.setWordWrap(True)

        self.btn_cancel = QPushButton("取消导出")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setFixedHeight(32)
        self.btn_cancel.clicked.connect(self._on_cancel)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(12)
        lay.addWidget(self.lbl_stage)
        lay.addWidget(self.lbl_file)
        lay.addWidget(self.bar)
        lay.addWidget(self.lbl_note)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.btn_cancel)
        lay.addLayout(row)

    def set_progress(self, p, cur, total, fname=""):
        """p=0~1 进度；cur/total=已完成/总段数；fname=正在写的文件名"""
        pct = int(max(0.0, min(1.0, p)) * 100)
        self.bar.setValue(pct)
        if total:
            self.lbl_stage.setText(
                "正在导出：已完成 {} / {} 个镜头…（{}%）".format(cur, total, pct))
        if fname:
            self.lbl_file.setText(fname)

    def _on_cancel(self):
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText("正在取消…")
        self.lbl_stage.setText("正在取消导出…")
        self.cancelled.emit()
