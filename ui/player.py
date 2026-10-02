# -*- coding: utf-8 -*-
"""视频播放器控件：QMediaPlayer + QVideoWidget + 两行式控制区。

第一行：大号图标按钮（上一帧/播放/下一帧/设起点/设终点/浏览镜头）—— 模仿 LosslessCut
第二行：时间标签 + 进度滑块 + 音量

支持：播放/暂停、前后跳帧、进度拖动、音量。
浏览镜头模式：由 MainWindow 处理跳转逻辑，本控件只负责开关状态。
暴露信号：positionChanged(秒)、inPointPressed、outPointPressed、browseModeChanged(bool)。
"""
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from utils.ffmpeg_utils import probe_stream


def fmt_ms(ms):
    ms = max(0, int(ms))
    s = ms // 1000
    return "{}:{:02d}".format(s // 60, s % 60)


class PlayerWidget(QWidget):
    positionChanged = Signal(float)      # 秒
    userSeeked = Signal(float)           # 用户拖动进度条释放（主动跳转，非自动播放回报）
    inPointPressed = Signal()
    outPointPressed = Signal()
    browseModeChanged = Signal(bool)      # 浏览镜头开关
    lockModeChanged = Signal(bool)        # 锁定开关（防止误触已删除片段）

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fps = 30.0
        self._seeking = False
        self.browse_enabled = False

        self.video = QVideoWidget(self)
        # 体感优化：双击画面 = 播放/暂停（几乎所有播放器的标配）
        self.video.mouseDoubleClickEvent = lambda _ev: self.toggle_play()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setVideoOutput(self.video)
        self.player.setAudioOutput(self.audio)

        # ---- 第一行：控制按钮（现代图标风格，居中） ----
        def ctl(icon, tip, size=36):
            b = QPushButton(icon)
            b.setObjectName("icon")
            b.setFixedSize(size, size)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            return b

        self.btn_prev = ctl("⏮", "上一帧 [←]")
        self.btn_prev.clicked.connect(lambda: self.step_frame(-1))
        self.btn_play = ctl("▶", "播放/暂停 [空格]", 40)
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_next = ctl("⏭", "下一帧 [→]")
        self.btn_next.clicked.connect(lambda: self.step_frame(1))
        self.btn_in = ctl("◀", "设为起点 [I]")
        self.btn_in.clicked.connect(self.inPointPressed.emit)
        self.btn_out = ctl("▶", "设为终点 [O]")
        self.btn_out.clicked.connect(self.outPointPressed.emit)

        # 锁定：防止误触已删除的废镜头
        self.btn_lock = QPushButton("锁定")
        self.btn_lock.setObjectName("icon")
        self.btn_lock.setCheckable(True)
        self.btn_lock.setCursor(Qt.PointingHandCursor)
        self.btn_lock.setFixedHeight(32)
        self.btn_lock.setToolTip(
            "锁定：开启后已删除的废镜头不可点击/拖动，防止误触\n"
            "（想点镜头号却点到废镜头时，开这个就好）")
        self.btn_lock.toggled.connect(self.lockModeChanged.emit)

        # 浏览镜头：跳过已删除的废镜头，只连续播放保留镜头
        self.btn_browse = QPushButton("浏览镜头")
        self.btn_browse.setObjectName("icon")
        self.btn_browse.setCheckable(True)
        self.btn_browse.setCursor(Qt.PointingHandCursor)
        self.btn_browse.setFixedHeight(32)
        self.btn_browse.setToolTip(
            "浏览镜头：播放时自动跳过已删除的废镜头，只连续播放保留镜头\n"
            "用来确认每个镜头是否保留完整（预览成片效果）")
        self.btn_browse.toggled.connect(self._on_browse_toggled)

        # 倍速播放：点击弹出倍速菜单
        self.btn_speed = QPushButton("1x")
        self.btn_speed.setObjectName("icon")
        self.btn_speed.setCursor(Qt.PointingHandCursor)
        self.btn_speed.setFixedHeight(32)
        self.btn_speed.setToolTip("播放速度：点击选择倍速（快速预览用）")
        self._speed_menu = QMenu(self)
        for rate in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
            label = "{}x".format(int(rate)) if rate == int(rate) else "{}x".format(rate)
            act = self._speed_menu.addAction(label)
            act.triggered.connect(lambda checked=False, r=rate: self.set_speed(r))
        self.btn_speed.setMenu(self._speed_menu)

        row_btns = QHBoxLayout()
        row_btns.setContentsMargins(12, 6, 12, 4)
        row_btns.setSpacing(4)
        row_btns.addStretch(1)
        row_btns.addWidget(self.btn_prev)
        row_btns.addWidget(self.btn_play)
        row_btns.addWidget(self.btn_next)
        row_btns.addSpacing(12)
        row_btns.addWidget(self.btn_in)
        row_btns.addWidget(self.btn_out)
        row_btns.addSpacing(12)
        row_btns.addWidget(self.btn_speed)
        row_btns.addStretch(2)
        row_btns.addWidget(self.btn_lock)
        row_btns.addSpacing(4)
        row_btns.addWidget(self.btn_browse)

        # ---- 第二行：时间 + 进度滑块 + 音量 ----
        self.lbl_time = QLabel("0:00 / 0:00")
        self.lbl_time.setObjectName("dim")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)

        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(100)
        self.vol.setMaximumWidth(80)
        self.vol.valueChanged.connect(self.audio.setVolume)
        self.lbl_vol = QLabel("🔊")

        row_slider = QHBoxLayout()
        row_slider.setContentsMargins(12, 2, 12, 8)
        row_slider.setSpacing(8)
        row_slider.addWidget(self.lbl_time)
        row_slider.addWidget(self.slider, stretch=1)
        row_slider.addWidget(self.lbl_vol)
        row_slider.addWidget(self.vol)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.video, stretch=1)
        lay.addLayout(row_btns)
        lay.addLayout(row_slider)

        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)

    # ---------- 浏览镜头 ----------
    def _on_browse_toggled(self, checked):
        self.browse_enabled = checked
        self.browseModeChanged.emit(checked)
        if checked and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self.player.play()   # 打开浏览模式时直接开始播放

    def is_playing(self):
        return self.player.playbackState() == QMediaPlayer.PlayingState.PlayingState

    def is_paused(self):
        """暂停中（含刚加载未播放）。循环播放只在非暂停时跳回段首。"""
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PausedState

    def pause(self):
        """暂停播放（供时间轴刮擦预览调用：拖动播放头时先暂停，松手停在那一帧）。"""
        self.player.pause()

    def set_speed(self, rate):
        """设置播放倍速，并让按钮显示当前倍速。"""
        self.player.setPlaybackRate(rate)
        label = "{}x".format(int(rate)) if rate == int(rate) else "{}x".format(rate)
        self.btn_speed.setText(label)

    # ---------- 播放控制 ----------
    def load(self, path):
        self.fps = probe_stream(path)[2] or 30.0
        # Windows 路径必须用 QUrl.fromLocalFile 转成 file:///c:/... 形式；
        # 直接传 str 会被 QUrl(str) 解析成畸形 URL（c:%5CUsers...），
        # 播放器报 ResourceError 打不开文件（黑屏）
        self.player.setSource(QUrl.fromLocalFile(path))
        self._duration_ms = 0
        self.lbl_time.setText("0:00 / 0:00")

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("⏸" if playing else "▶")

    def step_frame(self, direction):
        self.player.pause()
        step = max(33, int(1000.0 / self.fps))
        self.player.setPosition(self.player.position() + direction * step)

    def seek(self, seconds):
        self.player.setPosition(int(seconds * 1000))

    def play_at(self, seconds):
        """跳转到指定秒并开始播放（双击片段=播放该片段）。"""
        self.player.setPosition(int(seconds * 1000))
        self.player.play()

    def _on_slider_pressed(self):
        self._seeking = True

    def _on_slider_moved(self, v):
        # 拖动中只刷新时间预览，不 seek（4K 视频高频 seek 必卡，松手才真正跳转）
        self.lbl_time.setText("{} / {}".format(fmt_ms(v), fmt_ms(self._duration_ms)))

    def _on_slider_released(self):
        self._seeking = False
        self.player.setPosition(self.slider.value())
        self.userSeeked.emit(self.slider.value() / 1000.0)

    def _on_pos(self, ms):
        if not self._seeking:
            self.slider.blockSignals(True)
            self.slider.setValue(ms)
            self.slider.blockSignals(False)
        dur = self._duration_ms or self.player.duration()
        self.lbl_time.setText("{} / {}".format(fmt_ms(ms), fmt_ms(dur)))
        self.positionChanged.emit(ms / 1000.0)

    def _on_dur(self, ms):
        self._duration_ms = max(1, ms)
        self.slider.setRange(0, self._duration_ms)
