# -*- coding: utf-8 -*-
"""全局设计系统 — 现代深色 AI 工具主题。

设计原则：
  - 深色层级：通过不同深浅的黑灰色建立空间层级，不用纯黑
  - 克制科技感：极弱蓝紫强调色，不用霓虹/发光
  - 玻璃质感：半透明面板 + 1px 半透明边框
  - 留白：大量呼吸空间，信息层级清晰
  - 统一：所有颜色/字体/间距集中管理，禁止硬编码

颜色层级：
  背景：#0B0D10 → #111418 → #15191E → #1A1F25（由深到浅，建立层级）
  文字：#F2F4F7（主）→ #9AA3AE（次）→ #626B76（弱化）
  强调：#5B8DEF（柔和蓝，用于主按钮/选中态/进度）
  成功：#4CAF7D（保留段/完成状态）
  危险：#E05D5D（删除/错误）
"""

# ============ 颜色 ============
BG_APP = "#0B0D10"           # 应用背景（最外层）
BG_PANEL = "#111418"         # 面板背景
BG_ELEVATED = "#15191E"      # 浮起面板（对话框、菜单）
BG_HOVER = "#1A1F25"         # 悬停态背景

BORDER = "rgba(255,255,255,0.06)"      # 默认边框
BORDER_LIGHT = "rgba(255,255,255,0.10)"  # 强调边框
BORDER_FOCUS = "rgba(91,141,239,0.5)"   # 聚焦边框

TEXT_PRIMARY = "#F2F4F7"     # 主文字
TEXT_SECONDARY = "#9AA3AE"   # 次级文字
TEXT_MUTED = "#626B76"       # 弱化文字

ACCENT = "#5B8DEF"           # 主强调色（按钮/选中/进度）
ACCENT_HOVER = "#6B9DF0"     # 强调色悬停
ACCENT_PRESSED = "#4A7DE0"   # 强调色按下

SUCCESS = "#4CAF7D"          # 成功/保留
SUCCESS_HOVER = "#5CBF8D"    # 成功悬停
DANGER = "#E05D5D"           # 危险/删除
DANGER_HOVER = "#E86D6D"     # 危险悬停

# 时间轴专用色
TIMELINE_GREEN = "#4CAF7D"       # 保留段
TIMELINE_GREEN_HOVER = "#5CBF8D" # 保留段悬停
TIMELINE_DEL = "#2A2D33"         # 删除段
TIMELINE_DEL_HOVER = "#3A3D43"   # 删除段悬停
TIMELINE_SELECT = "#FFD54F"      # 选中高亮
TIMELINE_PLAYHEAD = "#FFFFFF"    # 播放头
TIMELINE_MM_VIEW = "#5B8DEF"     # 迷你概览图视口框

# ============ 字体 ============
FONT_FAMILY = "Microsoft YaHei UI, Segoe UI, PingFang SC, sans-serif"
FONT_SIZE_TITLE = 24         # 页面标题
FONT_SIZE_SECTION = 16       # 区块标题
FONT_SIZE_BODY = 13          # 正文
FONT_SIZE_SMALL = 12         # 辅助文字
FONT_SIZE_TINY = 11          # 极小文字

# ============ 间距 ============
SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
}

# ============ 圆角 ============
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8

# ============ 阴影 ============
SHADOW_PANEL = "0 2px 8px rgba(0,0,0,0.3)"
SHADOW_DIALOG = "0 8px 32px rgba(0,0,0,0.4)"


