# -*- coding: utf-8 -*-
"""核心链路自测脚本（不弹界面）：
    python test_core.py <视频路径> [快速/精确]
先切 60 秒测试片段 -> 分析运动 -> 决策片段 -> 导出 -> 打印统计。
"""
import os
import sys
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from utils.ffmpeg_utils import FFMPEG, FFPROBE, get_duration, probe_stream, run
from core.models import Config
from core.motion_analyzer import analyze_motion
from core.segment_decider import decide_segments, merge_adjacent_keeps, summarize
from core.exporter import export


def make_clip(video, seconds=60):
    """用流复制切一个短片段用于快速测试"""
    tmp = tempfile.mkdtemp(prefix="autocut_test_")
    clip = os.path.join(tmp, "clip60.mp4")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error",
           "-ss", "0", "-i", video, "-t", str(seconds),
           "-map", "0:v", "-map", "0:a?",
           "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", clip]
    p = run(cmd)
    if p.returncode != 0 or not os.path.exists(clip):
        print("切测试片段失败")
        sys.exit(1)
    return clip


def main():
    if len(sys.argv) < 2:
        print("用法: python test_core.py <视频路径> [fast/accurate]")
        sys.exit(1)
    video = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "fast"

    print("== 0. 基础信息 ==")
    dur = get_duration(video)
    w, h, fps = probe_stream(video)
    print("时长 {:.1f}s, {}x{}, {:.0f}fps".format(dur, w, h, fps))

    test = make_clip(video)
    print("测试片段:", os.path.basename(test))

    print("== 1. 运动分析 ==")
    cfg = Config(strength=50, min_keep=1.0, padding=0.3)
    scores = analyze_motion(test, cfg, progress_cb=lambda *a: None)
    print("每秒运动分数量:", len(scores))
    # 打印分布概览
    lo = sum(1 for s in scores if s < 0.02)
    mid = sum(1 for s in scores if 0.02 <= s < 0.05)
    hi = sum(1 for s in scores if s >= 0.05)
    print("运动分分布: <2%: {}s, 2~5%: {}s, >=5%: {}s".format(lo, mid, hi))

    print("== 2. 片段决策 ==")
    segs = decide_segments(scores, cfg)
    keeps = [s for s in segs if s.keep]
    dels = [s for s in segs if not s.keep]
    print("总段数 {}，保留 {} 段，删除 {} 段".format(len(segs), len(keeps), len(dels)))
    for s in segs:
        print("  {:.1f}~{:.1f}  {}".format(s.start, s.end, "保留" if s.keep else "删除"))

    keep_s, del_s, ratio = summarize(segs, len(scores))
    print("统计: 保留 {:.1f}s, 删除 {:.1f}s, 压缩 {:.0f}%".format(keep_s, del_s, ratio))

    print("== 3. 导出 ==")
    out = os.path.join(tempfile.mkdtemp(prefix="autocut_out_"), "out.mp4")
    export(test, segs, out, mode=mode)
    print("导出成功:", out, "大小 {:.1f}MB".format(os.path.getsize(out) / 1e6))
    print("== 全部通过 ==")


if __name__ == "__main__":
    main()
