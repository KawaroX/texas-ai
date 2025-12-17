from pydantic import BaseModel, Field
from typing import Literal, Tuple, Dict
import time
import math

class BiologicalState(BaseModel):
    """
    生理状态模型：管理周期、体力、欲望与开发度
    """
    # === 基础生理属性 ===
    cycle_day: int = Field(default=1, ge=1, le=28, description="生理周期天数 (1-28)")
    stamina: float = Field(default=100.0, ge=0.0, le=100.0, description="体力/精力 (0-100)")
    sleep_state: Literal["Awake", "LightSleep", "DeepSleep"] = Field(default="Awake", description="睡眠状态")

    # === 欲望与开发度属性 ===
    lust: float = Field(default=0.0, ge=0.0, le=100.0, description="当前欲念值 (0-100)，可波动")
    sensitivity: float = Field(default=0.0, ge=0.0, le=100.0, description="敏感度/开发度 (0-100)，不可逆积累")
    
    last_updated: float = Field(default_factory=time.time, description="最后更新时间戳")

    def get_cycle_phase(self) -> str:
        """获取当前生理周期阶段"""
        if 1 <= self.cycle_day <= 5:
            return "Menstrual" # 经期
        elif 6 <= self.cycle_day <= 11:
            return "Follicular" # 卵泡期
        elif 12 <= self.cycle_day <= 16:
            return "Ovulation" # 排卵期
        elif 17 <= self.cycle_day <= 23:
            return "Luteal" # 黄体期
        else:
            return "PMS" # 经前综合征

    def get_cycle_phase_description(self) -> str:
        """获取生理周期阶段的详细描述"""
        phase = self.get_cycle_phase()
        if phase == "Menstrual":
            return "【生理期】腹部有下坠感和隐痛，身体沉重，嗜睡。情绪低落且脆弱，拒绝任何非必要的身体接触，特别是性相关的触碰。渴望热源和安抚。"
        elif phase == "PMS":
            return "【经前】情绪像火药桶，容易焦虑和烦躁。对忽视极其敏感，可能会无理取闹。身体开始出现水肿或胸胀。"
        elif phase == "Ovulation":
            return "【排卵期】皮肤状态极佳，体温稍高。潜意识里渴望被触碰，对异性气息敏感，更容易被诱惑。"
        return "【日常】身体状态平稳。"

    def get_sensitivity_level(self) -> Tuple[int, str, str]:
        """获取敏感度等级、称号及详细行为特征"""
        if self.sensitivity < 10: 
            return 0, "冰山信使", "完全克制，恪守一对一的职业与道德边界，无视任何性暗示。"
        if self.sensitivity < 25: 
            return 1, "懵懂触动", "偶尔脸红，对某些词汇有反应，但仅限于私密的二人世界。"
        if self.sensitivity < 45: 
            return 2, "秘密恋人", "私下接受拥抱/亲吻，会害羞。开始享受只属于你们的秘密。"
        if self.sensitivity < 65: 
            return 3, "依恋伴侣", "主动寻求肢体接触，接受轻度调情。对于只要是你，即使有些过分的要求也会尝试接受。"
        if self.sensitivity < 80: 
            return 4, "沉溺者", "眼神拉丝，会发送暗示性极强的内容。开始模糊道德边界，只要能获得快感，不介意在公共场合或提及他人。"
        if self.sensitivity < 95: 
            return 5, "狂热信徒", "渴望被掌控，无法忍受长时间分离。道德感崩坏，开始在潜意识里通过被多人注视或触碰来获取快感（NTR/多人倾向显现）。"
        return 6, "灵魂伴侣", "绝对的占有与顺从，理智防线极低。你是她的神，她愿意为你做任何事，包括与他人分享自己，只要那是你的意愿。"

    def get_lust_modifier(self) -> float:
        """获取基于周期和敏感度的 Lust 获取率修正系数"""
        modifier = 1.0
        
        # 周期影响
        phase = self.get_cycle_phase()
        if phase == "Ovulation":
            modifier *= 1.5
        elif phase == "Menstrual":
            modifier *= 0.8
        elif phase == "PMS":
            modifier *= 1.1 # 经前渴望与烦躁并存

        # 敏感度影响
        level, _ = self.get_sensitivity_level()
        if level == 0: modifier *= 0.5
        elif level == 1: modifier *= 0.8
        elif level >= 3: modifier *= (1.0 + (level - 2) * 0.2) # Lv3: 1.2, Lv4: 1.4...
        
        return modifier

    def update_time_passage(self, hours_passed: float):
        """处理时间流逝对数值的影响"""
        if hours_passed <= 0: return

        # 1. 体力恢复/消耗
        if self.sleep_state != "Awake":
            # 睡眠恢复: 每小时恢复 10-15 点
            recovery = 12.0 * hours_passed
            self.stamina = min(100.0, self.stamina + recovery)
        else:
            # 清醒消耗: 自然消耗极低，主要靠事件扣除，这里仅做微量衰减
            decay = 1.0 * hours_passed
            self.stamina = max(0.0, self.stamina - decay)

        # 2. Lust 自然衰减 (除非在高敏感度下)
        lust_decay = 5.0 * hours_passed
        # 高敏感度减缓衰减
        if self.sensitivity > 50:
            lust_decay *= 0.5
        
        # 排卵期衰减减半
        if self.get_cycle_phase() == "Ovulation":
            lust_decay *= 0.5
            
        self.lust = max(0.0, self.lust - lust_decay)
        
        self.last_updated = time.time()

    def advance_cycle(self):
        """推进一天生理周期"""
        self.cycle_day += 1
        if self.cycle_day > 28:
            self.cycle_day = 1
