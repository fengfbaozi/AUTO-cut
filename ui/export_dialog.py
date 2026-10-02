# -*- coding: utf-8 -*-
"""导出设置对话框（模仿 LosslessCut 的导出面板）：
   输出目录 + 项目名 + 序号位数 + 起始编号 + 格式 + 导出方式（独立/合并）。

   命名规范：项目名_编号.扩展名（如 IMG_9765_1.mp4）
   编号从「起始编号」开始往后排（默认 1：…_1、…_2、…_3）
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QSpinBox, QVBoxLayout)


class ExportDialog(QDialog):
    def __init__(self, parent=None, default_prefix="视频", default_dir="",
                 saved=None):
        super().__init__(parent)
        self.setWindowTitle("导出设置")
        self.setMinimumWidth(500)

        lay = QVBoxLayout(self)

        # 输出目录
        r1 = QHBoxLayout()
        self.ed_dir = QLineEdit(default_dir)
        btn_dir = QPushButton("浏览…")
        btn_dir.clicked.connect(self._pick_dir)
        r1.addWidget(QLabel("输出目录："))
        r1.addWidget(self.ed_dir, stretch=1)
        r1.addWidget(btn_dir)
        lay.addLayout(r1)

        # 项目名 + 序号位数 + 起始编号
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("项目名："))
        self.ed_prefix = QLineEdit(default_prefix)
        r2.addWidget(self.ed_prefix, stretch=1)
        r2.addWidget(QLabel("序号位数："))
        self.cmb_digits = QComboBox()
        self.cmb_digits.addItem("1 位（1）", 1)
        self.cmb_digits.addItem("2 位（01）", 2)
        self.cmb_digits.addItem("3 位（001）", 3)
        self.cmb_digits.setCurrentIndex(0)
        r2.addWidget(self.cmb_digits)
        r2.addWidget(QLabel("起始编号："))
        self.spn_start = QSpinBox()
        self.spn_start.setRange(0, 9999)
        self.spn_start.setValue(1)
        self.spn_start.setToolTip(
            "导出文件从几号开始排\n如从 5 开始：…_5、…_6、…_7")
        r2.addWidget(self.spn_start)
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("格式："))
        self.cmb_ext = QComboBox()
        self.cmb_ext.addItems(["mp4", "mov", "mkv"])
        self.cmb_ext.setCurrentIndex(0)
        self.cmb_ext.setToolTip("只是换容器包装，原画质零损失")
        r3.addWidget(self.cmb_ext)
        r3.addStretch()
        lay.addLayout(r3)

        # 示例
        self.lbl_example = QLabel("")
        self.lbl_example.setObjectName("dim")
        lay.addWidget(self.lbl_example)

        # 导出方式（LosslessCut 的 Export / Export to individual files）
        # 注意：两组单选钮必须各建一个 QButtonGroup，
        # 否则同父的 4 个单选钮会互斥成一组（点切割方式会挤掉导出方式的选中）
        self._grp_method = QButtonGroup(self)
        self._grp_mode = QButtonGroup(self)
        r4 = QHBoxLayout()
        r4.addWidget(QLabel("导出方式："))
        self.rb_files = QRadioButton("每个保留镜头独立文件（推荐）")
        self.rb_files.setChecked(True)
        self.rb_merge = QRadioButton("合并为一个视频")
        self._grp_method.addButton(self.rb_files)
        self._grp_method.addButton(self.rb_merge)
        r4.addWidget(self.rb_files)
        r4.addWidget(self.rb_merge)
        lay.addLayout(r4)

        # 切割方式
        r5 = QHBoxLayout()
        r5.addWidget(QLabel("切割方式："))
        self.rb_fast = QRadioButton("极速无损")
        self.rb_fast.setToolTip(
            "原画质直接裁切（-c copy），画质零损失，速度最快\n"
            "⚠ 注意：切点会吸附到最近的关键帧，片段头尾可能有约 0~2 秒偏差")
        self.rb_acc = QRadioButton("精确（推荐）")
        self.rb_acc.setChecked(True)
        self.rb_acc.setToolTip(
            "切点精准到帧，导出的内容和你选的镜头完全一致\n"
            "NVIDIA 显卡自动用硬件编码：速度接近无损模式，画质近无损\n"
            "无独显时自动回退软件编码（稍慢）")
        self._grp_mode.addButton(self.rb_fast)
        self._grp_mode.addButton(self.rb_acc)
        r5.addWidget(self.rb_fast)
        r5.addWidget(self.rb_acc)
        lay.addLayout(r5)

        # 按钮
        r6 = QHBoxLayout()
        btn_ok = QPushButton("开始导出")
        btn_ok.setObjectName("primary")
        btn_ok.setFixedHeight(36)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.setFixedHeight(36)
        btn_cancel.clicked.connect(self.reject)
        r6.addStretch()
        r6.addWidget(btn_cancel)
        r6.addWidget(btn_ok)
        lay.addLayout(r6)

        self.ed_prefix.textChanged.connect(self._update_example)
        self.cmb_digits.currentIndexChanged.connect(self._update_example)
        self.spn_start.valueChanged.connect(self._update_example)
        self.cmb_ext.currentIndexChanged.connect(self._update_example)
        self.rb_merge.toggled.connect(self._update_example)
        # 恢复上次导出的选择（省得每次都重选一遍）
        if saved:
            self._apply_saved(saved, default_prefix, default_dir)
        self._update_example()

    def _apply_saved(self, saved, default_prefix, default_dir):
        if saved.get("dir"):
            self.ed_dir.setText(saved["dir"])
        elif default_dir:
            self.ed_dir.setText(default_dir)
        if saved.get("prefix"):
            self.ed_prefix.setText(saved["prefix"])
        else:
            self.ed_prefix.setText(default_prefix)
        idx = self.cmb_digits.findData(saved.get("digits", 1))
        if idx >= 0:
            self.cmb_digits.setCurrentIndex(idx)
        self.spn_start.setValue(saved.get("seq_start", 1))
        idx = self.cmb_ext.findText(saved.get("ext", "mp4"))
        if idx >= 0:
            self.cmb_ext.setCurrentIndex(idx)
        if saved.get("merge"):
            self.rb_merge.setChecked(True)
        else:
            self.rb_files.setChecked(True)
        if saved.get("mode") == "fast":
            self.rb_fast.setChecked(True)
        else:
            self.rb_acc.setChecked(True)

    def _update_example(self):
        digits = self.cmb_digits.currentData()
        start = self.spn_start.value()
        prefix = self.ed_prefix.text() or "项目名"
        ext = self.cmb_ext.currentText()
        if self.rb_merge.isChecked():
            self.lbl_example.setText(
                "示例：{}_成片.{}（合并为一个视频）".format(prefix, ext))
        else:
            self.lbl_example.setText(
                "示例：{}_{}.{}、{}_{}.{} …（在右侧列表给镜头起了名的，"
                "名字自动跟在编号后：{}_{}_下油.{}）".format(
                    prefix, "{:0{}}".format(start, digits), ext,
                    prefix, "{:0{}}".format(start + 1, digits), ext,
                    prefix, "{:0{}}".format(start, digits), ext))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", self.ed_dir.text())
        if d:
            self.ed_dir.setText(d)

    def values(self):
        return {
            "out_dir": self.ed_dir.text().strip() or os.path.expanduser("~"),
            "prefix": self.ed_prefix.text().strip() or "视频",
            "digits": self.cmb_digits.currentData(),
            "seq_start": self.spn_start.value(),
            "ext": self.cmb_ext.currentText(),
            "merge": self.rb_merge.isChecked(),
            "mode": "fast" if self.rb_fast.isChecked() else "accurate",
        }
