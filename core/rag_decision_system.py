import re
import time
import json
import os
import random
from typing import Dict, Optional
from dataclasses import dataclass, asdict
import jieba
import redis

import logging

logger = logging.getLogger(__name__)


@dataclass
class SimpleContext:
    """简单的动态累积上下文"""

    accumulated_score: float = 0.0
    last_update_time: float = 0.0
    # 新增：连续查询计数器
    consecutive_queries: int = 0
    # 新增：最近触发时间
    last_trigger_time: float = 0.0

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SimpleContext":
        """从字典创建实例"""
        return cls(**data)


class RAGDecisionMaker:
    """精简版RAG决策器 - 输入文本，输出布尔值（支持Redis缓存）"""

    def __init__(
        self,
        user_id: str,  # 新增用户ID参数
        search_threshold: float = 0.65,
        accumulation_threshold: float = 0.35,
        min_accumulation_threshold: float = 0.15,
        time_decay_minutes: float = 10.0,
        max_accumulation: float = 0.4,
        random_factor_weight: float = 0.05,
        cache_ttl: int = 3600,
        # 新增参数：提高触发概率的配置
        consecutive_boost_factor: float = 0.08,  # 连续查询加成因子
        max_consecutive_boost: float = 0.25,  # 最大连续查询加成
        trigger_cooldown_minutes: float = 2.0,  # 触发冷却时间（分钟）
        context_sensitivity: float = 1.2,  # 上下文敏感度倍数
        memory_boost_probability: float = 0.15,  # 记忆加成触发概率
    ):
        """
        初始化参数

        Args:
            user_id: 用户唯一标识符
            search_threshold: 搜索阈值，超过此值返回True
            accumulation_threshold: 累积阈值，超过此值且低于搜索阈值时累积
            min_accumulation_threshold: 最低累积门槛，低于此值不累积
            time_decay_minutes: 累积分数衰减时间（分钟）
            max_accumulation: 最大累积值
            random_factor_weight: 随机因子权重
            cache_ttl: Redis缓存过期时间（秒）
            consecutive_boost_factor: 连续查询加成因子
            max_consecutive_boost: 最大连续查询加成
            trigger_cooldown_minutes: 触发冷却时间
            context_sensitivity: 上下文敏感度倍数
            memory_boost_probability: 记忆加成触发概率
        """
        self.user_id = user_id
        self.search_threshold = search_threshold
        self.accumulation_threshold = accumulation_threshold
        self.min_accumulation_threshold = min_accumulation_threshold
        self.time_decay_minutes = time_decay_minutes
        self.max_accumulation = max_accumulation
        self.random_factor_weight = random_factor_weight
        self.cache_ttl = cache_ttl

        # 新增参数
        self.consecutive_boost_factor = consecutive_boost_factor
        self.max_consecutive_boost = max_consecutive_boost
        self.trigger_cooldown_minutes = trigger_cooldown_minutes
        self.context_sensitivity = context_sensitivity
        self.memory_boost_probability = memory_boost_probability

        # 初始化Redis连接
        self.redis_client = redis.Redis.from_url(os.getenv("REDIS_URL"))

        # Redis键名设计
        self._context_key = f"rag_decision:context:{self.user_id}"
        self._stats_key = f"rag_decision:stats:{self.user_id}"

        # 初始化jieba
        jieba.initialize()

        # 德克萨斯角色相关词汇 - 扩展词汇库
        self.texas_keywords = {
            "character_related": [
                "企鹅物流",
                "拉普兰德",
                "能天使",
                "可颂",
                "空",
                "罗德岛",
                "德克萨斯",
                "快递",
                "送货",
                "物流",
                "配送",
                "包裹",
                "任务",
                "工作",
                "同伴",
            ],
            "emotional_states": [
                "累了",
                "疲惫",
                "压力",
                "放松",
                "休息",
                "紧张",
                "担心",
                "开心",
                "高兴",
                "难过",
                "沮丧",
                "兴奋",
                "平静",
                "焦虑",
                "轻松",
            ],
            "relationships": [
                "朋友",
                "伙伴",
                "同事",
                "队友",
                "信任",
                "依赖",
                "关心",
                "照顾",
                "合作",
                "配合",
                "理解",
                "支持",
            ],
            "memories": [
                "记得",
                "想起",
                "回忆",
                "以前",
                "那时",
                "过去",
                "之前",
                "上次",
                "曾经",
                "最近",
                "刚才",
                "刚刚",
                "刚说",
                "提到过",
                "聊过",
            ],
            # 新增：更多触发类别
            "continuity": [
                "继续",
                "接着",
                "然后",
                "后来",
                "接下来",
                "另外",
                "还有",
                "而且",
            ],
            "uncertainty": [
                "不确定",
                "不知道",
                "可能",
                "也许",
                "大概",
                "估计",
                "应该",
                "或许",
            ],
        }

        # 语言模式 - 增强模式匹配
        self.patterns = {
            "temporal": [
                r"昨天",
                r"前天",
                r"上周",
                r"之前",
                r"那时候",
                r"当时",
                r"以前",
                r"刚才",
                r"刚刚",
                r"刚说",
                r"最近",
                r"近期",
                r"这几天",
            ],
            "referential": [
                r"那个",
                r"这个",
                r"它",
                r"他",
                r"她",
                r"那件事",
                r"这件事",
                r"那样",
                r"这样",
                r"那种",
                r"这种",
                r"如你所说",
                r"像你说的",
            ],
            "personal": [
                r"我的",
                r"你的",
                r"我们的",
                r"你知道我",
                r"你了解我",
                r"对我来说",
                r"在我看来",
                r"我觉得",
                r"我认为",
                r"我想",
                r"我希望",
            ],
            "questioning": [
                r"吗\?",
                r"呢\?",
                r"如何",
                r"怎么",
                r"为什么",
                r"什么时候",
                r"哪里",
                r"什么",
                r"谁",
                r"多少",
                r"哪个",
                r"哪种",
            ],
            # 新增：对话延续模式
            "continuation": [
                r"那么",
                r"所以",
                r"因此",
                r"不过",
                r"但是",
                r"而且",
                r"另外",
                r"还有",
                r"除了",
                r"关于",
                r"说到",
            ],
        }

        # 加载或初始化上下文
        self._context = self._load_context()

    def _load_context(self) -> SimpleContext:
        """从Redis加载上下文"""
        try:
            context_data = self.redis_client.get(self._context_key)
            if context_data:
                context_dict = json.loads(context_data.decode("utf-8"))
                logger.debug(
                    f"[RAG DECISION] Loaded context from Redis: {context_dict}"
                )
                return SimpleContext.from_dict(context_dict)
            else:
                logger.debug("[RAG DECISION] No context in Redis, using default")
        except (redis.RedisError, json.JSONDecodeError, TypeError) as e:
            logger.error(f"[RAG DECISION] Failed to load context from Redis: {e}")

        # 返回默认上下文
        return SimpleContext()

    def _save_context(self):
        """保存上下文到Redis"""
        try:
            context_data = json.dumps(self._context.to_dict())
            self.redis_client.setex(self._context_key, self.cache_ttl, context_data)
            logger.debug(
                f"[RAG DECISION] Context saved to Redis: {self._context.to_dict()}"
            )
        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(f"[RAG DECISION] Failed to save context to Redis: {e}")

    def _update_stats(self, message: str, decision: bool, final_score: float):
        """更新统计信息到Redis"""
        try:
            # 获取当前统计
            stats_data = self.redis_client.get(self._stats_key)
            if stats_data:
                stats = json.loads(stats_data.decode("utf-8"))
                logger.debug("[RAG DECISION] Loaded existing stats from Redis")
            else:
                stats = {
                    "total_queries": 0,
                    "search_count": 0,
                    "no_search_count": 0,
                    "avg_score": 0.0,
                    "last_updated": 0.0,
                }
                logger.debug("[RAG DECISION] Created new stats structure")

            # 更新统计
            stats["total_queries"] += 1
            if decision:
                stats["search_count"] += 1
            else:
                stats["no_search_count"] += 1

            # 更新平均分数（简单移动平均）
            old_avg = stats["avg_score"]
            stats["avg_score"] = (
                old_avg * (stats["total_queries"] - 1) + final_score
            ) / stats["total_queries"]
            stats["last_updated"] = time.time()

            # 保存统计
            stats_json = json.dumps(stats)
            self.redis_client.setex(self._stats_key, self.cache_ttl, stats_json)
            logger.debug(
                f"[RAG DECISION] Updated stats: total_queries={stats['total_queries']}, "
                f"search_count={stats['search_count']}, no_search_count={stats['no_search_count']}, "
                f"avg_score={stats['avg_score']:.3f}"
            )

        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(f"[RAG DECISION] Failed to update stats in Redis: {e}")

    def get_user_stats(self) -> Dict:
        """获取用户统计信息"""
        try:
            stats_data = self.redis_client.get(self._stats_key)
            if stats_data:
                return json.loads(stats_data.decode("utf-8"))
        except (redis.RedisError, json.JSONDecodeError) as e:
            print(f"Warning: Failed to get stats from Redis: {e}")

        return {
            "total_queries": 0,
            "search_count": 0,
            "no_search_count": 0,
            "avg_score": 0.0,
            "last_updated": 0.0,
        }

    def _quick_filter(self, message: str) -> Optional[bool]:
        """快速过滤明显情况 - 增强版"""
        message = message.strip()
        logger.debug(f"[RAG DECISION] Applying quick filter for: {message}")

        # 极短简单问候 - 但要考虑连续查询
        if len(message) <= 3:
            simple_greetings = ["你好", "早", "晚安", "嗯", "哦", "好的", "谢谢"]
            if any(greeting in message for greeting in simple_greetings):
                # 如果连续查询较多，即使是简单问候也可能需要搜索
                if self._context.consecutive_queries >= 3:
                    logger.debug(
                        "[RAG DECISION] Quick filter: short greeting but consecutive queries -> search"
                    )
                    return True
                logger.debug("[RAG DECISION] Quick filter: short greeting -> no search")
                return False

        # 明确的记忆相关词汇
        memory_patterns = [
            "记得",
            "还记得",
            "想起",
            "之前说过",
            "上次提到",
            "以前聊过",
            "刚才说",
            "刚提到",
        ]
        if any(pattern in message for pattern in memory_patterns):
            logger.debug("[RAG DECISION] Quick filter: memory pattern -> search")
            return True

        # 明确的时间指代
        time_patterns = [
            "昨天我们",
            "上次你",
            "之前的",
            "那时候我",
            "刚才我们",
            "刚刚你",
        ]
        if any(pattern in message for pattern in time_patterns):
            logger.debug("[RAG DECISION] Quick filter: time pattern -> search")
            return True

        # 新增：对话延续指示词
        continuation_patterns = ["那么", "所以", "因此", "接着", "然后", "另外", "还有"]
        if any(pattern in message for pattern in continuation_patterns):
            logger.debug(
                "[RAG DECISION] Quick filter: continuation pattern -> potential search"
            )
            # 延续性词汇增加搜索倾向，但不是绝对
            return None  # 需要详细分析，但会有加成

        logger.debug("[RAG DECISION] Quick filter: no match, need detailed analysis")
        return None  # 需要详细分析

    def _calculate_base_score(self, message: str) -> float:
        """计算基础分数 - 增强版"""
        total_score = 0.0
        logger.debug(f"[RAG DECISION] Calculating base score for: {message}")

        # 1. 关键词分析 - 权重调整
        # 德克萨斯相关词汇 (权重提升)
        texas_score = 0
        for category, keywords in self.texas_keywords.items():
            matches = sum(1 for keyword in keywords if keyword in message)
            if matches > 0:
                # 不同类别给予不同权重
                if category in ["memories", "continuity"]:
                    texas_score += matches * 0.15  # 记忆和连续性权重更高
                else:
                    texas_score += matches * 0.12
        total_score += min(texas_score, 0.35)  # 上限提高
        logger.debug(f"  - Texas keywords score: {min(texas_score, 0.35):.3f}")

        # 记忆相关词汇 (单独加强)
        memory_keywords = self.texas_keywords["memories"]
        memory_score = sum(
            0.18 for keyword in memory_keywords if keyword in message
        )  # 权重提升
        total_score += min(memory_score, 0.45)  # 上限提高
        logger.debug(f"  - Memory keywords score: {min(memory_score, 0.45):.3f}")

        # 2. 语言模式分析 - 权重调整
        pattern_scores = {}
        for pattern_type, patterns in self.patterns.items():
            pattern_score = 0
            for pattern in patterns:
                if re.search(pattern, message):
                    if pattern_type in ["temporal", "referential", "continuation"]:
                        pattern_score += 0.12  # 这些模式权重更高
                    else:
                        pattern_score += 0.10
            pattern_score = min(pattern_score, 0.3)  # 上限提高
            total_score += pattern_score
            pattern_scores[pattern_type] = pattern_score

        logger.debug(f"  - Pattern scores: {pattern_scores}")

        # 3. 个性化分析 - 增强
        personal_indicators = [
            "我的",
            "你知道我",
            "你了解",
            "对我",
            "我觉得",
            "我想要",
            "在我看来",
            "我认为",
        ]
        personal_score = sum(
            0.12
            for indicator in personal_indicators
            if indicator in message  # 权重提升
        )
        personal_score = min(personal_score, 0.3)  # 上限提高
        total_score += personal_score
        logger.debug(f"  - Personalization score: {personal_score:.3f}")

        # 情感表达 - 增强
        emotional_words = [
            "感觉",
            "觉得",
            "认为",
            "希望",
            "担心",
            "开心",
            "难过",
            "紧张",
            "兴奋",
            "平静",
            "焦虑",
            "轻松",
            "满意",
            "失望",
        ]
        emotion_score = sum(
            0.10 for word in emotional_words if word in message
        )  # 权重提升
        emotion_score = min(emotion_score, 0.25)  # 上限提高
        total_score += emotion_score
        logger.debug(f"  - Emotion score: {emotion_score:.3f}")

        # 4. 消息复杂度 - 调整
        length_score = min(len(message) / 80, 0.2)  # 长度阈值降低，上限提高
        total_score += length_score
        logger.debug(f"  - Length score: {length_score:.3f}")

        # 5. 新增：问句检测
        question_indicators = [
            "？",
            "?",
            "吗",
            "呢",
            "如何",
            "怎么",
            "为什么",
            "什么",
            "哪",
        ]
        question_score = (
            0.15
            if any(indicator in message for indicator in question_indicators)
            else 0
        )
        total_score += question_score
        logger.debug(f"  - Question score: {question_score:.3f}")

        total_score = min(total_score, 1.0)
        logger.debug(f"[RAG DECISION] Base score calculated: {total_score:.3f}")
        return total_score

    def _generate_memory_spark(self, base_score: float) -> float:
        """生成记忆突发因子 - 增强版"""
        random_factor = 0.0

        # 基础随机因子 - 范围扩大，更倾向于正值
        if base_score >= 0.1:  # 降低门槛
            # 使用更积极的随机分布
            base_random = random.gauss(0.03, 0.04)  # 均值提高，方差增加
            base_random = max(-0.03, min(base_random, 0.12))  # 范围调整
            random_factor += base_random

        # 记忆加成随机触发
        if random.random() < self.memory_boost_probability:
            memory_boost = random.uniform(0.08, 0.15)
            random_factor += memory_boost
            logger.debug(f"[RAG DECISION] Memory boost triggered: +{memory_boost:.4f}")

        # 连续查询加成
        if self._context.consecutive_queries > 0:
            consecutive_boost = min(
                self._context.consecutive_queries * self.consecutive_boost_factor,
                self.max_consecutive_boost,
            )
            random_factor += consecutive_boost
            logger.debug(
                f"[RAG DECISION] Consecutive queries boost: {consecutive_boost:.4f} (queries: {self._context.consecutive_queries})"
            )

        # 冷却时间加成 - 如果距离上次触发较久，增加触发概率
        current_time = time.time()
        if self._context.last_trigger_time > 0:
            time_since_trigger = (
                current_time - self._context.last_trigger_time
            ) / 60  # 分钟
            if time_since_trigger > self.trigger_cooldown_minutes:
                cooldown_boost = min(time_since_trigger / 60, 0.1)  # 最多10%加成
                random_factor += cooldown_boost
                logger.debug(
                    f"[RAG DECISION] Cooldown boost: {cooldown_boost:.4f} (time: {time_since_trigger:.1f}min)"
                )

        random_factor = max(-0.05, min(random_factor, 0.25))  # 总体范围限制
        logger.debug(f"[RAG DECISION] Generated memory spark: {random_factor:.4f}")

        return random_factor * self.random_factor_weight * 2  # 整体权重翻倍

    def _update_accumulation(self, current_score: float, should_search: bool):
        """更新累积分数 - 增强版"""
        current_time = time.time()

        prev_time = self._context.last_update_time

        # 更新连续查询计数
        if prev_time > 0:
            time_diff = (current_time - prev_time) / 60  # 分钟
            if time_diff <= 5:  # 5分钟内算连续
                self._context.consecutive_queries += 1
            else:
                self._context.consecutive_queries = 1  # 重置为1
        else:
            self._context.consecutive_queries = 1

        # 计算时间衰减 - 调整衰减策略
        if prev_time > 0:
            time_diff = (current_time - prev_time) / 60  # 分钟
            if time_diff > self.time_decay_minutes:
                self._context.accumulated_score = 0.0
                logger.debug(
                    f"[RAG DECISION] Accumulation reset due to time decay ({time_diff:.1f}min > {self.time_decay_minutes}min)"
                )
            else:
                # 更温和的衰减
                decay_factor = 1.0 - (
                    time_diff / (self.time_decay_minutes * 1.5)
                )  # 衰减更慢
                self._context.accumulated_score *= max(
                    decay_factor, 0.1
                )  # 保留更多累积值
                logger.debug(
                    f"[RAG DECISION] Time decay applied: decay_factor={decay_factor:.3f}, "
                    f"time_diff={time_diff:.1f}min, accumulated={self._context.accumulated_score:.4f}"
                )

        # 如果搜索了，记录触发时间但不完全重置累积
        if should_search:
            self._context.last_trigger_time = current_time
            self._context.consecutive_queries = 0  # 重置连续查询
            # 部分重置而不是完全重置
            self._context.accumulated_score *= 0.3  # 保留30%
            logger.debug("[RAG DECISION] Search triggered, partial accumulation reset")
        else:
            # 累积策略调整 - 更容易累积
            if current_score >= self.min_accumulation_threshold:  # 降低累积门槛
                if current_score >= self.accumulation_threshold:
                    # 正常累积
                    accumulation_boost = (
                        current_score - self.accumulation_threshold
                    ) * 0.6  # 系数提高
                else:
                    # 即使低于累积阈值也有小幅累积
                    accumulation_boost = (
                        current_score - self.min_accumulation_threshold
                    ) * 0.3

                # 应用上下文敏感度
                accumulation_boost *= self.context_sensitivity

                self._context.accumulated_score += accumulation_boost
                self._context.accumulated_score = min(
                    self._context.accumulated_score,
                    self.max_accumulation * 1.2,  # 上限提高
                )
                logger.debug(
                    f"[RAG DECISION] Accumulation updated: "
                    f"boost={accumulation_boost:.4f}, "
                    f"new_accumulated={self._context.accumulated_score:.4f}"
                )

        self._context.last_update_time = current_time
        logger.debug(
            f"[RAG DECISION] Context updated: accumulated_score={self._context.accumulated_score:.4f}, "
            f"consecutive_queries={self._context.consecutive_queries}, "
            f"last_update_time={current_time}"
        )

        # 保存到Redis
        self._save_context()

    def should_search(self, message: str) -> bool:
        """
        主要接口：判断是否需要搜索RAG

        Args:
            message: 用户输入的消息

        Returns:
            bool: True表示需要搜索，False表示不需要
        """
        logger.info(f"[RAG DECISION] should_search() 开始, message={message}")

        # 阶段1：快速过滤
        quick_result = self._quick_filter(message)
        if quick_result is not None:
            self._update_accumulation(0.9 if quick_result else 0.1, quick_result)
            # 更新统计
            self._update_stats(message, quick_result, 0.9 if quick_result else 0.1)
            logger.info(
                f"[RAG DECISION] Quick decision: {'SEARCH' if quick_result else 'NO SEARCH'}"
            )
            return quick_result

        # 阶段2：详细分析
        base_score = self._calculate_base_score(message)

        # 添加记忆突发因子（增强版）
        memory_spark = self._generate_memory_spark(base_score)

        # 计算当前累积加成（增强版）
        current_time = time.time()
        if self._context.last_update_time > 0:
            time_diff = (current_time - self._context.last_update_time) / 60
            if time_diff <= self.time_decay_minutes:
                decay_factor = 1.0 - (
                    time_diff / (self.time_decay_minutes * 1.5)
                )  # 更慢的衰减
                accumulated_boost = self._context.accumulated_score * max(
                    decay_factor, 0.1
                )
            else:
                accumulated_boost = 0.0
        else:
            accumulated_boost = 0.0

        # 应用上下文敏感度倍数
        accumulated_boost *= self.context_sensitivity

        # 最终分数
        final_score = min(base_score + memory_spark + accumulated_boost, 1.0)

        # 决策
        should_search_result = final_score >= self.search_threshold

        # 更新累积状态
        self._update_accumulation(final_score, should_search_result)

        # 更新统计
        self._update_stats(message, should_search_result, final_score)

        # 详细日志记录决策过程
        logger.info(
            f"[RAG DECISION] Final decision: {'SEARCH' if should_search_result else 'NO SEARCH'} | "
            f"Score: {final_score:.3f} = "
            f"base({base_score:.3f}) + "
            f"spark({memory_spark:.3f}) + "
            f"accumulated({accumulated_boost:.3f}) * sensitivity({self.context_sensitivity}) | "
            f"Threshold: {self.search_threshold} | "
            f"Consecutive: {self._context.consecutive_queries}"
        )

        return should_search_result

    def get_debug_info(self, message: str) -> Dict:
        """
        获取调试信息（可选）- 增强版

        Args:
            message: 用户输入的消息

        Returns:
            Dict: 包含详细分析信息的字典
        """
        # 这个方法用于调试，返回详细的分析过程
        quick_result = self._quick_filter(message)
        if quick_result is not None:
            return {
                "user_id": self.user_id,
                "quick_filter_result": quick_result,
                "base_score": 0.9 if quick_result else 0.1,
                "memory_spark": 0.0,
                "accumulated_boost": 0.0,
                "final_score": 0.9 if quick_result else 0.1,
                "decision": quick_result,
                "context_from_redis": True,
                "consecutive_queries": self._context.consecutive_queries,
                "enhancements_applied": "quick_filter",
            }

        base_score = self._calculate_base_score(message)
        memory_spark = self._generate_memory_spark(base_score)

        current_time = time.time()
        if self._context.last_update_time > 0:
            time_diff = (current_time - self._context.last_update_time) / 60
            if time_diff <= self.time_decay_minutes:
                decay_factor = 1.0 - (time_diff / (self.time_decay_minutes * 1.5))
                accumulated_boost = self._context.accumulated_score * max(
                    decay_factor, 0.1
                )
            else:
                accumulated_boost = 0.0
        else:
            accumulated_boost = 0.0

        accumulated_boost *= self.context_sensitivity
        final_score = min(base_score + memory_spark + accumulated_boost, 1.0)
        decision = final_score >= self.search_threshold

        return {
            "user_id": self.user_id,
            "quick_filter_result": None,
            "base_score": base_score,
            "memory_spark": memory_spark,
            "accumulated_boost": accumulated_boost,
            "final_score": final_score,
            "decision": decision,
            "current_accumulated": self._context.accumulated_score,
            "consecutive_queries": self._context.consecutive_queries,
            "context_sensitivity": self.context_sensitivity,
            "last_trigger_time": self._context.last_trigger_time,
            "context_from_redis": True,
            "enhancements_applied": "full_analysis",
        }

    def clear_user_data(self):
        """清除用户的所有缓存数据"""
        try:
            self.redis_client.delete(self._context_key)
            self.redis_client.delete(self._stats_key)
            self._context = SimpleContext()
            print(f"Cleared all data for user: {self.user_id}")
        except redis.RedisError as e:
            logger.error(f"[RAG DECISION] Failed to clear user data from Redis: {e}")

    def get_cache_info(self) -> Dict:
        """获取缓存信息"""
        try:
            context_exists = self.redis_client.exists(self._context_key)
            stats_exists = self.redis_client.exists(self._stats_key)

            context_ttl = (
                self.redis_client.ttl(self._context_key) if context_exists else -1
            )
            stats_ttl = self.redis_client.ttl(self._stats_key) if stats_exists else -1

            return {
                "user_id": self.user_id,
                "context_key": self._context_key,
                "stats_key": self._stats_key,
                "context_exists": bool(context_exists),
                "stats_exists": bool(stats_exists),
                "context_ttl": context_ttl,
                "stats_ttl": stats_ttl,
                "cache_ttl_setting": self.cache_ttl,
                "enhancements": {
                    "consecutive_boost_factor": self.consecutive_boost_factor,
                    "max_consecutive_boost": self.max_consecutive_boost,
                    "trigger_cooldown_minutes": self.trigger_cooldown_minutes,
                    "context_sensitivity": self.context_sensitivity,
                    "memory_boost_probability": self.memory_boost_probability,
                },
            }
        except redis.RedisError as e:
            logger.error(f"[RAG DECISION] Failed to get cache info: {e}")
            return {"error": f"Failed to get cache info: {e}", "user_id": self.user_id}

    def adjust_sensitivity(self, new_sensitivity: float):
        """动态调整上下文敏感度"""
        old_sensitivity = self.context_sensitivity
        self.context_sensitivity = max(0.5, min(new_sensitivity, 3.0))  # 限制在合理范围
        logger.info(
            f"[RAG DECISION] Context sensitivity adjusted: {old_sensitivity:.2f} -> {self.context_sensitivity:.2f}"
        )

    def get_performance_metrics(self) -> Dict:
        """获取性能指标"""
        stats = self.get_user_stats()
        if stats["total_queries"] == 0:
            return {"message": "No queries processed yet"}

        search_rate = stats["search_count"] / stats["total_queries"]
        current_context = self._context.to_dict()

        return {
            "search_trigger_rate": f"{search_rate:.1%}",
            "total_queries": stats["total_queries"],
            "average_score": f"{stats['avg_score']:.3f}",
            "current_accumulated_score": f"{current_context['accumulated_score']:.4f}",
            "consecutive_queries": current_context["consecutive_queries"],
            "enhancement_impact": {
                "context_sensitivity_multiplier": self.context_sensitivity,
                "consecutive_boost_available": f"{min(current_context['consecutive_queries'] * self.consecutive_boost_factor, self.max_consecutive_boost):.4f}",
                "memory_boost_probability": f"{self.memory_boost_probability:.1%}",
            },
        }


