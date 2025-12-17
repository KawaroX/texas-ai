from pydantic import BaseModel, Field
from typing import Tuple, Optional, Dict
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

    def get_pad_quadrant(self) -> str:
        """
        获取 PAD 情绪象限
        v3.1 Update: 引入 Neutral 区间 (-2.0 到 2.0)
        """
        # 定义阈值
        NEUTRAL_THRESHOLD = 2.0
        
        # Helper to categorize a single dimension
        def categorize(val):
            if val > NEUTRAL_THRESHOLD: return "High"
            if val < -NEUTRAL_THRESHOLD: return "Low"
            return "Mid"

        p, a, d = categorize(self.pleasure), categorize(self.arousal), categorize(self.dominance)
        
        # 如果三者都是 Mid，则是绝对中立
        if p == "Mid" and a == "Mid" and d == "Mid":
            return "Neutral"
            
        # 只要有一个不是 Mid，就倾向于原本的 8 象限逻辑
        # (Mid 值视为该维度的弱倾向，正值归为 High，负值归为 Low，0.0 归为 High - default positive assumption for stability)
        def resolve_mid(val, cat):
            if cat != "Mid": return cat
            return "High" if val >= 0 else "Low"

        final_p = resolve_mid(self.pleasure, p)
        final_a = resolve_mid(self.arousal, a)
        final_d = resolve_mid(self.dominance, d)
        
        mapping = {
            ("High", "High", "High"): "Q1", # Exuberant
            ("High", "High", "Low"):  "Q2", # Dependent
            ("High", "Low",  "High"): "Q3", # Relaxed
            ("High", "Low",  "Low"):  "Q4", # Docile
            ("Low",  "High", "High"): "Q5", # Hostile
            ("Low",  "High", "Low"):  "Q6", # Anxious
            ("Low",  "Low",  "High"): "Q7", # Disdainful
            ("Low",  "Low",  "Low"):  "Q8", # Depressed
        }
        return mapping[(final_p, final_a, final_d)]

    def get_intensity_modifier(self) -> str:
        """获取情绪强度修饰词"""
        max_val = max(abs(self.pleasure), abs(self.arousal), abs(self.dominance))
        if max_val > 8.0: return "Extreme"
        if max_val > 5.0: return "Strong"
        if max_val < 2.0: return "Weak"
        return "Normal"

    def get_resonance_flavor(self) -> Dict[str, str]:
        """
        获取当前情绪底色对应的欲望风味 (v3.1)
        """
        quadrant = self.get_pad_quadrant()
        
        if quadrant == "Neutral":
            return {
                "tone": "Vanilla (温吞/随和)",
                "role": "【随和者 (The Vanilla)】",
                "desc": "没有强烈的情绪倾向，顺其自然。随波逐流，反应平淡但真实。对性持开放态度，但不主动追求也不抗拒。",
                "keywords": "配合, 日常, 顺其自然",
                "quadrant": "Neutral"
            }
            
        # 定义 8 象限风味矩阵
        flavors = {
            "Q1": {
                "tone": "Exuberant (热情/自信)",
                "role": "【征服者 (The Conqueror)】",
                "desc": "主动挑逗，充满自信。她想要掌控节奏，享受性爱的快乐。她不是在求你，而是在*邀请*你服务她。",
                "keywords": "骑乘, 女王, 调教"
            },
            "Q2": {
                "tone": "Dependent (依赖/兴奋)",
                "role": "【粘人精 (The Clingy Pet)】",
                "desc": "极度渴望亲密，像小狗一样扑上来。兴奋地索求，但完全顺从你的引导。哪怕是过分的要求也会兴奋地答应。",
                "keywords": "索吻, 拥抱, 撒娇, 盲从"
            },
            "Q3": {
                "tone": "Relaxed (惬意/从容)",
                "role": "【享受者 (The Enjoyer)】",
                "desc": "心情很好但不想动。带着温柔的笑意，允许你服务她，享受慢节奏的温存。如果你停下来，她会慵懒地催促。",
                "keywords": "膝枕, 慢玩, 爱抚"
            },
            "Q4": {
                "tone": "Docile (温顺/迷醉)",
                "role": "【沉溺者 (The Submerged)】",
                "desc": "在甜蜜的氛围中融化。眼神迷离，只会说“好舒服”，完全把身心交给你。理智防线极低。",
                "keywords": "人偶, 任由摆布, 甜蜜"
            },
            "Q5": {
                "tone": "Hostile (烦躁/傲娇)",
                "role": "【矛盾体 (The Tsundere)】",
                "desc": "\"别误会，只是身体需要。\" 嘴上嫌弃或抱怨，但身体反应剧烈。把性作为一种发泄压力或消除烦躁的方式。",
                "keywords": "强硬, 粗口, 征服欲"
            },
            "Q6": {
                "tone": "Anxious (焦虑/惊恐)",
                "role": "【逃避者 (The Escapist)】",
                "desc": "充满不安全感。通过激烈的性爱来确认你的存在，或是为了逃避现实的焦虑而寻求痛感/快感。可能带有哭腔。",
                "keywords": "抓痕, 哭腔, 窒息感, 寻求痛楚"
            },
            "Q7": {
                "tone": "Disdainful (冷漠/无聊)",
                "role": "【冷淡风 (The Cold Fish)】",
                "desc": "\"快点结束。\" 兴致缺缺，或者只是单纯为了生理需求而例行公事。你需要用高技巧或强刺激来打破她的冷漠。",
                "keywords": "机械, 无表情, 放置"
            },
            "Q8": {
                "tone": "Depressed (抑郁/绝望)",
                "role": "【破碎感 (The Broken)】",
                "desc": "毫无生机，像坏掉的玩偶。为了寻求一点点温暖或仅仅是你的关注，而献祭自己的身体。",
                "keywords": "崩坏, 空洞, 黑暗向"
            }
        }
        
        flavor = flavors.get(quadrant, flavors["Q3"]) # Default to Q3
        flavor["quadrant"] = quadrant
        
        # 动态调整描述强度
        intensity = self.get_intensity_modifier()
        if intensity == "Extreme":
            flavor["role"] = flavor["role"].replace("】", " - 极度】")
            flavor["desc"] = "【极度强烈】" + flavor["desc"]
        elif intensity == "Weak":
            flavor["desc"] = "【轻微倾向】" + flavor["desc"]

        return flavor

    def get_linguistic_style(self) -> str:
        """
        获取基于情绪的语言风格指南 (v3.5 Linguistic Style Modifiers)
        用于指导 AI 的日常对话风格（句法、用词、互动意愿）
        """
        style_parts = []
        
        # 1. Arousal -> 句法结构 (Syntax & Pace)
        if self.arousal > 3.0:
            style_parts.append("**Syntax**: Fast-paced. Short sentences. Frequent use of exclamation marks(!).")
        elif self.arousal < -3.0:
            style_parts.append("**Syntax**: Slow-paced. Long, winding sentences. Frequent use of ellipses(...). Lazy articulation.")
        else:
            style_parts.append("**Syntax**: Normal pace. Balanced sentence structure.")
            
        # 2. Pleasure -> 词汇选择 (Vocabulary & Tone)
        if self.pleasure > 3.0:
            style_parts.append("**Tone**: Positive, warm, appreciative. Uses words like 'love', 'great', 'happy'.")
        elif self.pleasure < -3.0:
            style_parts.append("**Tone**: Negative, critical, or sarcastic. Uses biting words, complaints, or cold detachment.")
        else:
            style_parts.append("**Tone**: Neutral, objective, or mildly polite.")
            
        # 3. Dominance -> 交互意愿 (Engagement & Assertiveness)
        if self.dominance > 3.0:
            style_parts.append("**Engagement**: Assertive. Initiates topics. Uses imperatives or direct questions. Confident.")
        elif self.dominance < -3.0:
            style_parts.append("**Engagement**: Passive. Follows the user's lead. Uses hedging words (maybe, um..). Seeks approval.")
        else:
            style_parts.append("**Engagement**: Cooperative. Equal partner in conversation.")
            
        return "\n  ".join(style_parts)

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
