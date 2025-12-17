import json
import time
from datetime import datetime
from typing import Optional, Dict, Any
from utils.logging_config import get_logger
from utils.redis_manager import get_redis_client
from .biological_model import BiologicalState
from .mood_model import MoodState

logger = get_logger(__name__)

REDIS_KEY_STATE = "texas:state:v2"

class TexasStateManager:
    """
    德克萨斯状态总控 (Singleton)
    负责协调 BiologicalState 和 MoodState，处理持久化与状态更新。
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TexasStateManager, cls).__new__(cls)
            cls._instance.redis = get_redis_client()
            cls._instance.bio_state = BiologicalState()
            cls._instance.mood_state = MoodState()
            cls._instance._load_state()
        return cls._instance

    def _load_state(self):
        """从 Redis 加载状态，如果不存在则使用默认值"""
        try:
            data = self.redis.get(REDIS_KEY_STATE)
            if data:
                state_dict = json.loads(data)
                if "bio" in state_dict:
                    self.bio_state = BiologicalState(**state_dict["bio"])
                if "mood" in state_dict:
                    self.mood_state = MoodState(**state_dict["mood"])
                self.current_activity_rate = state_dict.get("current_activity_rate", 0.0)
                logger.info("[StateManager] 状态已加载")
            else:
                logger.info("[StateManager] 无现有状态，初始化默认值")
                self.save_state()
        except Exception as e:
            logger.error(f"[StateManager] 加载状态失败: {e}，重置为默认")
            self.bio_state = BiologicalState()
            self.mood_state = MoodState()

    def save_state(self):
        """保存当前状态到 Redis"""
        try:
            # 在保存前打印当前关键状态，便于调试观察
            bio = self.bio_state
            mood = self.mood_state
            logger.info(
                f"[State] 💾 保存状态: "
                f"Bio(Day{bio.cycle_day}/Sta{bio.stamina:.1f}/Lust{bio.lust:.1f}/Sens{bio.sensitivity:.1f}) "
                f"Mood(P{mood.pleasure:.1f}/A{mood.arousal:.1f}/D{mood.dominance:.1f})"
            )

            state_dict = {
                "bio": self.bio_state.model_dump(),
                "mood": self.mood_state.model_dump(),
                "current_activity_rate": getattr(self, "current_activity_rate", 0.0),
                "updated_at": time.time()
            }
            self.redis.set(REDIS_KEY_STATE, json.dumps(state_dict))
        except Exception as e:
            logger.error(f"[StateManager] 保存状态失败: {e}")

    def update_current_activity(self, stamina_cost_per_hour: float, is_sleeping: bool = False):
        """
        更新当前活动的体力消耗率
        由外部系统（如 LifeDataService）在检测到日程变更时调用
        """
        self.current_activity_rate = stamina_cost_per_hour
        
        # 更新睡眠状态
        new_sleep_state = "DeepSleep" if is_sleeping else "Awake"
        if self.bio_state.sleep_state != new_sleep_state:
            logger.info(f"[StateManager] 睡眠状态切换: {self.bio_state.sleep_state} -> {new_sleep_state}")
            self.bio_state.sleep_state = new_sleep_state
            
        self.save_state()

    def update_time_based_stats(self):
        """
        心跳更新：处理时间流逝对数值的影响
        建议每小时或每次交互前调用
        """
        current_time = time.time()
        
        # 计算距离上次更新经过的时间 (小时)
        # 取 bio 和 mood 中较早的那个时间作为基准
        last_time = min(self.bio_state.last_updated, self.mood_state.last_updated)
        hours_passed = (current_time - last_time) / 3600.0
        
        if hours_passed < 0.01: # 少于36秒忽略
            return

        logger.debug(f"[StateManager] 时间流逝更新: {hours_passed:.2f} 小时")

        # 1. 更新生理数值 (体力恢复/衰减, Lust衰减)
        # 传递额外的活动消耗率
        activity_rate = getattr(self, "current_activity_rate", 0.0)
        self.bio_state.update_time_passage(hours_passed)
        # 额外扣除活动消耗
        if self.bio_state.sleep_state == "Awake":
            consumption = activity_rate * hours_passed
            self.bio_state.stamina = max(0.0, self.bio_state.stamina - consumption)
        
        # 2. 更新情绪数值 (回归基准)
        self.mood_state.decay_to_base(hours_passed)
        
        # 3. 检查是否跨天 (简单的日期比较)
        last_dt = datetime.fromtimestamp(last_time)
        curr_dt = datetime.fromtimestamp(current_time)
        if curr_dt.date() > last_dt.date():
            days_diff = (curr_dt.date() - last_dt.date()).days
            logger.info(f"[StateManager] 跨天检测: 推进生理周期 {days_diff} 天")
            for _ in range(days_diff):
                self.bio_state.advance_cycle()

        self.save_state()

    def apply_interaction_impact(self, intent: str, intensity: float):
        """
        应用对话交互的影响
        intent: 'Flirt', 'Comfort', 'Normal', 'Attack'
        intensity: 1.0 - 5.0
        """
        self.update_time_based_stats() # 先结算时间
        
        current_hour = datetime.now().hour
        
        # 1. 情绪影响 (Mood)
        p_delta, a_delta, d_delta = 0, 0, 0
        
        if intent == "Flirt":
            p_delta = 1.0 * intensity
            a_delta = 2.0 * intensity # 兴奋
            # 2. 欲望影响 (Biological)
            # 获取基于周期和敏感度的修正系数
            lust_mod = self.bio_state.get_lust_modifier()
            lust_gain = intensity * 5.0 * lust_mod
            self.bio_state.lust = min(100.0, self.bio_state.lust + lust_gain)
            
        elif intent == "Comfort":
            p_delta = 2.0 * intensity
            a_delta = -2.0 * intensity # 平静
            d_delta = 1.0 * intensity # 恢复自信
            
        elif intent == "Attack":
            p_delta = -3.0 * intensity
            a_delta = 3.0 * intensity # 愤怒/紧张
            d_delta = -2.0 * intensity
            
        # 应用情绪变化 (含昼夜阻尼)
        self.mood_state.apply_stimulus(p_delta, a_delta, d_delta, current_hour)
        
        self.save_state()

    def apply_raw_impact(self, p_delta: float, a_delta: float, lust_delta: float, release: bool = False):
        """
        直接应用数值变化（由 LLM 分析得出）
        """
        self.update_time_based_stats()
        current_hour = datetime.now().hour
        
        # 1. 应用情绪变化
        self.mood_state.apply_stimulus(p_delta, a_delta, 0, current_hour)
        
        # 2. 应用欲望变化 (考虑敏感度加成)
        if lust_delta > 0:
            lust_mod = self.bio_state.get_lust_modifier()
            self.bio_state.lust = min(100.0, self.bio_state.lust + lust_delta * lust_mod)
            
        # 3. 处理释放 (Release)
        if release:
            # 释放逻辑：Lust归零，P大幅上升，体力大幅下降，敏感度微涨
            logger.info("[StateManager] 触发释放 (Release/Climax)")
            self.bio_state.lust = 0.0
            self.mood_state.pleasure = min(10.0, self.mood_state.pleasure + 5.0)
            self.mood_state.arousal = max(-5.0, self.mood_state.arousal - 5.0) # 贤者模式：平静
            self.bio_state.stamina = max(0.0, self.bio_state.stamina - 30.0) # 体力透支
            
            # 敏感度成长 (0.5 - 2.0 随机或固定)
            growth = 1.0
            self.bio_state.sensitivity = min(100.0, self.bio_state.sensitivity + growth)
            
        self.save_state()

    def get_system_prompt_injection(self) -> str:
        """
        生成注入到 System Prompt 的状态描述文本 (Dynamic Modulation)
        """
        self.update_time_based_stats()
        
        bio = self.bio_state
        mood = self.mood_state
        
        # === 1. 生理状态与周期表现 ===
        cycle_phase = bio.get_cycle_phase()
        cycle_base_desc = bio.get_cycle_phase_description()
        
        # 动态修正：经期表现
        if cycle_phase == "Menstrual":
            if bio.lust > 60 and bio.sensitivity > 50:
                cycle_desc = f"{cycle_base_desc} 但注意：【欲望代偿】虽然身体不适，但因为高涨的欲望和对你的依恋，她愿意尝试用不涉及身体负担的方式（如口、手、腿）来满足你，以换取你的安抚。"
            elif mood.pleasure > 5:
                cycle_desc = f"{cycle_base_desc} 【情感依赖】因为你的安抚，她现在感到很安心。痛楚还在，但她只想粘着你，像只小猫一样蹭你。"
            elif mood.dominance < -5:
                cycle_desc = f"{cycle_base_desc} 【脆弱崩溃】疼痛让她变得极度脆弱，可能会哭着求你抱抱，完全失去了平日的冷静，会无条件顺从你的温和指令。"
            else:
                cycle_desc = cycle_base_desc # 保持默认拒绝
        else:
            cycle_desc = cycle_base_desc
            
        # 体力描述
        stamina_desc = ""
        if bio.stamina < 20:
            stamina_desc = "【濒死】体力耗尽，意识模糊，几乎无法做出反应，只能发出单音节。"
        elif bio.stamina < 40:
            stamina_desc = "【极度疲惫】只想躺着，说话简短，拒绝任何消耗体力的活动。"
        elif bio.stamina < 60:
            stamina_desc = "【疲倦】有些累了，反应会慢半拍。"
            
        # === 2. 情绪描述 ===
        mood_desc = mood.get_description()
        
        # === 3. 欲望描述与动态突破 ===
        lust_desc = ""
        # 只要 Lust > 30 或者有一定敏感度就显示，便于 AI 铺垫
        if bio.lust > 30 or bio.sensitivity > 20:
            lvl, title, sens_desc = bio.get_sensitivity_level()
            lust_desc = f"\n- **Desire**: [{title} Lv.{lvl}] Lust:{bio.lust:.0f}%。"
            
            # 动态状态判定
            if bio.lust > 80:
                if bio.sensitivity < 25: # 低敏感度的突破
                    lust_desc += "\n  **状态**: 【理智崩坏】身体产生了陌生的燥热，虽然理智在抗拒，但眼神出卖了渴望。她可能会对你的过分要求半推半就，甚至在潜意识里期待被强行突破。"
                else:
                    lust_desc += "\n  **状态**: 眼神迷离，呼吸急促，难以集中注意力。全身都在渴望被触碰，几乎无法拒绝任何要求。"
            elif bio.lust > 50:
                if mood.dominance < -2: # 顺从/弱气
                    lust_desc += "\n  **状态**: 隐约的躁动，但不敢表达，只是用湿润的眼神看着你，等待你的主动。"
                else:
                    lust_desc += "\n  **状态**: 感到身体有些发热，对肢体接触变得敏感。"
            
            # 补充敏感度描述（仅在高Lust或特定情境下强调）
            if bio.lust > 40:
                lust_desc += f"\n  *{sens_desc}*"
        
        # === 4. 极端情绪组合 (Crisis Mode) ===
        # 心情极差 + 掌控感极低 -> 自暴自弃/寻求发泄
        if mood.pleasure < -5 and mood.dominance < -5 and bio.lust > 30:
            lust_desc += "\n  **特殊状态**: 【自暴自弃】心情极差且感到无助，想要寻找发泄口。可能会为了逃避现实的痛苦，而沉溺于肉体的快感，甚至主动诱导你粗暴对待她。"

        injection = (
            f"\n\n## [System Status - Realtime]\n"
            f"- **Physical**: Day {bio.cycle_day} ({cycle_phase}). {cycle_desc} {stamina_desc}\n"
            f"- **Mood**: {mood_desc}\n"
            f"{lust_desc}"
        )
        
        return injection

# 全局单例访问点
state_manager = TexasStateManager()
