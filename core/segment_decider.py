# -*- coding: utf-8 -*-
"""片段决策器：把每秒运动分曲线切分成「保留段 / 删除段」。

流程：阈值二值化 -> 平滑去抖 -> 切段 -> 过滤短片段 -> 加前后余量。
"""
from typing import List

from core.models import Segment, Config


def decide_segments(motion_scores: List[float], config: Config) -> List[Segment]:
    """输入每秒运动分，输出带 keep 标记的片段列表（秒）。"""
    n = len(motion_scores)
    if n == 0:
        return []

    threshold = config.threshold

    # 1. 二值化：>= 阈值 算“有动作”
    binary = [1 if s >= threshold else 0 for s in motion_scores]

    # 2. 中值平滑（窗口 3 秒，去单秒抖动）
    smoothed = []
    for i in range(n):
        win = binary[max(0, i - 1): min(n, i + 2)]
        smoothed.append(1 if sum(win) >= 2 else 0)

    # 3. 切分成连续段
    raw = []
    i = 0
    while i < n:
        j = i
        while j < n and smoothed[j] == smoothed[i]:
            j += 1
        raw.append([i, j, bool(smoothed[i])])
        i = j

    # 4. 过滤短片段（太短的保留段转删除，太短的删除段转保留）
    filtered = []
    for s, e, keep in raw:
        length = e - s
        if keep and length < config.min_keep:
            keep = False
        elif not keep and length < config.min_delete:
            keep = True
        if filtered and filtered[-1][2] == keep:
            filtered[-1][1] = e  # 合并相邻同类型
        else:
            filtered.append([s, e, keep])

    # 5. 加前后余量（仅保留段）
    result = []
    for s, e, keep in filtered:
        if keep:
            s = max(0, s - config.padding)
            e = min(n, e + config.padding)
        seg = Segment(start=s, end=e, keep=keep)
        if result and result[-1].keep and keep and s <= result[-1].end + 1e-6:
            result[-1].end = max(result[-1].end, e)  # 余量导致相邻保留段合并
        else:
            result.append(seg)
    return result


def merge_adjacent_keeps(segments: List[Segment]) -> List[Segment]:
    """把相邻的保留段合并为一段（导出前调用，减少切片数量）"""
    segs = sorted(segments, key=lambda s: s.start)
    out = []
    for s in segs:
        if not s.keep:
            out.append(s)
            continue
        if out and out[-1].keep and s.start <= out[-1].end + 1e-6:
            out[-1].end = max(out[-1].end, s.end)
        else:
            out.append(Segment(s.start, s.end, True, s.score))
    return out


def summarize(segments: List[Segment], duration: float):
    """返回 (保留秒数, 删除秒数, 压缩百分比)"""
    keep = sum(s.duration for s in segments if s.keep)
    total = duration if duration > 0 else keep
    ratio = (1 - keep / total) * 100 if total > 0 else 0.0
    return keep, max(0.0, total - keep), ratio
