# -*- coding: utf-8 -*-
"""导出模块（核心参考 LosslessCut：-c copy 流复制，原画质零损失且秒级完成）。

export_segments：每个保留段导出为独立文件，命名 = 项目名_编号.扩展名
export：把保留段先切片再用 concat 拼成一个完整视频

提速三板斧：
  1. 并行切片：多个镜头同时切（无损 4 路 / 显卡编码 3 路 / 软件编码 2 路）
  2. 显卡编码只探测一次并缓存：没有 N 卡时不再每段都白试一遍再回退
  3. 显卡编码用更快档位（p3）+ 硬件解码（-hwaccel auto）给 CPU 减负

进度显示（LosslessCut 同款原理）：
  给 ffmpeg 加 -progress pipe:1，它会在 stdout 周期性输出
  out_time_ms=已处理毫秒数，用它除以本段时长就是段内实时进度；
  并行时把各段进度加总除以总段数，就是全局进度 —— 进度条平滑不回跳。
"""
import os
import re
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.ffmpeg_utils import FFMPEG, run, CREATE_NO_WINDOW


def _safe_label(label):
    """把用户起的名字清洗成合法文件名片段：去掉 Windows 禁用字符和控制符、
    收尾空格/点、多个空格合成一个、限长 50。空名字返回空串。"""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", str(label or ""))
    s = re.sub(r"\s+", " ", s).strip().strip(".").strip()
    return s[:50]


def file_name_for(prefix, num, ext, label=""):
    """导出文件名 = 项目名_编号[_镜头名].扩展名（镜头名可选）"""
    lab = _safe_label(label)
    return "{}_{}{}.{}".format(prefix, num, "_" + lab if lab else "", ext)

# 显卡编码（h264_nvenc）是否可用：只探测一次，结果缓存
_NVENC_OK = None


def _nvenc_available():
    """用 3 帧小图探测本机 ffmpeg 能否调用 NVIDIA 显卡编码。"""
    global _NVENC_OK
    if _NVENC_OK is None:
        ok = False
        if FFMPEG:
            try:
                p = run([FFMPEG, "-hide_banner", "-loglevel", "error",
                         "-f", "lavfi", "-i", "color=black:s=256x256:r=30",
                         "-frames:v", "3", "-c:v", "h264_nvenc",
                         "-f", "null", "-"])
                ok = (p.returncode == 0)
            except Exception:
                ok = False
        _NVENC_OK = ok
    return _NVENC_OK


def _pick_workers(mode):
    """并行切片路数：无损=IO 型开 4 路；显卡编码受会话数限制开 3 路；软编码开 2 路"""
    cpu = os.cpu_count() or 4
    if mode != "accurate":
        return max(1, min(4, cpu))
    return 3 if _nvenc_available() else max(1, min(2, cpu))


def _run_cut(cmd, dur, progress_cb=None, cancel_event=None):
    """跑一次 ffmpeg 切片，实时上报段内进度。返回 (成功, 错误信息尾部, 是否取消)"""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=CREATE_NO_WINDOW)
    cancelled = False
    try:
        for raw in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                proc.kill()
                break
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("out_time_ms=") and progress_cb and dur > 0:
                try:
                    ms = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if ms >= 0:
                    progress_cb(min(1.0, ms / 1000.0 / dur))
        err = proc.stderr.read().decode("utf-8", "replace").strip()
        proc.wait()
    finally:
        for s in (proc.stdout, proc.stderr):
            try:
                s.close()
            except OSError:
                pass
    return proc.returncode == 0, err, cancelled


def _cut_clip(video_path, start, end, out_path, mode="fast",
              progress_cb=None, cancel_event=None):
    """按 [start, end] 秒切一个片段，实时上报段内进度（0~1）。

    mode:
      'fast'     流复制（无损、秒级）——切点吸附到最近关键帧，有 GOP 间隔的偏差
      'accurate' 重编码（切点准）——有 N 卡用硬件编码（探测过一次直接用，不再白试），
                 无 N 卡直接走软编码；硬件解码（-hwaccel auto）能开就开
    """
    dur = end - start
    head = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-progress", "pipe:1", "-nostats",   # 实时进度（LosslessCut 同款）
    ]
    if mode == "accurate":
        # 硬件解码：能用显卡解码就不占 CPU（不支持时 ffmpeg 自动回退软解）
        head += ["-hwaccel", "auto"]
    head += [
        "-ss", "{:.3f}".format(start), "-i", video_path,
        "-t", "{:.3f}".format(dur),
        "-map", "0:v", "-map", "0:a?",
    ]
    if mode == "accurate":
        attempts = []
        # N 卡硬编码（画质近无损；p3 档位比 medium 快一截）
        if _nvenc_available():
            attempts.append([
                "-c:v", "h264_nvenc", "-preset", "p3",
                "-rc", "vbr", "-cq", "19", "-b:v", "0",
                "-c:a", "aac", "-b:a", "192k"])
        # 软编码兜底（任何机器可用）
        attempts.append(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                         "-c:a", "aac", "-b:a", "192k"])
    else:
        attempts = [["-c", "copy", "-avoid_negative_ts", "make_zero"]]

    last_err = ""
    for enc in attempts:
        # 上一次尝试可能留了半截文件，先清掉
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        cmd = head + enc + ["-y", out_path]
        rc, err, cancelled = _run_cut(cmd, dur, progress_cb, cancel_event)
        if cancelled:
            raise RuntimeError("导出已取消")
        if rc and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return
        last_err = err
    raise RuntimeError("切片失败（{} ~ {}s）：{}".format(
        start, end, last_err[-300:] or "ffmpeg 未产出文件"))


