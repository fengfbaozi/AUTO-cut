# -*- coding: utf-8 -*-
"""核心数据结构"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class Segment:
    """时间轴上的一个片段"""
    start: float            # 起始时间（秒）
    end: float              # 结束时间（秒）
    keep: bool = True       # True=保留, False=删除
    score: float = 0.0       # 该段平均运动分（0~1）
    label: str = ""         # 镜头名（可选，导出时跟在编号后面，如 项目名_1_下油.mp4）

    @property
    def duration(self):
        return self.end - self.start


@dataclass
class Config:
    """口语化参数 -> 算法参数"""
    strength: float = 50.0    # 保留力度 0~100（0=多删, 100=多留）
    min_keep: float = 1.0     # 最短保留（秒），太短的动作不保留
    padding: float = 0.3      # 前后余量（秒），保留段前后多留的过渡
    min_delete: float = 1.0   # 最短删除（秒），太短的空白不删（防碎）
    sample_fps: float = 2.0   # 采样帧率（帧/秒），分析时用（越小越快）
    resize_width: int = 192   # 降采样宽度（像素），运动检测足够小（越小越快）

    @property
    def threshold(self):
        """保留力度 -> 运动判定阈值（越小越容易保留）"""
        return 0.05 - (self.strength / 100.0) * 0.04


@dataclass
class ProjectState:
    """当前项目状态"""
    video_path: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    motion_scores: List[float] = field(default_factory=list)  # 每秒运动分
    segments: List[Segment] = field(default_factory=list)     # 决策后的片段
    config: Config = field(default_factory=Config)
