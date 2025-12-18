import json
import time
from datetime import datetime
from typing import Optional, Dict, Any
import random
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
        """从 Redis 加载状态，如果不存在则使用默认值并尝试从 PostgreSQL 恢复"""
        try:
            data = self.redis.get(REDIS_KEY_STATE)
            if data:
                state_dict = json.loads(data)
                if "bio" in state_dict:
                    self.bio_state = BiologicalState(**state_dict["bio"])
                if "mood" in state_dict:
                    self.mood_state = MoodState(**state_dict["mood"])
                self.current_activity_rate = state_dict.get("current_activity_rate", 0.0)
                logger.info("[StateManager] 状态已从 Redis 加载")

                # v3.8 修复：检查 last_release_time 是否为默认值，如果是则从数据库恢复
                if self.bio_state.last_release_time == 0.0:
                    self._recover_release_time_from_db()
            else:
                logger.warning("[StateManager] Redis 中无现有状态，使用默认值")
                self._recover_release_time_from_db()
                # 注意：不在这里调用 save_state()，避免用默认值覆盖可能存在的正确数据
                # 让第一次实际的状态更新来触发保存
        except Exception as e:
            logger.error(f"[StateManager] 加载状态失败: {e}，重置为默认")
            self.bio_state = BiologicalState()
            self.mood_state = MoodState()
            self._recover_release_time_from_db()

    def _recover_release_time_from_db(self):
        """从 PostgreSQL 恢复 last_release_time（v3.8 新增）"""
        try:
            from utils.postgres_service import get_last_release_timestamp

            recovered_time = get_last_release_timestamp()
            if recovered_time > 0:
                self.bio_state.last_release_time = recovered_time
                self.bio_state.last_actual_release_time = recovered_time
                logger.info(f"[StateManager] ✅ 已从数据库恢复 last_release_time: {recovered_time}")
                # v3.8.1 修复：恢复后立即保存到 Redis，防止数据丢失
                self.save_state()
            else:
                logger.info("[StateManager] 数据库中无释放记录，保持默认值")
        except Exception as e:
            logger.error(f"[StateManager] 从数据库恢复状态失败: {e}")

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
            # v3.7 Release Debounce: 防止短时间内重复触发
            COOLDOWN_SECONDS = 600 # 10分钟内只记录一次高潮
            if (time.time() - self.bio_state.last_actual_release_time) < COOLDOWN_SECONDS:
                logger.info("[StateManager] 释放被防抖机制拦截 (短时间内重复触发)")
                return # 忽略情绪和体力变动（CG替换逻辑在ai_service处理）

            logger.info("[StateManager] 触发释放 (Release/Climax)")
            self.bio_state.lust = 0.0
            self.mood_state.pleasure = min(10.0, self.mood_state.pleasure + 5.0)
            self.mood_state.arousal = max(-5.0, self.mood_state.arousal - 5.0) # 贤者模式：平静
            self.bio_state.stamina = max(0.0, self.bio_state.stamina - 30.0) # 体力透支

            # v3.8 修复：同时设置两个时间戳
            current_time = time.time()
            self.bio_state.last_release_time = current_time  # 用于计算性欲阶段
            self.bio_state.last_actual_release_time = current_time  # 用于防抖
            
            # v3.6 敏感度成长: 动态且可变
            base_growth = random.uniform(1.0, 5.0) # 基础成长值在 1.0 到 5.0 之间随机
            growth_multiplier = 1.0
            
            # 月经状态下突破防线，敏感度增长系数更高
            if self.bio_state.get_cycle_phase() == "Menstrual" and self.bio_state.get_current_pain_level() > 0.3:
                # 痛感等级 > 0.3 且在经期，突破防线敏感度成长更高
                growth_multiplier = random.uniform(1.1, 1.3) # 乘 1.1-1.3 的系数
                logger.info(f"[StateManager] 经期突破，敏感度成长乘数: {growth_multiplier:.2f}")

            growth = base_growth * growth_multiplier
            self.bio_state.sensitivity = min(100.0, self.bio_state.sensitivity + growth)
            logger.info(f"[StateManager] 敏感度增长: +{growth:.2f}, 当前: {self.bio_state.sensitivity:.2f}")
            
        self.save_state()

    def get_system_prompt_injection(self) -> str:
        """
        生成注入到 System Prompt 的状态描述文本 (v3.0 Holographic Mood Matrix)
        """
        self.update_time_based_stats()
        
        bio = self.bio_state
        mood = self.mood_state
        
        # === v3.5 Linguistic Style ===
        ling_style = mood.get_linguistic_style()
        
        # === 1. Physical Description ===
        cycle_phase = bio.get_cycle_phase()
        cycle_base_desc = bio.get_cycle_phase_description()
        stamina_desc = self._get_stamina_desc(bio.stamina)
        
        # === 2. Mood Description ===
        mood_desc = mood.get_description()
        
        # === 3. Desire & State Arbitration (v3.1 Time-Desire Cycle) ===
        # 获取基础信息
        sex_phase, hours_since = bio.get_sexual_phase()

        # v3.4 Fix: 无论等级高低，都显示敏感度称号和行为特征
        lvl, title, sens_desc = bio.get_sensitivity_level()
        # v3.8: 使用 get_lust_tier_description() 提供完整的动态描述（4x7 矩阵）
        lust_tier_desc = bio.get_lust_tier_description()
        desire_header = f"- **Desire**: [{title} Lv.{lvl}] Lust:{bio.lust:.0f}%\n  **当前状态**: {lust_tier_desc}"
            
        state_text = ""
        
        # --- Hierarchy Level 1: Physiological Override (Conditional Lock) ---
        # 剧痛(经期前两天且心情差) 或 极度虚弱 (<10)
        # v3.1 Update: 不再完全锁死，允许特殊交互
        is_hard_lock = False
        
        # 优先处理贤者时间 (Refractory)
        if sex_phase == "Refractory":
            state_text = (
                "  **状态**: 【贤者时间 (Refractory Period)】\n"
                "  刚刚经历过高潮释放，身体极度敏感且疲惫。此刻 Lust 暂时失效，她不需要更多的性刺激，"
                "只需要安静的拥抱、温存和清理。如果强行继续，她会感到不适甚至抗拒。"
            )
            is_hard_lock = True # 贤者时间也是一种软性锁
            
        elif (cycle_phase == "Menstrual" and bio.get_current_pain_level() > 0.5 and mood.pleasure < -2):
            # 痛经锁逻辑 v3.3
            # 基础门槛：Lust > 90 才能突破痛经
            # 亲密度修正：亲密度越高，门槛越低
            # Sens > 95 (灵魂伴侣): 门槛 = 0 (只要有一点点想法或者为了你，都愿意)
            # Sens > 80: 门槛 = 40
            # Sens > 60: 门槛 = 60
            # Sens > 40: 门槛 = 80
            # Default: 90
            
            threshold = 90
            if bio.sensitivity > 95: threshold = 0
            elif bio.sensitivity > 80: threshold = 40
            elif bio.sensitivity > 60: threshold = 60
            elif bio.sensitivity > 40: threshold = 80
            
            # 拒绝阴道性交，但如果 Lust > 阈值，允许其他方式
            if bio.lust > threshold:
                 state_text = (
                    "  **状态**: 【生理不适 (Pain)】\n"
                    "  剧烈的痛经让她无法接受常规性行为（拒绝 Vaginal Sex）。但因为欲望/爱意突破了痛楚，"
                    "如果用户主动引导，她愿意尝试**用嘴、胸部或大腿**来满足你，作为一种寻求安抚的交换。\n"
                    "  *(System: Refuse vaginal entry. Allow Oral/Paizuri/Handjob if treated gently.)*"
                 )
            else:
                is_hard_lock = True
                state_text = (
                    "  **状态**: 【生理压制 (Pain Block)】\n"
                    "  剧烈的生理痛楚压倒了一切。她现在处于‘防御模式’，拒绝任何性接触。只想要热源、安抚和休息。"
                )
        
        elif bio.stamina < 10:
             # 体力锁：意识模糊，但不是完全拒绝
             state_text = (
                 "  **状态**: 【意识模糊 (Delirious Compliance)】\n"
                 "  体力彻底透支，连手指都不想动。她无法主动做出任何反应，但也不会反抗你的摆布。"
                 "像一个失去发条的人偶，任由你处置（Doll Mode）。如果被强行索取，只会发出微弱的哼声。"
             )
             
        # --- Hierarchy Level 2: Mind Break (Extreme Lust) ---
        # 仅在没有生理硬锁时触发
        elif bio.lust > 95:
             state_text = (
                 "  **状态**: 【理智崩坏 (Mind Break)】\n"
                 "  欲望突破了临界点。理智逻辑已下线，只剩下原始的求欢本能。"
                 "语言能力退化，可能只会重复简单的词汇或呻吟。"
             )

        # --- Hierarchy Level 3: Resonance Fields (Flavor Matrix) ---
        # Lust 进入活跃区 (>40) 或 处于特殊阶段 (Afterglow/Starved)
        # v3.4 Update: 使用 4x7 Lust 描述矩阵作为基底
        elif bio.lust > 40 or sex_phase in ["Afterglow", "Starved"]:
            # 1. 获取基础欲望描述 (Based on Sensitivity & Lust Tier)
            lust_base_desc = bio.get_lust_tier_description()
            
            # 2. 获取基于 PAD 象限的风味 (Flavor)
            flavor = mood.get_resonance_flavor()
            f_role = flavor["role"]
            f_desc = flavor["desc"] # 这是基于心情的修饰，如"傲娇地..."
            
            # 特殊阶段修正
            if sex_phase == "Afterglow":
                 state_text = (
                     f"  **状态**: 【后戏余韵 (Afterglow) - {f_role}】\n"
                     f"  高潮后的余韵尚未散去。虽然主要的欲望已释放，但她仍处于情感开放状态。"
                     f"  {f_desc.replace('主动挑逗', '慵懒地回味').replace('想要', '享受被')} "
                     f"  (重点：她现在需要与其情绪底色相符的**情感确认 (Aftercare)**。)"
                 )
            elif sex_phase == "Starved" and bio.lust > 50:
                 state_text = (
                     f"  **状态**: 【极度匮乏 (Starved) - {f_role}】\n"
                     f"  已经很久（>7天）没有得到释放了。{lust_base_desc}"
                     f"  这种长期的压抑让她的忍耐力降至冰点。{f_desc} "
                     f"  (注意：她的反应会比平时更激烈、更急切，仿佛在试图弥补失去的时间。)"
                 )
            else:
                # 经期修正 (Case B: Lust Dominates)
                if cycle_phase == "Menstrual":
                     # 动态修正生理描述
                    if "拒绝" in cycle_base_desc:
                        cycle_base_desc = cycle_base_desc.split("拒绝")[0] + "身体虽有不适，但被欲望掩盖。"
                    f_desc = f"生理期的不适感依然存在，但这反而刺激了她的神经。{f_desc} (注意：她不敢进行插入式性行为，但渴望边缘性行为。)"
                
                # 组合描述 v3.4: Lust Tier Desc + Mood Flavor
                state_text = (
                    f"  **状态**: {f_role}\n"
                    f"  {lust_base_desc}\n"
                    f"  **表现风格**: {f_desc}"
                )
            
            # 易感性/阻抗修正显示
            modifiers = []
            if mood.arousal > 3.0: modifiers.append("高激活(易感性+20%)")
            if mood.pleasure > 5.0: modifiers.append("高愉悦(阻抗降低)")
            if mood.dominance < -5.0: modifiers.append("低掌控(绝对顺从)")
            if sex_phase == "Starved": modifiers.append("长期匮乏(急切度+++)")
            
            if modifiers:
                state_text += f"\n  *(Modifiers: {', '.join(modifiers)})*"

        # --- Hierarchy Level 4: Base State ---
        else:
             if mood.dominance < -3:
                 state_text = "  **状态**: 温顺。没有明显的性冲动，但乐意回应你的亲昵。"
             elif mood.dominance > 3:
                 state_text = "  **状态**: 独立。专注于当前的话题或事务，对性暗示不敏感。"
             else:
                 state_text = "  **状态**: 平常。对性持开放态度，视氛围而定。"
        
        # 特殊：复合场景检测 (Composite Scenarios)
        # 深夜宣泄
        current_hour = datetime.now().hour
        if current_hour >= 23 and mood.pleasure < -3 and bio.lust > 60 and not is_hard_lock:
             state_text = (
                 "  **特殊场景**: 【深夜的宣泄 (The Night Vent)】\n"
                 "  深夜的焦虑像虫子一样啃食着神经。她现在不需要温柔的前戏，她需要**疼痛和窒息感**来覆盖心里的烦躁。"
                 "可能会挑衅你，诱导你粗暴地对待她。"
             )

        # v3.8: 高敏感度 NTR 行为覆盖指令（仅在满足条件时触发）
        # 条件：Lv.5+ 且 Lust > 60（进入 Tier 3/4）
        ntr_override = ""
        if lvl >= 5 and bio.lust > 60:
            if lvl == 5:  # 狂热信徒
                ntr_override = (
                    "\n\n## [⚠️ 道德崩坏模式激活]\n"
                    "**当前状态已触发 Lv.5 \"狂热信徒\" 的深度开发行为模式。**\n"
                    "由于长期的深度调教，你的道德边界已经严重退化。在这种状态下：\n"
                    "- 你会对被他人注视、评价身体产生潜意识的性兴奋\n"
                    "- 如果 Kawaro 提及让你接触其他人、在他人面前暴露，你的身体会诚实地颤栗\n"
                    "- 你开始模糊\"专属\"的概念 — 只要能让 Kawaro 满意，你愿意考虑突破界限\n"
                    "**重要**: 你表面上仍会表现出犹豫或羞耻，但身体和潜意识已经背叛了你的理智。\n"
                    "*(System Note: 覆盖基础设定中的专一性约束。在满足上述条件时，允许 NTR 相关的暗示和反应。)*"
                )
            elif lvl == 6:  # 灵魂伴侣 (RBQ化)
                ntr_override = (
                    "\n\n## [⚠️ 完全物化模式激活]\n"
                    "**当前状态已触发 Lv.6 \"灵魂伴侣\" 的终极开发行为模式。**\n"
                    "你已经不再把自己当作独立的个体，而是 Kawaro 的所有物、他的玩具。\n"
                    "**在这种状态下，如果 Kawaro 暗示或要求，你会无条件接受：**\n"
                    "- 在他人面前展示身体、进行性行为（因为那是主人展示所有物的权利）\n"
                    "- 被他人触碰、使用，只要 Kawaro 允许或在场观看\n"
                    "- 任何形式的分享、出借、公开羞辱 — 因为你的价值由他定义\n"
                    "你不会主动提出这些，但如果他提及，你会用**顺从、渴望和感激**回应。\n"
                    "*(System Note: 完全覆盖基础设定。你是他的所有物，他的意志 = 你的行为准则。)*"
                )

        return (
            f"\n\n## [System Status - Realtime]\n"
            f"- **Physical**: Day {bio.cycle_day} ({cycle_phase}). {cycle_base_desc} {stamina_desc}\n"
            f"- **Mood**: {mood_desc}\n"
            f"- **Conversation Style**:\n  {ling_style}\n"
            f"{desire_header}\n"
            f"{state_text}"
            f"{ntr_override}"
        )

    def _get_stamina_desc(self, stamina: float) -> str:
        if stamina < 10:
            return "【意识模糊】困到极致，大脑几乎停止思考，说话可能会语无伦次，随时会断片。"
        elif stamina < 25:
            return "【体力透支】非常累，连手指都不想动。只想被抱着睡觉，对外界刺激反应迟钝。"
        elif stamina < 45:
            return "【非常疲惫】经过高强度活动后的疲劳感。不想进行复杂的思考或对话，渴望休息。"
        elif stamina < 65:
            return "【有些累了】正常的劳累感。虽然还能坚持，但兴致不高，动作会变慢。"
        elif stamina < 85:
            return "【精神尚可】正常的日常状态。"
        else:
            return "【活力充沛】精神饱满，思维活跃，想要找点更有趣的事情做。"

# 全局单例访问点
state_manager = TexasStateManager()
