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
    ):  # 缓存过期时间（秒）
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
        """
        self.user_id = user_id
        self.search_threshold = search_threshold
        self.accumulation_threshold = accumulation_threshold
        self.min_accumulation_threshold = min_accumulation_threshold
        self.time_decay_minutes = time_decay_minutes
        self.max_accumulation = max_accumulation
        self.random_factor_weight = random_factor_weight
        self.cache_ttl = cache_ttl

        # 初始化Redis连接
        self.redis_client = redis.Redis.from_url(os.getenv("REDIS_URL"))

        # Redis键名设计
        self._context_key = f"rag_decision:context:{self.user_id}"
        self._stats_key = f"rag_decision:stats:{self.user_id}"

        # 初始化jieba
        jieba.initialize()

        # 德克萨斯角色相关词汇
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
            ],
            "emotional_states": [
                "累了",
                "疲惫",
                "压力",
                "放松",
                "休息",
                "紧张",
                "担心",
            ],
            "relationships": ["朋友", "伙伴", "同事", "队友", "信任", "依赖"],
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
            ],
        }

        # 语言模式
        self.patterns = {
            "temporal": [
                r"昨天",
                r"前天",
                r"上周",
                r"之前",
                r"那时候",
                r"当时",
                r"以前",
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
            ],
            "personal": [
                r"我的",
                r"你的",
                r"我们的",
                r"你知道我",
                r"你了解我",
                r"对我来说",
            ],
            "questioning": [
                r"吗\?",
                r"呢\?",
                r"如何",
                r"怎么",
                r"为什么",
                r"什么时候",
                r"哪里",
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
                logger.info(f"[RAG DECISION] Successfully loaded context from Redis: {context_dict}")
                return SimpleContext.from_dict(context_dict)
            else:
                logger.info("[RAG DECISION] No context found in Redis, using default")
        except (redis.RedisError, json.JSONDecodeError, TypeError) as e:
            logger.error(f"[RAG DECISION] Failed to load context from Redis: {e}")

        # 返回默认上下文
        return SimpleContext()

    def _save_context(self):
        """保存上下文到Redis"""
        try:
            context_data = json.dumps(self._context.to_dict())
            self.redis_client.setex(self._context_key, self.cache_ttl, context_data)
            logger.debug(f"[RAG DECISION] Context saved to Redis: {self._context.to_dict()}")
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
            logger.info(
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
        """快速过滤明显情况"""
        message = message.strip()
        logger.debug(f"[RAG DECISION] Applying quick filter for: {message}")

        # 极短简单问候
        if len(message) <= 3:
            simple_greetings = ["你好", "早", "晚安", "嗯", "哦", "好的", "谢谢"]
            if any(greeting in message for greeting in simple_greetings):
                logger.debug("[RAG DECISION] Quick filter: short greeting -> no search")
                return False

        # 明确的记忆相关词汇
        memory_patterns = ["记得", "还记得", "想起", "之前说过", "上次提到", "以前聊过"]
        if any(pattern in message for pattern in memory_patterns):
            logger.debug("[RAG DECISION] Quick filter: memory pattern -> search")
            return True

        # 明确的时间指代
        time_patterns = ["昨天我们", "上次你", "之前的", "那时候我"]
        if any(pattern in message for pattern in time_patterns):
            logger.debug("[RAG DECISION] Quick filter: time pattern -> search")
            return True

        logger.debug("[RAG DECISION] Quick filter: no match, need detailed analysis")
        return None  # 需要详细分析

    def _calculate_base_score(self, message: str) -> float:
        """计算基础分数"""
        total_score = 0.0
        logger.debug(f"[RAG DECISION] Calculating base score for: {message}")

        # 1. 关键词分析
        # 德克萨斯相关词汇
        texas_score = 0
        for category, keywords in self.texas_keywords.items():
            matches = sum(1 for keyword in keywords if keyword in message)
            if matches > 0:
                texas_score += matches * 0.1
        total_score += min(texas_score, 0.3)
        logger.debug(f"  - Texas keywords score: {min(texas_score, 0.3):.3f}")

        # 记忆相关词汇
        memory_keywords = self.texas_keywords["memories"]
        memory_score = sum(0.15 for keyword in memory_keywords if keyword in message)
        total_score += min(memory_score, 0.4)
        logger.debug(f"  - Memory keywords score: {min(memory_score, 0.4):.3f}")

        # 2. 语言模式分析
        pattern_scores = {}
        for pattern_type, patterns in self.patterns.items():
            pattern_score = 0
            for pattern in patterns:
                if re.search(pattern, message):
                    pattern_score += 0.1
            pattern_score = min(pattern_score, 0.25)
            total_score += pattern_score
            pattern_scores[pattern_type] = pattern_score
        
        logger.debug(f"  - Pattern scores: {pattern_scores}")

        # 3. 个性化分析
        personal_indicators = ["我的", "你知道我", "你了解", "对我", "我觉得", "我想要"]
        personal_score = sum(
            0.1 for indicator in personal_indicators if indicator in message
        )
        personal_score = min(personal_score, 0.25)
        total_score += personal_score
        logger.debug(f"  - Personalization score: {personal_score:.3f}")

        # 情感表达
        emotional_words = [
            "感觉",
            "觉得",
            "认为",
            "希望",
            "担心",
            "开心",
            "难过",
            "紧张",
        ]
        emotion_score = sum(0.08 for word in emotional_words if word in message)
        emotion_score = min(emotion_score, 0.2)
        total_score += emotion_score
        logger.debug(f"  - Emotion score: {emotion_score:.3f}")

        # 4. 消息复杂度
        length_score = min(len(message) / 100, 0.15)
        total_score += length_score
        logger.debug(f"  - Length score: {length_score:.3f}")

        total_score = min(total_score, 1.0)
        logger.info(f"[RAG DECISION] Base score calculated: {total_score:.3f}")
        return total_score

    def _generate_memory_spark(self, base_score: float) -> float:
        """生成记忆突发因子"""
        # 只有当基础分数不是太低或太高时才添加随机性
        if base_score < 0.1 or base_score > 0.8:
            logger.debug("[RAG DECISION] Memory spark skipped (base_score out of range)")
            return 0.0

        # 使用正态分布生成随机因子，偏向正值
        random_factor = random.gauss(0.02, 0.03)

        # 限制随机因子的范围
        random_factor = max(-0.05, min(random_factor, 0.08))
        logger.debug(f"[RAG DECISION] Generated memory spark: {random_factor:.4f}")

        return random_factor * self.random_factor_weight

    def _update_accumulation(self, current_score: float, should_search: bool):
        """更新累积分数"""
        current_time = time.time()

        prev_accumulated = self._context.accumulated_score
        prev_time = self._context.last_update_time
        
        # 计算时间衰减
        if prev_time > 0:
            time_diff = (current_time - prev_time) / 60  # 分钟
            if time_diff > self.time_decay_minutes:
                self._context.accumulated_score = 0.0
                logger.debug(f"[RAG DECISION] Accumulation reset due to time decay ({time_diff:.1f}min > {self.time_decay_minutes}min)")
            else:
                # 线性衰减
                decay_factor = 1.0 - (time_diff / self.time_decay_minutes)
                self._context.accumulated_score *= max(decay_factor, 0.0)
                logger.debug(
                    f"[RAG DECISION] Time decay applied: decay_factor={decay_factor:.3f}, "
                    f"time_diff={time_diff:.1f}min, accumulated={self._context.accumulated_score:.4f}"
                )
        else:
            logger.debug("[RAG DECISION] No previous context time, skipping decay")

        # 如果搜索了，重置累积
        if should_search:
            logger.debug("[RAG DECISION] Search triggered, resetting accumulation")
            self._context.accumulated_score = 0.0
        else:
            # 只有分数在合适范围内才累积
            if (
                current_score >= self.min_accumulation_threshold
                and current_score >= self.accumulation_threshold
                and current_score < self.search_threshold
            ):
                accumulation_boost = (current_score - self.accumulation_threshold) * 0.5
                self._context.accumulated_score += accumulation_boost
                self._context.accumulated_score = min(
                    self._context.accumulated_score, self.max_accumulation
                )
                logger.debug(
                    f"[RAG DECISION] Accumulation updated: "
                    f"boost={accumulation_boost:.4f}, "
                    f"new_accumulated={self._context.accumulated_score:.4f}"
                )
            else:
                logger.debug(
                    f"[RAG DECISION] No accumulation: "
                    f"current_score={current_score:.3f} not in accumulation range "
                    f"[{self.min_accumulation_threshold}, {self.search_threshold})"
                )

        self._context.last_update_time = current_time
        logger.info(
            f"[RAG DECISION] Context updated: accumulated_score={self._context.accumulated_score:.4f}, "
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
        logger.info(f"[RAG DECISION]接收到的信息是：{message}")

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

        # 添加记忆突发因子
        memory_spark = self._generate_memory_spark(base_score)

        # 计算当前累积加成
        current_time = time.time()
        if self._context.last_update_time > 0:
            time_diff = (current_time - self._context.last_update_time) / 60
            if time_diff <= self.time_decay_minutes:
                decay_factor = 1.0 - (time_diff / self.time_decay_minutes)
                accumulated_boost = self._context.accumulated_score * max(
                    decay_factor, 0.0
                )
            else:
                accumulated_boost = 0.0
        else:
            accumulated_boost = 0.0

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
            f"accumulated({accumulated_boost:.3f}) | "
            f"Threshold: {self.search_threshold}"
        )

        return should_search_result

    def get_debug_info(self, message: str) -> Dict:
        """
        获取调试信息（可选）

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
            }

        base_score = self._calculate_base_score(message)
        memory_spark = self._generate_memory_spark(base_score)

        current_time = time.time()
        if self._context.last_update_time > 0:
            time_diff = (current_time - self._context.last_update_time) / 60
            if time_diff <= self.time_decay_minutes:
                decay_factor = 1.0 - (time_diff / self.time_decay_minutes)
                accumulated_boost = self._context.accumulated_score * max(
                    decay_factor, 0.0
                )
            else:
                accumulated_boost = 0.0
        else:
            accumulated_boost = 0.0

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
            "context_from_redis": True,
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
            }
        except redis.RedisError as e:
            logger.error(f"[RAG DECISION] Failed to get cache info: {e}")
            return {"error": f"Failed to get cache info: {e}", "user_id": self.user_id}