# ============ 全局 QSS ============
DARK_QSS = """
/* ========== 基础 ========== */
QWidget {{
    background-color: {bg_app};
    color: {text_primary};
    font-family: {font_family};
    font-size: {font_body}px;
}}

/* ========== 按钮 ========== */
QPushButton {{
    background-color: {bg_elevated};
    border: 1px solid {border};
    border-radius: {radius_md}px;
    padding: {spacing_md}px {spacing_lg}px;
    color: {text_primary};
    font-size: {font_body}px;
}}
QPushButton:hover {{
    background-color: {bg_hover};
    border-color: {border_light};
}}
QPushButton:pressed {{
    background-color: {bg_panel};
}}
QPushButton:disabled {{
    color: {text_muted};
    background-color: {bg_panel};
    border-color: {border};
}}
QPushButton:checked {{
    background-color: {accent};
    border-color: {accent};
    color: #FFFFFF;
}}
QPushButton:checked:hover {{
    background-color: {accent_hover};
}}

/* 主按钮（CTA） */
QPushButton#primary {{
    background-color: {accent};
    border: none;
    color: #FFFFFF;
    font-weight: 500;
    padding: {spacing_md}px {spacing_xl}px;
}}
QPushButton#primary:hover {{
    background-color: {accent_hover};
}}
QPushButton#primary:pressed {{
    background-color: {accent_pressed};
}}
QPushButton#primary:disabled {{
    background-color: {text_muted};
    color: {bg_app};
}}

/* 危险按钮 */
QPushButton#danger {{
    background-color: {danger};
    border: none;
    color: #FFFFFF;
}}
QPushButton#danger:hover {{
    background-color: {danger_hover};
}}

/* 图标按钮（播放器控制） */
QPushButton#icon {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: {radius_md}px;
    padding: {spacing_sm}px;
    font-size: 16px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}}
QPushButton#icon:hover {{
    background-color: {bg_hover};
    border-color: {border_light};
}}
QPushButton#icon:checked {{
    background-color: {accent};
    color: #FFFFFF;
}}

/* ========== 列表 ========== */
QListWidget {{
    background-color: {bg_panel};
    border: 1px solid {border};
    border-radius: {radius_md}px;
    outline: none;
    padding: {spacing_xs}px;
}}
QListWidget::item {{
    padding: {spacing_sm}px {spacing_md}px;
    border-radius: {radius_sm}px;
    border: none;
}}
QListWidget::item:selected {{
    background-color: {accent};
    color: #FFFFFF;
}}
QListWidget::item:hover:!selected {{
    background-color: {bg_hover};
}}

/* ========== 输入控件 ========== */
QComboBox, QLineEdit, QSpinBox {{
    background-color: {bg_elevated};
    border: 1px solid {border};
    border-radius: {radius_md}px;
    padding: {spacing_sm}px {spacing_md}px;
    color: {text_primary};
    selection-background-color: {accent};
    selection-color: #FFFFFF;
    min-height: 20px;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
    border-color: {border_light};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
    border-color: {border_focus};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid {text_secondary};
    margin-right: {spacing_sm}px;
}}
QComboBox QAbstractItemView {{
    background-color: {bg_elevated};
    border: 1px solid {border_light};
    selection-background-color: {accent};
    selection-color: #FFFFFF;
    outline: none;
    padding: {spacing_xs}px;
}}

/* ========== 滑块 ========== */
QSlider::groove:horizontal {{
    height: 4px;
    background: {bg_panel};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {text_primary};
    border: none;
}}
QSlider::handle:horizontal:hover {{
    background: #FFFFFF;
}}
QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 2px;
}}
QSlider::groove:vertical {{
    width: 4px;
    background: {bg_panel};
    border-radius: 2px;
}}
QSlider::handle:vertical {{
    width: 14px;
    height: 14px;
    margin: 0 -5px;
    border-radius: 7px;
    background: {text_primary};
    border: none;
}}
QSlider::handle:vertical:hover {{
    background: #FFFFFF;
}}
QSlider::sub-page:vertical {{
    background: {accent};
    border-radius: 2px;
}}

/* ========== 勾选框 / 单选框 ========== */
QCheckBox, QRadioButton {{
    spacing: {spacing_sm}px;
    background: transparent;
    color: {text_primary};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
}}
QCheckBox::indicator {{
    border: 1px solid {border_light};
    border-radius: {radius_sm}px;
    background: {bg_elevated};
}}
QCheckBox::indicator:hover {{
    border-color: {accent};
}}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent};
    image: none;
}}
QRadioButton::indicator {{
    border: 1px solid {border_light};
    border-radius: 8px;
    background: {bg_elevated};
}}
QRadioButton::indicator:checked {{
    background: {accent};
    border: 3px solid {bg_elevated};
}}

/* ========== 进度条 ========== */
QProgressBar {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: {radius_md}px;
    text-align: center;
    color: {text_primary};
    font-size: {font_small}px;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: {radius_sm}px;
}}

/* ========== 滚动条 ========== */
QScrollBar:vertical {{
    background: {bg_app};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {bg_hover};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {text_muted};
}}
QScrollBar:horizontal {{
    background: {bg_app};
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {bg_hover};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {text_muted};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ========== 菜单 ========== */
QMenu {{
    background-color: {bg_elevated};
    border: 1px solid {border_light};
    border-radius: {radius_md}px;
    padding: {spacing_xs}px;
}}
QMenu::item {{
    padding: {spacing_sm}px {spacing_lg}px;
    border-radius: {radius_sm}px;
    color: {text_primary};
}}
QMenu::item:selected {{
    background-color: {accent};
    color: #FFFFFF;
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: {spacing_xs}px {spacing_sm}px;
}}

/* ========== 弹窗 / 标签 / 状态栏 ========== */
QMessageBox, QDialog {{
    background-color: {bg_app};
}}
QLabel {{
    background: transparent;
    color: {text_primary};
}}
QLabel#dim {{
    color: {text_secondary};
}}
QLabel#muted {{
    color: {text_muted};
}}
QLabel#title {{
    font-size: {font_title}px;
    font-weight: 600;
}}
QLabel#section {{
    font-size: {font_section}px;
    font-weight: 500;
}}
QLabel#seg_del {{
    color: {text_muted};
}}
QLabel#thumb {{
    background-color: {bg_panel};
    border: 1px solid {border};
    color: {text_muted};
    border-radius: {radius_sm}px;
}}
QStatusBar {{
    background-color: {bg_panel};
    color: {text_secondary};
    border-top: 1px solid {border};
    font-size: {font_small}px;
}}
QStatusBar::item {{
    border: none;
}}
QToolTip {{
    background-color: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border_light};
    border-radius: {radius_sm}px;
    padding: {spacing_xs}px {spacing_sm}px;
    font-size: {font_small}px;
}}

/* ========== 分割条 ========== */
QSplitter::handle {{
    background-color: {bg_panel};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}
QSplitter::handle:hover {{
    background-color: {accent};
}}

/* ========== 面板（玻璃质感） ========== */
QWidget#panel {{
    background-color: {bg_panel};
    border: 1px solid {border};
    border-radius: {radius_lg}px;
}}
QWidget#panel_elevated {{
    background-color: {bg_elevated};
    border: 1px solid {border_light};
    border-radius: {radius_lg}px;
}}

/* ========== 拖拽区域 ========== */
QLabel#drop_zone {{
    background-color: {bg_panel};
    border: 2px dashed {border_light};
    border-radius: {radius_lg}px;
    color: {text_muted};
    font-size: {font_body}px;
}}
QLabel#drop_zone:hover {{
    border-color: {accent};
    color: {text_secondary};
}}

/* ========== 无边框窗口 Header ========== */
QWidget#header {{
    background-color: {bg_app};
    border-bottom: 1px solid {border};
}}
QWidget#header QLabel {{
    background: transparent;
}}

/* 镜头跳转箭头按钮（时间轴上方） */
QPushButton#nav_arrow {{
    background-color: {bg_elevated};
    border: 1px solid {border};
    border-radius: {radius_sm}px;
    padding: 0px;
    color: {text_secondary};
    font-size: 12px;
    min-width: 30px;
    max-width: 30px;
    min-height: 26px;
    max-height: 26px;
}}
QPushButton#nav_arrow:hover {{
    background-color: {bg_hover};
    color: {text_primary};
    border-color: {border_light};
}}
QPushButton#nav_arrow:pressed {{
    background-color: {bg_panel};
}}

/* Header 功能按钮（素材库 / 设置 / 开发者信息） */
QPushButton#header_btn {{
    background: transparent;
    border: none;
    border-radius: {radius_sm}px;
    padding: 5px 10px;
    color: {text_secondary};
    font-size: 12px;
}}
QPushButton#header_btn:hover {{
    background-color: {bg_hover};
    color: {text_primary};
}}
QPushButton#header_btn:checked {{
    background-color: {bg_hover};
    color: {text_primary};
}}

/* 窗口控制按钮（最小化 / 最大化 / 关闭） */
QPushButton#win_btn {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
    min-width: 46px;
    max-width: 46px;
    min-height: 32px;
    max-height: 32px;
    color: {text_secondary};
    font-size: 13px;
}}
QPushButton#win_btn:hover {{
    background-color: {bg_hover};
    color: {text_primary};
}}
QPushButton#win_btn:pressed {{
    background-color: {bg_panel};
}}
QPushButton#win_close {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
    min-width: 46px;
    max-width: 46px;
    min-height: 32px;
    max-height: 32px;
    color: {text_secondary};
    font-size: 13px;
}}
QPushButton#win_close:hover {{
    background-color: #E81123;
    color: #FFFFFF;
}}
QPushButton#win_close:pressed {{
    background-color: #C50F1F;
    color: #FFFFFF;
}}
""".format(
    bg_app=BG_APP, bg_panel=BG_PANEL, bg_elevated=BG_ELEVATED, bg_hover=BG_HOVER,
    border=BORDER, border_light=BORDER_LIGHT, border_focus=BORDER_FOCUS,
    text_primary=TEXT_PRIMARY, text_secondary=TEXT_SECONDARY, text_muted=TEXT_MUTED,
    accent=ACCENT, accent_hover=ACCENT_HOVER, accent_pressed=ACCENT_PRESSED,
    danger=DANGER, danger_hover=DANGER_HOVER,
    success=SUCCESS, success_hover=SUCCESS_HOVER,
    font_family=FONT_FAMILY,
    font_body=FONT_SIZE_BODY, font_small=FONT_SIZE_SMALL,
    font_title=FONT_SIZE_TITLE, font_section=FONT_SIZE_SECTION,
    spacing_xs=SPACING["xs"], spacing_sm=SPACING["sm"],
    spacing_md=SPACING["md"], spacing_lg=SPACING["lg"], spacing_xl=SPACING["xl"],
    radius_sm=RADIUS_SM, radius_md=RADIUS_MD, radius_lg=RADIUS_LG,
)