def _cut_parallel(video_path, jobs, mode, on_progress, cancel_event):
    """并行切一批片段。jobs = [(序号, Segment, 输出路径, 显示名)]

    on_progress(总进度0~1, 已完成段数, 显示名)；
    一个片段失败立刻取消其余，优先抛真实错误（取消不算错误）。
    """
    total = len(jobs)
    if not total:
        return
    workers = min(_pick_workers(mode), total)
    prog = {}
    lock = threading.Lock()
    done = [0]
    real_error = []

    def _do_one(job):
        i, seg, out_path, name = job
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("导出已取消")

        def _seg_progress(p):
            with lock:
                prog[i] = p
                g = sum(prog.values()) / total
                d = done[0]
            if on_progress:
                on_progress(g, d, name)

        _cut_clip(video_path, seg.start, seg.end, out_path, mode,
                  progress_cb=_seg_progress, cancel_event=cancel_event)
        with lock:
            prog[i] = 1.0
            done[0] += 1
            g = sum(prog.values()) / total
            d = done[0]
        if on_progress:
            on_progress(g, d, name)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_do_one, j) for j in jobs]
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as exc:
                if "取消" not in str(exc):
                    real_error.append(exc)
                if cancel_event is not None:
                    cancel_event.set()   # 一个失败/取消，其余尽快收工
    if real_error:
        raise real_error[0]
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("导出已取消")


def _keep_sorted(segments):
    return sorted([s for s in segments if s.keep], key=lambda s: s.start)


def export_segments(video_path, segments, out_dir, prefix,
                    seq_digits=1, seq_start=1, mode="fast", ext="mp4",
                    progress_cb=None, cancel_event=None):
    """每个保留段导出为独立文件，命名 = 项目名_编号[_镜头名].扩展名
    （如 IMG_9765_1.mp4；给镜头起了名则 IMG_9765_1_下油.mp4）。

    编号从 seq_start 开始往后排（如起始 5：…_5、…_6、…_7）；
    超出位数自动加宽（起始 98、1 位 → 98、99、100）。
    progress_cb(全局进度0~1, 已完成段数, 总段数, 当前文件名)
    """
    keep_segs = _keep_sorted(segments)
    if not keep_segs:
        raise RuntimeError("没有保留片段，无法导出")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    total = len(keep_segs)
    jobs = []
    for i, seg in enumerate(keep_segs, 1):
        num = "{:0{}}".format(seq_start + i - 1, seq_digits)
        fname = file_name_for(prefix, num, ext, seg.label)
        jobs.append((i, seg, os.path.join(out_dir, fname), fname))

    def _on_progress(g, d, name):
        if progress_cb:
            progress_cb(g, d, total, name)

    _cut_parallel(video_path, jobs, mode, _on_progress, cancel_event)
    return [j[2] for j in jobs]


def export(video_path, segments, out_path, mode="fast",
           progress_cb=None, cancel_event=None):
    """切片 + concat 拼接成一个完整视频（LosslessCut 的「导出为一个文件」）。

    progress_cb(全局进度0~1, 已完成段数, 总段数)；合并阶段报 (n, n)。
    """
    keep_segs = _keep_sorted(segments)
    if not keep_segs:
        raise RuntimeError("没有保留片段，无法导出")

    tmp_dir = tempfile.mkdtemp(prefix="autocut_export_")
    total = len(keep_segs)
    CUT_W = 0.9   # 约 90% 时间花在切片，10% 在合并
    clips = [None] * total
    jobs = []
    for i, seg in enumerate(keep_segs, 1):
        clip = os.path.join(tmp_dir, "clip_{:04d}.mp4".format(i - 1))
        clips[i - 1] = clip
        jobs.append((i, seg, clip, "正在切分镜头…"))

    def _on_progress(g, d, name):
        if progress_cb:
            progress_cb(CUT_W * g, d, total, name)

    try:
        _cut_parallel(video_path, jobs, mode, _on_progress, cancel_event)

        if progress_cb:
            progress_cb(0.92, total, total, "正在把镜头拼成完整视频…")
        list_path = os.path.join(tmp_dir, "concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for c in clips:
                path = c.replace("\\", "/").replace("'", "'\\''")
                f.write("file '{}'\n".format(path))
        cmd = [
            FFMPEG, "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-map", "0:v", "-map", "0:a?",
            "-c", "copy", "-movflags", "+faststart", "-y", out_path,
        ]
        p = run(cmd)
        if p.returncode != 0 or not os.path.exists(out_path):
            err = p.stderr.decode("utf-8", "replace").strip() if p.stderr else ""
            raise RuntimeError("拼接失败，请检查磁盘空间：{}".format(
                err[-300:] or "ffmpeg 未产出文件"))
        if progress_cb:
            progress_cb(1.0, total, total, "完成")
    finally:
        for c in clips:
            if not c:
                continue
            try:
                os.remove(c)
            except OSError:
                pass
        for extra in ("concat.txt",):
            try:
                os.remove(os.path.join(tmp_dir, extra))
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass
    return out_path
