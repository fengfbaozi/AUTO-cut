# -*- coding: utf-8 -*-
"""会话持久化（防丢恢复）：
   自动把已导入的视频、分析结果、手动调整的片段保存到本地 JSON 文件，
   程序意外关闭 / 误关 / 崩溃后，下次启动可以一键恢复，不丢失任何工作。

   存储位置：用户主目录下的 .autocut_session.json（每次原子写入，防写坏）。
"""
import json
import os
from dataclasses import dataclass, field
from typing import List

from core.models import Segment

SESSION_PATH = os.path.join(os.path.expanduser("~"), ".autocut_session.json")


@dataclass
class VideoState:
    """一个已导入视频的完整工作状态（可持久化 / 可恢复）。"""
    path: str
    duration: float = 0.0
    fps: float = 30.0
    segments: List[Segment] = field(default_factory=list)  # 分析/调整后的片段
    analyzed: bool = False
    thumb_dir: str = ""          # 本视频缩略图目录（临时，不持久化）
    thumbs: set = field(default_factory=set)   # 已生成的缩略图下标集合
    cover: str = ""              # 左侧目录封面图路径（临时，不持久化）


def _seg_to_dict(s):
    return {"start": round(s.start, 3), "end": round(s.end, 3),
            "keep": bool(s.keep), "label": s.label or ""}


def _seg_from_dict(d):
    return Segment(start=float(d["start"]), end=float(d["end"]),
                   keep=bool(d.get("keep", True)),
                   label=str(d.get("label", "") or ""))


def save_session(states, active_path):
    """把全部视频状态写盘。states: List[VideoState]；active_path: 当前打开的视频。"""
    try:
        data = {
            "version": 1,
            "active": active_path,
            "videos": [
                {
                    "path": st.path,
                    "duration": st.duration,
                    "fps": st.fps,
                    "analyzed": st.analyzed,
                    "segments": [_seg_to_dict(s) for s in st.segments],
                }
                for st in states
            ],
        }
        tmp = SESSION_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, SESSION_PATH)   # 原子替换：即使中途断电也不会留半个文件
    except Exception:
        # 保存失败不能影响主程序
        pass


def load_session():
    """返回 (states, active_path)；没有会话或文件损坏返回 None。"""
    if not os.path.exists(SESSION_PATH):
        return None
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        states = []
        for v in data.get("videos", []):
            if not os.path.exists(v["path"]):
                # 原视频已被移动/删除：跳过而不是让程序崩溃
                continue
            states.append(VideoState(
                path=v["path"],
                duration=float(v.get("duration", 0.0)),
                fps=float(v.get("fps", 30.0)),
                analyzed=bool(v.get("analyzed", False)),
                segments=[_seg_from_dict(d) for d in v.get("segments", [])],
            ))
        return states, data.get("active", "")
    except Exception:
        return None