def example_usage():
    """使用示例 - 展示优化效果"""
    # 创建优化后的决策器
    user_id = "texas_user_enhanced_001"
    rag_decision = RAGDecisionMaker(
        user_id=user_id,
        search_threshold=0.65,  # 阈值不变
        accumulation_threshold=0.35,
        min_accumulation_threshold=0.15,
        time_decay_minutes=10.0,
        max_accumulation=0.4,
        random_factor_weight=0.05,
        cache_ttl=3600,
        # 新增优化参数
        consecutive_boost_factor=0.08,  # 连续查询加成
        max_consecutive_boost=0.25,  # 最大连续加成
        trigger_cooldown_minutes=2.0,  # 触发冷却
        context_sensitivity=1.3,  # 上下文敏感度提升
        memory_boost_probability=0.18,  # 记忆加成概率
    )

    # 测试消息 - 包含更多边界情况
    test_messages = [
        "晚上好！",
        "今天天气不错",
        "你觉得企鹅物流怎么样？",
        "那个问题你怎么看？",
        "嗯嗯，我明白了",
        "德克萨斯你说呢？",
        "我记得你之前说过什么来着？",
        "那么我们继续聊吧",
        "另外，我想问个问题",
        "你了解我的想法吗？",
        "刚才提到的那件事...",
        "所以你的建议是？",
    ]

    print("=== 优化版RAG决策器测试（提高触发概率）===\n")

    # 显示配置信息
    cache_info = rag_decision.get_cache_info()
    print("配置信息:")
    print(f"  - 搜索阈值: {rag_decision.search_threshold}")
    print(f"  - 上下文敏感度: {cache_info['enhancements']['context_sensitivity']}")
    print(
        f"  - 连续查询加成因子: {cache_info['enhancements']['consecutive_boost_factor']}"
    )
    print(
        f"  - 记忆加成概率: {cache_info['enhancements']['memory_boost_probability']:.1%}"
    )
    print(
        f"  - 触发冷却时间: {cache_info['enhancements']['trigger_cooldown_minutes']}分钟\n"
    )

    trigger_count = 0
    for i, message in enumerate(test_messages, 1):
        # 主要接口：直接获取布尔结果
        result = rag_decision.should_search(message)
        if result:
            trigger_count += 1

        # 获取调试信息
        debug_info = rag_decision.get_debug_info(message)

        print(f"消息 {i}: {message}")
        print(f"结果: {'🔍 需要搜索' if result else '💬 不需要搜索'}")

        if debug_info.get("enhancements_applied") == "quick_filter":
            print(f"分析: 快速过滤 -> {debug_info['final_score']:.3f}")
        else:
            print(
                f"分析: 基础{debug_info['base_score']:.3f} + "
                f"突发{debug_info['memory_spark']:.3f} + "
                f"累积{debug_info['accumulated_boost']:.3f} = "
                f"{debug_info['final_score']:.3f}"
            )
            if debug_info["consecutive_queries"] > 0:
                print(f"      连续查询: {debug_info['consecutive_queries']} 次")

        print("-" * 60)

    # 显示优化效果统计
    print("\n📊 测试结果统计:")
    print(f"总消息数: {len(test_messages)}")
    print(f"触发搜索: {trigger_count} 次")
    print(f"触发率: {trigger_count / len(test_messages):.1%}")

    # 显示性能指标
    metrics = rag_decision.get_performance_metrics()
    print("\n📈 性能指标:")
    for key, value in metrics.items():
        if isinstance(value, dict):
            print(f"{key}:")
            for sub_key, sub_value in value.items():
                print(f"  - {sub_key}: {sub_value}")
        else:
            print(f"  - {key}: {value}")

    print("\n💡 优化说明:")
    print("1. 扩展了关键词库，增加了更多触发词汇")
    print("2. 提高了各类评分的权重和上限")
    print("3. 增加了连续查询加成机制")
    print("4. 添加了记忆加成随机触发")
    print("5. 优化了累积策略，更容易累积分数")
    print("6. 增加了上下文敏感度倍数")
    print("7. 改进了时间衰减策略，保留更多历史累积")


if __name__ == "__main__":
    example_usage()
