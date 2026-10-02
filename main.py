# -*- coding: utf-8 -*-
"""自动视频切片工具 — 入口（PySide6）

用法：
    python main.py                 （或双击 启动工具.bat）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.theme import DARK_QSS


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("自动视频切片工具")
    app.setStyleSheet(DARK_QSS)
    win = MainWindow()
    # 默认最大化启动（无边框窗口的现代桌面软件体验）
    if win._settings.value("maximized", "true") == "true":
        win.showMaximized()
        win.btn_max.setText("❐")
    else:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
