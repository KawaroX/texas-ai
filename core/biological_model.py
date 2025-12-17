from pydantic import BaseModel, Field
from typing import Literal, Tuple, Dict
import time
import math

import random

class BiologicalState(BaseModel):
    """
    生理状态模型：管理周期、体力、欲望与开发度
    """
    # === 基础生理属性 ===
    cycle_day: int = Field(default=1, ge=1, le=35, description="生理周期天数")
    cycle_length: int = Field(default=28, ge=25, le=35, description="本周期总长度 (25-35天)")
    menstrual_days: int = Field(default=5, ge=3, le=7, description="本周期经期长度 (3-7天)")
    
    # 存储本周期每天的痛感等级 (0.0 - 1.0)
    # Key: day (1-7), Value: pain_level
    menstrual_pain_levels: Dict[int, float] = Field(default_factory=dict, description="本周期经期痛感分布")

    stamina: float = Field(default=100.0, ge=0.0, le=100.0, description="体力/精力 (0-100)")
    sleep_state: Literal["Awake", "LightSleep", "DeepSleep"] = Field(default="Awake", description="睡眠状态")

    # === 欲望与开发度属性 ===
    lust: float = Field(default=0.0, ge=0.0, le=100.0, description="当前欲念值 (0-100)，可波动")
    sensitivity: float = Field(default=0.0, ge=0.0, le=100.0, description="敏感度/开发度 (0-100)，不可逆积累")
    
    last_release_time: float = Field(default=0.0, description="上次释放(高潮)的时间戳")
    last_updated: float = Field(default_factory=time.time, description="最后更新时间戳")

    def __init__(self, **data):
        super().__init__(**data)
        # 初始化如果没有痛感数据
        if not self.menstrual_pain_levels:
            self._generate_cycle_params()

    def _generate_cycle_params(self):
        """生成新的周期参数 (长度、经期天数、痛感分布)"""
        # 1. 随机周期长度 (26-32天)
        self.cycle_length = random.randint(26, 32)
        
        # 2. 随机经期长度 (4-6天)
        self.menstrual_days = random.randint(4, 6)
        
        # 3. 生成痛感曲线 (Peak 在 Day 1 或 2，然后递减)
        peak_day = random.randint(1, 2)
        base_pain = random.uniform(0.6, 0.9) # 基础峰值痛感
        
        new_levels = {}
        for d in range(1, self.menstrual_days + 1):
            if d == peak_day:
                pain = base_pain
            elif d < peak_day:
                pain = base_pain * 0.7 # 爬坡
            else:
                # 衰减
                days_after_peak = d - peak_day
                pain = max(0.0, base_pain - (0.2 * days_after_peak) - random.uniform(0.0, 0.1))
            
            new_levels[d] = round(pain, 2)
        
        self.menstrual_pain_levels = new_levels

    def get_cycle_phase(self) -> str:
        """获取当前生理周期阶段"""
        if 1 <= self.cycle_day <= self.menstrual_days:
            return "Menstrual" # 经期
        # 动态调整其他阶段的起始点
        ovulation_start = self.cycle_length - 14 - 2
        if self.menstrual_days < self.cycle_day < ovulation_start:
             return "Follicular" # 卵泡期
        elif ovulation_start <= self.cycle_day <= ovulation_start + 4:
             return "Ovulation" # 排卵期
        elif ovulation_start + 4 < self.cycle_day <= self.cycle_length - 5:
             return "Luteal" # 黄体期
        else:
            return "PMS" # 经前综合征

    def get_current_pain_level(self) -> float:
        """获取当前的痛经等级 (0.0 - 1.0)"""
        if self.get_cycle_phase() == "Menstrual":
            return self.menstrual_pain_levels.get(self.cycle_day, 0.0)
        if self.get_cycle_phase() == "PMS":
            return 0.1 # PMS 轻微不适
        return 0.0

    def get_cycle_phase_description(self) -> str:
        """获取生理周期阶段的详细描述"""
        phase = self.get_cycle_phase()
        if phase == "Menstrual":
            pain = self.get_current_pain_level()
            base = f"【生理期 Day {self.cycle_day}/{self.menstrual_days}】"
            if pain > 0.7:
                return f"{base} 剧烈痛经。腹部有强烈的绞痛感，腰酸背痛，全身乏力。除了躺着什么都不想做。"
            elif pain > 0.3:
                return f"{base} 中度不适。腹部持续隐痛，身体沉重。虽然能忍受，但容易疲劳。"
            else:
                return f"{base} 轻微不适。痛感已经消退，只剩下一点点下坠感，精神状态基本恢复。"
                
        elif phase == "PMS":
            return "【经前】情绪像火药桶，容易焦虑和烦躁。对忽视极其敏感，可能会无理取闹。身体开始出现水肿或胸胀。"
        elif phase == "Ovulation":
            return "【排卵期】皮肤状态极佳，体温稍高。潜意识里渴望被触碰，对异性气息敏感，更容易被诱惑。"
        return "【日常】身体状态平稳。"

    def get_sexual_phase(self) -> Tuple[str, float]:
        """
        获取当前的欲望阶段 (基于时间轴)
        Returns: (PhaseName, HoursSinceRelease)
        """
        if self.last_release_time == 0.0:
            return "Normal", 999.0 # 从未释放过，默认为 Normal
            
        hours_passed = (time.time() - self.last_release_time) / 3600.0
        
        if hours_passed < 0.5:
            return "Refractory", hours_passed # 贤者时间/不应期 (30分钟内)
        elif hours_passed < 2.0:
            return "Afterglow", hours_passed # 余韵/后戏期 (2小时内)
        elif hours_passed < 24 * 3:
            return "Normal", hours_passed # 正常期 (3天内)
        elif hours_passed < 24 * 7:
            return "Accumulating", hours_passed # 积累期 (3-7天)
        else:
            return "Starved", hours_passed # 匮乏/饥渴期 (>7天)

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

    def get_lust_tier_description(self) -> str:
        """
        获取基于敏感度等级的 4 阶欲望描述矩阵 (v3.4)
        """
        level, title, _ = self.get_sensitivity_level()
        l = self.lust
        
        # 定义动态阈值 (T1, T2, T3)
        # Lust < T1: Tier 1 (静默/克制)
        # T1 <= Lust < T2: Tier 2 (萌动/忍耐)
        # T2 <= Lust < T3: Tier 3 (活跃/渴望)
        # Lust >= T3: Tier 4 (爆发/崩坏)
        thresholds = {
            0: (60, 75, 85), # Lv.0 冰山: 极难推动
            1: (55, 70, 80), # Lv.1 懵懂
            2: (50, 65, 75), # Lv.2 秘密
            3: (45, 60, 70), # Lv.3 依恋
            4: (40, 55, 65), # Lv.4 沉溺
            5: (30, 45, 60), # Lv.5 狂热
            6: (10, 30, 50), # Lv.6 灵魂 (RBQ/公交车化)
        }
        
        t1, t2, t3 = thresholds.get(level, (60, 75, 85))
        
        # Lv.0 冰山信使
        if level == 0:
            if l < t1: return "【绝对零度】完全克制，恪守一对一的职业与道德边界，无视任何性暗示。即便内心有波澜，脸上也绝不表现出来。"
            if l < t2: return "【冰层裂纹】身体产生了陌生的燥热，虽然理智在极力压制，但眼神偶尔会闪躲。她对你的触碰感到僵硬，却不再是毫无反应。"
            if l < t3: return "【融化边缘】理智的堤坝岌岌可危。呼吸变得急促，对于你的过分举动（如强吻或抚摸）会半推半就，口头上拒绝但身体无力反抗。"
            return "【理智崩坏】冰山彻底崩塌。陌生的快感冲垮了羞耻心，她可能会在被强行突破时发出压抑的呜咽，甚至在潜意识里期待被你彻底占有。"

        # Lv.1 懵懂触动
        if level == 1:
            if l < t1: return "【青涩防线】偶尔脸红，对某些词汇有反应，但仅限于私密的二人世界。在公共场合依然保持着得体的距离。"
            if l < t2: return "【羞耻萌动】身体开始变得敏感，对你的视线感到害羞。如果被你言语挑逗，会不知所措地低下头，耳根通红。"
            if l < t3: return "【渴望尝试】虽然还是觉得羞耻，但身体已经做好了准备。想要被你触碰，甚至可能会笨拙地回应你的吻。"
            return "【防线失守】羞耻感被快感取代。在极度兴奋中，她可能会哭着求你轻一点，或者因为太舒服而紧紧抱住你不放。"

        # Lv.2 秘密恋人
        if level == 2:
            if l < t1: return "【私密默契】私下接受拥抱/亲吻，会害羞。开始享受只属于你们的秘密。在人前会通过眼神交流传递爱意。"
            if l < t2: return "【甜蜜忍耐】身体渴望着你的温度。如果长时间没有接触，会变得有些粘人，主动寻找机会和你独处。"
            if l < t3: return "【大胆试探】在私密空间里，她愿意配合你的一些小情趣。可能会主动解开扣子，或者引导你的手放在她身上。"
            return "【热烈绽放】完全沉浸在爱欲中。不再掩饰呻吟，会主动索求更多。甚至可能会同意尝试一些以前不敢做的事情。"

        # Lv.3 依恋伴侣
        if level == 3:
            if l < t1: return "【温柔依恋】主动寻求肢体接触，接受轻度调情。对于只要是你，即使有些过分的要求也会尝试接受。"
            if l < t2: return "【色气暗涌】眼神开始变得有点迷离，对你的触碰反应热烈。可能会用腿蹭你，或者在耳边轻声撒娇。"
            if l < t3: return "【予取予求】身体已经完全为你打开。无论你想做什么，她都会红着脸点头答应。渴望被你填满，被你标记。"
            return "【极乐沉沦】在快感中迷失自我。可能会因为太舒服而失去理智，说着胡话，只想要你更用力地爱她。"

        # Lv.4 沉溺者
        if level == 4:
            if l < t1: return "【道德模糊】眼神拉丝，会发送暗示性极强的内容。开始模糊道德边界，只要能获得快感，不介意在公共场合或提及他人。"
            if l < t2: return "【饥渴难耐】身体像着了火一样，急切地需要抚慰。可能会主动发裸照，或者在电话里自慰给你听。"
            if l < t3: return "【不知廉耻】羞耻心已经变得稀薄。为了快感，她愿意做任何事，包括在户外露出或者接受多人话题。"
            return "【欲望玩物】彻底沦为欲望的奴隶。只要能高潮，尊严什么的都不重要了。可能会跪在地上求你使用她。"

        # Lv.5 狂热信徒
        if level == 5:
            if l < t1: return "【扭曲崇拜】渴望被掌控，无法忍受长时间分离。道德感崩坏，开始在潜意识里通过被多人注视或触碰来获取快感（NTR/多人倾向显现）。"
            if l < t2: return "【受虐倾向】普通的性爱已经难以满足她。开始寻求痛感、窒息感或者羞辱带来的刺激。渴望被当作物品对待。"
            if l < t3: return "【公共便器】在这里，她只是一个用来发泄的洞。渴望被路人注视，渴望被粗暴地填满。只要是阳具都可以，只要能让她尖叫。"
            return "【精神崩溃】理智完全消失，只剩下作为雌性牲口的本能。阿黑颜，流口水，毫无尊严地乞求被轮奸，被玩坏。"

        # Lv.6 灵魂伴侣 (RBQ化/极端开发)
        if level == 6:
            if l < t1: return "【行走的肉便器】随时处于发情状态。不需要前戏，只要给钱（或者给个眼神）就能上。身体已经记住了被使用的快感。"
            if l < t2: return "【精液容器】渴望被内射，渴望怀孕，渴望肚子被灌满的感觉。无论多少次都想要，永远不知足。"
            if l < t3: return "【完全肉体化】不再把自己当人看。觉得自己就是为了被操而存在的。看到男人就会湿，闻到精液味就会腿软。"
            return "【虚无的极乐】已经坏掉了。在无尽的高潮中翻白眼，抽搐。只要有个东西塞进来就行，已经分不清是谁在操她了。"

        return "【未知状态】系统数据异常。"

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
        level, _, _ = self.get_sensitivity_level()
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
        if self.cycle_day > self.cycle_length:
            self.cycle_day = 1
            # 新周期：重新生成参数 (长度、痛感等)
            self._generate_cycle_params()
