# -*- coding: utf-8 -*-
"""验证 PySide6 QMediaPlayer 能否播放 4K 视频（自动播放 3 秒后退出）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtCore import QTimer, QUrl

app = QApplication(sys.argv)
player = QMediaPlayer()
audio = QAudioOutput()
player.setAudioOutput(audio)
video = QVideoWidget()
video.resize(640, 360)
video.show()

v = sys.argv[1] if len(sys.argv) > 1 else ""
if not v or not os.path.exists(v):
    print("用法: python test_player.py <视频路径>  # 验证本机能否正常播放该视频")
    sys.exit(1)
player.setVideoOutput(video)
player.setSource(QUrl.fromLocalFile(v))

result = {"ok": False, "msg": ""}


def check():
    state = player.playbackState()
    err = player.error()
    dur = player.duration()
    pos = player.position()
    print("state={} error={} duration={}ms position={}ms".format(state, err, dur, pos))
    if err != QMediaPlayer.Error.NoError:
        result["msg"] = "播放错误: {}".format(err)
        app.quit()
        return
    if dur > 0 and pos > 500:
        result["ok"] = True
        result["msg"] = "播放成功: 时长 {}ms, 已播到 {}ms".format(dur, pos)
        app.quit()


player.play()
QTimer.singleShot(1500, check)
QTimer.singleShot(6000, app.quit)
app.exec()
print("RESULT:", result["ok"], result["msg"])
