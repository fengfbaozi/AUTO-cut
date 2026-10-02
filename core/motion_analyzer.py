# -*- coding: utf-8 -*-
"""运动分析引擎：FFmpeg 分块并行抽关键帧 + NumPy 帧差，算出每秒运动分。

原理：画面前后两帧差异越大，说明动作越多。
很多视频全程有背景音乐 / 环境噪音（操作演示、活动录像、Vlog 等），
所以「有没有动作」只看画面，不看声音。

提速设计（对比 LosslessCut 只是读文件，我们是真正解码画面做分析）：
  - 只解码关键帧（-skip_frame nokey），跳过绝大部分 P/B 帧
  - 按 90 秒一块并行解码，充分利用多核
  实测：11 分钟 4K 视频从 ~71 秒降到 ~10 秒分析完。
"""
import math
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import cv2
import numpy as np

from utils.ffmpeg_utils import FFMPEG, CREATE_NO_WINDOW, probe_stream, get_duration

DIFF_THRESHOLD = 25  # 像素变化超过该值才算“有变化”
BLUR_KERNEL = (5, 5)
CHUNK_SEC = 45.0     # 每个并行块覆盖的视频秒数
MAX_WORKERS = 4      # 并行解码路数（硬解时 GPU 需留余量，4 路已够快）
DECODE_THREADS = 2   # 软解回退时单进程的解码线程数
# 硬件解码：指定 d3d11va（Windows 通用，实测比软解快 ~10 倍）。
# 不用 auto——多进程下 auto 可能选中会话冲突的解码器导致挂死。
# 某块硬解无输出时自动回退软解，保证任何机器可用。
HWACCEL_METHOD = "d3d11va"


def _build_cmd(video, start, end, w, h, fps, hwaccel):
    """拼装单块解码命令（-ss 放在 -i 前为快速定位）。"""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
    if hwaccel:
        cmd += ["-hwaccel", HWACCEL_METHOD]
    cmd += [
        "-skip_frame", "nokey",          # 只解码关键帧，大幅减少解码量
        "-threads", str(DECODE_THREADS),  # 限制单进程线程数，避免多进程抢占
        "-ss", "{:.3f}".format(start),
        "-t", "{:.3f}".format(max(0.1, end - start)),
        "-i", video,
        "-vf", "scale={}:{},fps={},format=gray".format(w, h, fps),
        "-an", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    return cmd


def _run_chunk(video, start, end, w, h, fps, hwaccel, cancel_event):
    """跑一次解码并计算运动分，返回每采样帧的运动分列表。"""
    proc = subprocess.Popen(_build_cmd(video, start, end, w, h, fps, hwaccel),
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL,
                            creationflags=CREATE_NO_WINDOW)
    frame_size = w * h
    prev = None
    scores = []
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                break
            buf = proc.stdout.read(frame_size)
            if not buf or len(buf) < frame_size:
                break
            gray = np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
            gray = cv2.GaussianBlur(gray, BLUR_KERNEL, 0)
            if prev is not None:
                diff = np.abs(gray.astype(np.int16) - prev.astype(np.int16))
                scores.append(float((diff > DIFF_THRESHOLD).sum()) / (w * h))
            else:
                scores.append(0.0)
            prev = gray
    finally:
        proc.stdout.close()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    return scores


def _analyze_chunk(video, start, end, w, h, fps, cancel_event):
    """解码并分析一段视频，返回 (start, [每采样帧运动分])。

    硬件解码不可用时（例如无独显 / 驱动不支持）会自动回退到软件解码，
    保证在任何机器上都能正常分析。
    """
    attempts = [True, False]   # 先硬解（d3d11va），无输出回退软解
    for i, hw in enumerate(attempts):
        scores = _run_chunk(video, start, end, w, h, fps, hw, cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return start, scores
        # 有结果，或已是最后一次尝试 → 采用
        if scores or i == len(attempts) - 1:
            return start, scores
        # 硬件解码没产出任何帧 → 回退软解再试
    return start, []


def analyze_motion(video_path, config, progress_cb=None, cancel_event=None):
    """分析视频运动强度，返回每秒一个值的列表（0~1，越大动作越多）。"""
    w = config.resize_width
    vw, vh, _ = probe_stream(video_path)
    if vw <= 0 or vh <= 0:
        # 拿不到分辨率时按 16:9 兜底
        vw, vh = 1920, 1080
    # 按源画面比例计算目标高度，并保证偶数
    h = int(vh * w / vw)
    h -= h % 2
    if h < 2:
        h = 2

    fps = config.sample_fps
    duration = get_duration(video_path)
    if duration <= 0:
        return []

    # 分块并行解码
    n_chunks = max(1, int(math.ceil(duration / CHUNK_SEC)))
    workers = max(1, min(MAX_WORKERS, n_chunks, os.cpu_count() or 2))

    # 进度按「已完成块数 / 总块数」上报：
    # 只解关键帧时实际帧数无法预知，用块数作分母才能保证进度真实推进到 100%。
    state = {"done": 0}
    lock = threading.Lock()

    def _tick():
        with lock:
            state["done"] += 1
            done = state["done"]
        if progress_cb is not None:
            progress_cb(min(1.0, done / n_chunks), done, n_chunks)

    step = duration / n_chunks
    bounds = [(i * step, min((i + 1) * step, duration)) for i in range(n_chunks)]

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_analyze_chunk, video_path, s, e, w, h, fps,
                          cancel_event) for s, e in bounds]
        for fut in as_completed(futs):
            start, scores = fut.result()
            results[start] = scores
            _tick()

    # 按秒聚合（块内第 i 帧的时间 = 块起点 + i / fps）
    frame_time = 1.0 / fps
    seconds = int(duration) + 1
    per_second = [0.0] * seconds
    counts = [0] * seconds
    for start, scores in results.items():
        for i, s in enumerate(scores):
            t = int(start + i * frame_time)
            if 0 <= t < seconds:
                per_second[t] += s
                counts[t] += 1
    for t in range(seconds):
        if counts[t]:
            per_second[t] /= counts[t]
    return per_second
