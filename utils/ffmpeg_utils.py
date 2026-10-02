# -*- coding: utf-8 -*-
"""FFmpeg / ffprobe 路径查找与基础封装（Windows 下不弹黑窗口）"""
import os
import json
import shutil
import subprocess
import sys

# Windows 下隐藏子进程的控制台窗口
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _find(name):
    """依次从 PATH / 常见安装目录 / 本目录查找可执行文件"""
    p = shutil.which(name) or shutil.which(name + ".exe")
    if p:
        return p
    candidates = [
        # 打包成 exe 后：exe 同目录（把 ffmpeg.exe 放旁边就能用）
        os.path.dirname(sys.executable),
        r"C:\Program Files\FFmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ffmpeg\bin",
        os.path.dirname(os.path.abspath(__file__)),
    ]
    for d in candidates:
        cand = os.path.join(d, name + ".exe")
        if os.path.exists(cand):
            return cand
    return None


FFMPEG = _find("ffmpeg")
FFPROBE = _find("ffprobe")


def run(cmd, **kw):
    """执行命令，捕获输出，隐藏控制台窗口"""
    kw.setdefault("creationflags", CREATE_NO_WINDOW)
    kw.setdefault("capture_output", True)
    return subprocess.run(cmd, **kw)


def get_duration(path):
    """返回视频时长（秒）"""
    if not FFPROBE:
        return 0.0
    try:
        p = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", path])
        return float(p.stdout.decode("utf-8", "replace").strip())
    except Exception:
        return 0.0


def probe_stream(path):
    """返回 (宽度, 高度, 帧率)"""
    if not FFPROBE:
        return 0, 0, 0.0
    try:
        p = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate",
                 "-of", "json", path])
        st = json.loads(p.stdout.decode("utf-8", "replace"))["streams"][0]
        w, h = int(st["width"]), int(st["height"])
        fr = st.get("r_frame_rate", "30/1")
        try:
            num, den = fr.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 30.0
        except Exception:
            fps = 30.0
        return w, h, fps
    except Exception:
        return 0, 0, 0.0


def ffmpeg_available():
    return bool(FFMPEG) and bool(FFPROBE)