def example_usage():
    """使用示例"""
    # 创建决策器（需要用户ID）
    user_id = "texas_user_001"  # 实际使用时应该是真实的用户ID
    rag_decision = RAGDecisionMaker(
        user_id=user_id,
        search_threshold=0.65,
        accumulation_threshold=0.35,
        min_accumulation_threshold=0.15,
        time_decay_minutes=10.0,
        max_accumulation=0.4,
        random_factor_weight=0.05,
        cache_ttl=3600,  # 1小时缓存
    )

    # 测试消息
    test_messages = [
        "晚上好！",
        "今天天气不错",
        "你觉得企鹅物流怎么样？",
        "那个问题你怎么看？",
        "嗯嗯",
        "德克萨斯你说呢？",
        "我记得你之前说过什么来着？",
    ]

    print("=== 精简版RAG决策器测试（Redis缓存版本）===\n")

    # 显示缓存信息
    cache_info = rag_decision.get_cache_info()
    print(f"缓存信息: {cache_info}\n")

    for i, message in enumerate(test_messages, 1):
        # 主要接口：直接获取布尔结果
        result = rag_decision.should_search(message)

        # 可选：获取调试信息
        debug_info = rag_decision.get_debug_info(message)

        print(f"消息 {i}: {message}")
        print(f"结果: {'需要搜索' if result else '不需要搜索'}")
        print(
            f"分析: 基础{debug_info['base_score']:.3f} + 突发{debug_info['memory_spark']:.3f} + 累积{debug_info['accumulated_boost']:.3f} = {debug_info['final_score']:.3f}"
        )
        print("-" * 50)

    # 显示用户统计
    stats = rag_decision.get_user_stats()
    print(f"\n用户统计信息:")
    print(f"总查询数: {stats['total_queries']}")
    print(f"搜索次数: {stats['search_count']}")
    print(f"不搜索次数: {stats['no_search_count']}")
    print(f"平均分数: {stats['avg_score']:.3f}")
    print(
        f"最后更新: {time.ctime(stats['last_updated']) if stats['last_updated'] else 'Never'}"
    )


if __name__ == "__main__":
    example_usage()
