from pydantic import BaseModel, Field
from typing import Tuple, Optional
import time
import math
from datetime import datetime

class MoodState(BaseModel):
    """
    情绪状态模型 (PAD Model)
    """
    # PAD 核心数值 (-10.0 到 10.0)
    pleasure: float = Field(default=0.0, ge=-10.0, le=10.0, description="愉悦度 (P)")
    arousal: float = Field(default=0.0, ge=-10.0, le=10.0, description="激活度 (A)")
    dominance: float = Field(default=0.0, ge=-10.0, le=10.0, description="掌控度 (D)")
    
    last_updated: float = Field(default_factory=time.time, description="最后更新时间戳")
    base_mood: Tuple[float, float, float] = Field(default=(1.0, -1.0, 1.0), description="基准情绪回归点")

    def get_diurnal_damping(self, current_hour: int) -> float:
        """
        获取昼夜情绪阻尼系数
        返回 0.0-1.0，值越小代表阻尼越大（越难被改变，或者说越容易被情绪淹没？定义反了）
        
        Correction: 文档定义 "阻尼系数 Damping = 0.8" 意味着 "外界刺激只有 20% 能穿透"。
        Wait, standard physics damping: Force_net = Force_input - Damping * Velocity.
        
        按文档 v2.0 定义:
        - 白天: 阻尼 0.8 (理智) -> 效果 = Input * (1-0.8) = 0.2? 不太对，这样白天太麻木了。
        - 修正文档意图：系数应该代表 "理智防御值 (Rational Defense)"。
          - 白天: Defense = 0.8 (保留 20% 感性)
          - 晚上: Defense = 0.3 (保留 70% 感性)
          - 深夜: Defense = 0.1 (保留 90% 感性)
        """
        if 7 <= current_hour < 19:
            return 0.8 # 白天：理智高
        elif 19 <= current_hour or current_hour < 2:
            return 0.3 # 晚上：感性
        else:
            return 0.1 # 深夜：极度敏感

    def apply_stimulus(self, p_delta: float, a_delta: float, d_delta: float, current_hour: int = None):
        """
        应用外界刺激（如对话、事件）
        """
        if current_hour is None:
            current_hour = datetime.now().hour
            
        defense = self.get_diurnal_damping(current_hour)
        impact_factor = 1.0 - defense + 0.1 # 修正：保证至少有一定影响，比如白天是 1-0.8+0.1 = 0.3
        
        # 限制 impact_factor 最大为 1.0
        impact_factor = min(1.0, impact_factor)
        
        self.pleasure = max(-10.0, min(10.0, self.pleasure + p_delta * impact_factor))
        self.arousal = max(-10.0, min(10.0, self.arousal + a_delta * impact_factor))
        self.dominance = max(-10.0, min(10.0, self.dominance + d_delta * impact_factor))
        
        self.last_updated = time.time()

    def decay_to_base(self, hours_passed: float):
        """随时间回归基准情绪"""
        if hours_passed <= 0: return
        
        # 每小时回归 10%
        rate = 0.1
        factor = (1 - rate) ** hours_passed
        
        bp, ba, bd = self.base_mood
        
        self.pleasure = bp + (self.pleasure - bp) * factor
        self.arousal = ba + (self.arousal - ba) * factor
        self.dominance = bd + (self.dominance - bd) * factor
        
        self.last_updated = time.time()

    def get_description(self) -> str:
        """获取用于 Prompt 的情绪描述"""
        # 简单的最近邻分类
        intensity = math.sqrt(self.pleasure**2 + self.arousal**2 + self.dominance**2)
        
        label = "平静"
        if self.pleasure > 3: label = "开心"
        if self.pleasure > 7: label = "非常快乐"
        if self.pleasure < -3: label = "不悦"
        if self.pleasure < -7: label = "痛苦"
        
        if self.arousal > 5: label += "/激动"
        if self.arousal < -5: label += "/困倦"
        
        if self.dominance < -5: label += "/顺从"
        
        return f"{label} (P:{self.pleasure:.1f}, A:{self.arousal:.1f}, D:{self.dominance:.1f})"
