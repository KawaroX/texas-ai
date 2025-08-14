import os
import json
import redis
import logging
from typing import Dict
from datetime import datetime
import pytz
from utils.mem0_service import mem0  # 导入mem0实例

logger = logging.getLogger(__name__)


class MemoryStorage:
    def __init__(self):
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise ValueError("REDIS_URL环境变量未设置")
        self.client = redis.Redis.from_url(redis_url)
        logger.debug("[MemoryStorage] Redis client initialized with URL: %s", redis_url)

    def _ensure_string(self, value) -> str:
        """确保值是字符串类型"""
        if isinstance(value, str):
            logger.debug(
                "[MemoryStorage] Value is already string: %s",
                value[:100] if len(str(value)) > 100 else value,
            )
            return value
        elif value is None:
            logger.debug("[MemoryStorage] Converting None to empty string")
            return ""
        else:
            original_type = type(value).__name__
            converted_value = str(value)
            logger.debug(
                "[MemoryStorage] Converting %s to string: %s -> %s",
                original_type,
                str(value)[:50] if len(str(value)) > 50 else str(value),
                converted_value[:50] if len(converted_value) > 50 else converted_value,
            )
            return converted_value

    def _prepare_metadata(self, metadata_dict) -> Dict[str, str]:
        """确保metadata中所有值都是字符串"""
        logger.debug(
            "[MemoryStorage] Preparing metadata with %d fields", len(metadata_dict)
        )
        cleaned_metadata = {}
        for key, value in metadata_dict.items():
            if value is not None:  # 跳过None值
                original_value = value
                cleaned_value = self._ensure_string(value)
                cleaned_metadata[key] = cleaned_value
                logger.debug(
                    "[MemoryStorage] Metadata field '%s': %s (%s) -> %s",
                    key,
                    (
                        str(original_value)[:50]
                        if len(str(original_value)) > 50
                        else str(original_value)
                    ),
                    type(original_value).__name__,
                    cleaned_value[:50] if len(cleaned_value) > 50 else cleaned_value,
                )
            else:
                logger.debug("[MemoryStorage] Skipping None value for key: %s", key)

        logger.debug(
            "[MemoryStorage] Metadata prepared: %d fields (cleanup)",
            len(cleaned_metadata),
        )
        return cleaned_metadata

    def _combine_summary_and_details(self, item) -> str:
        """合并summary和details为完整内容"""
        summary = item.get("summary", "")
        details = item.get("details", "")

        combined_parts = []

        if summary:
            combined_parts.append(f"概要: {summary}")

        if details:
            combined_parts.append(f"详细信息: {details}")

        combined_content = "\n".join(combined_parts)

        logger.debug(
            "[MemoryStorage] Combined content from summary (%d chars) and details (%d chars) -> total: %d chars",
            len(summary) if summary else 0,
            len(details) if details else 0,
            len(combined_content),
        )

        return combined_content

    def _create_conversation_messages(self, content: str) -> list:
        """将单个内容转换为符合规范的对话格式"""
        messages = [
            {"role": "user", "content": f"{content}"},
        ]
        logger.debug(
            "[MemoryStorage] Created conversation messages with content length: %d",
            len(content),
        )
        logger.debug(
            "[MemoryStorage] Messages structure: %s",
            [
                {"role": msg["role"], "content_length": len(msg["content"])}
                for msg in messages
            ],
        )
        return messages

    def store_memory(self, memory_data) -> bool:
        """存储记忆到Redis（24小时过期）并同步到Mem0，支持单个记忆或多个记忆列表"""
        try:
            # 如果是单个记忆项，转换为列表
            memories = (
                [memory_data] if not isinstance(memory_data, list) else memory_data
            )
            logger.info("[MemoryStorage] 开始处理记忆 count=%d", len(memories))

            mem0_operations_count = 0  # 计数器

            for i, memory in enumerate(memories):
                logger.debug(
                    "[MemoryStorage] Processing memory %d/%d", i + 1, len(memories)
                )
                logger.debug(
                    "[MemoryStorage] Memory data structure: %s",
                    {
                        k: f"{type(v).__name__}({len(str(v)) if v else 0} chars)"
                        for k, v in memory.items()
                    },
                )

                # 确保每个记忆有唯一ID
                if "id" not in memory:
                    memory_id = (
                        f"memory_{datetime.now(pytz.utc).strftime('%Y%m%d%H%M%S%f')}"
                    )
                    memory["id"] = memory_id
                    logger.debug(
                        "[MemoryStorage] Generated new memory ID: %s", memory_id
                    )
                else:
                    memory_id = memory["id"]
                    logger.debug(
                        "[MemoryStorage] Using existing memory ID: %s", memory_id
                    )

                # 获取类型和日期，用于构建新的key格式
                memory_type = memory.get("type", "unknown")
                memory_date = memory.get(
                    "date", datetime.now(pytz.utc).date().isoformat()
                )
                logger.debug(
                    "[MemoryStorage] Memory type: %s, date: %s",
                    memory_type,
                    memory_date,
                )

                # 构建新的key格式：mem0:类型_日期:ID
                key = f"mem0:{memory_type}_{memory_date}"

                logger.debug("[MemoryStorage] Storing memory for key: %s", key)
                serialized = json.dumps(memory, ensure_ascii=False)
                logger.debug(
                    "[MemoryStorage] Serialized data length: %d bytes", len(serialized)
                )
                self.client.setex(key, 86400, serialized)
                logger.debug(
                    "[MemoryStorage] Successfully stored to Redis with 24h expiry"
                )

                # 构建Mem0的基础metadata
                base_mem0_metadata = {
                    "original_redis_id": memory_id,
                    "date": memory_date,
                    "type": memory_type,
                }
                logger.debug(
                    "[MemoryStorage] Base metadata created: %s", base_mem0_metadata
                )

                # 添加可选字段（确保都是字符串）
                if "source_count" in memory and memory["source_count"] is not None:
                    base_mem0_metadata["source_count"] = str(memory["source_count"])
                    logger.debug(
                        "[MemoryStorage] Added source_count to metadata: %s",
                        memory["source_count"],
                    )
                if "importance" in memory and memory["importance"] is not None:
                    base_mem0_metadata["importance"] = str(memory["importance"])
                    logger.debug(
                        "[MemoryStorage] Added importance to metadata: %s",
                        memory["importance"],
                    )

                ai_summary_content = memory.get("content")
                content_type = type(ai_summary_content).__name__
                logger.debug(
                    "[MemoryStorage] Processing content of type: %s", content_type
                )

                if isinstance(
                    ai_summary_content, list
                ):  # 例如：chat总结，是一个话题列表
                    logger.debug(
                        "[MemoryStorage] Processing list content with %d items",
                        len(ai_summary_content),
                    )

                    for j, item in enumerate(ai_summary_content):
                        logger.debug(
                            "[MemoryStorage] Processing list item %d/%d",
                            j + 1,
                            len(ai_summary_content),
                        )

                        # 使用新的合并函数获取完整内容
                        item_content = self._combine_summary_and_details(item)

                        if item_content:
                            logger.debug(
                                "[MemoryStorage] Found combined item content: %s",
                                (
                                    item_content[:100]
                                    if len(str(item_content)) > 100
                                    else str(item_content)
                                ),
                            )

                            # 确保content是字符串
                            content_str = self._ensure_string(item_content)

                        # 合并基础元数据和当前总结项的详细元数据
                        item_metadata = {**base_mem0_metadata}
                        for k, v in item.items():
                            if k not in ["summary", "details"]:  # 避免重复
                                item_metadata[k] = self._ensure_string(v)

                        # 如果item中有category字段，确保它也被包含在metadata中
                        if "category" in item:
                            item_metadata["category"] = self._ensure_string(
                                item["category"]
                            )

                            logger.debug(
                                "[MemoryStorage] Item metadata before cleanup: %d fields",
                                len(item_metadata),
                            )

                            # 清理metadata，确保所有值都是字符串
                            clean_metadata = self._prepare_metadata(item_metadata)

                            # 创建符合规范的对话格式
                            messages = self._create_conversation_messages(content_str)

                            # 提交到Mem0
                            logger.debug(
                                "[MemoryStorage] Submitting list item %d to Mem0", j + 1
                            )
                            logger.debug(
                                "[MemoryStorage] Messages to be sent to Mem0: %s",
                                messages,
                            )
                            logger.debug(
                                "[MemoryStorage] Metadata to be sent to Mem0: %s",
                                clean_metadata,
                            )
                            try:
                                logger.debug(
                                    f"[MemoryStorage] messages+metadata 预览: keys={list(clean_metadata.keys())}"
                                )
                                result = mem0.add(
                                    messages=messages,
                                    metadata=clean_metadata,
                                    user_id="kawaro",
                                    infer=False,
                                )
                                mem0_operations_count += 1
                                logger.debug(
                                    "[MemoryStorage] Successfully added list item %d to Mem0. Result: %s",
                                    j + 1,
                                    str(result)[:200] if result else "None",
                                )
                                logger.debug(
                                    "[MemoryStorage] Full result from Mem0: %s", result
                                )

                                # 验证记忆是否真的存储成功
                                try:
                                    search_result = mem0.search(
                                        query=(
                                            item_content[:50]
                                            if len(item_content) > 50
                                            else item_content
                                        ),
                                        user_id="kawaro",
                                    )
                                    logger.debug(
                                        "[MemoryStorage] Search result for verification: %s",
                                        search_result,
                                    )
                                except Exception as search_error:
                                    logger.warning(
                                        "[MemoryStorage] Failed to search for verification: %s",
                                        str(search_error),
                                    )
                            except Exception as mem0_error:
                                logger.error(
                                    "[MemoryStorage] Failed to add list item %d to Mem0: %s",
                                    j + 1,
                                    str(mem0_error),
                                )
                                logger.error(
                                    "[MemoryStorage] Full traceback: ", exc_info=True
                                )
                                raise
                        else:
                            logger.warning(
                                "[MemoryStorage] List item %d has no content (summary/details)",
                                j + 1,
                            )

                elif isinstance(ai_summary_content, dict):  # 例如：schedule或event总结
                    logger.debug(
                        "[MemoryStorage] Processing dict content with %d keys",
                        len(ai_summary_content),
                    )

                    # 使用新的合并函数获取完整内容
                    item_content = self._combine_summary_and_details(ai_summary_content)
                    if item_content:
                        logger.debug(
                            "[MemoryStorage] Found combined dict content: %s",
                            (
                                item_content[:100]
                                if len(str(item_content)) > 100
                                else str(item_content)
                            ),
                        )

                        # 确保content是字符串
                        content_str = self._ensure_string(item_content)

                        # 合并基础元数据和AI总结的详细元数据
                        item_metadata = {**base_mem0_metadata}
                        for k, v in ai_summary_content.items():
                            if k not in ["summary", "details"]:  # 避免重复
                                item_metadata[k] = self._ensure_string(v)

                        # 如果ai_summary_content中有category字段，确保它也被包含在metadata中
                        if "category" in ai_summary_content:
                            item_metadata["category"] = self._ensure_string(
                                ai_summary_content["category"]
                            )

                        logger.debug(
                            "[MemoryStorage] Dict metadata before cleanup: %d fields",
                            len(item_metadata),
                        )

                        # 清理metadata，确保所有值都是字符串
                        clean_metadata = self._prepare_metadata(item_metadata)

                        # 创建符合规范的对话格式
                        messages = self._create_conversation_messages(content_str)

                        # 提交到Mem0
                        logger.debug("[MemoryStorage] Submitting dict content to Mem0")
                        logger.debug(
                            "[MemoryStorage] Messages to be sent to Mem0: %s", messages
                        )
                        logger.debug(
                            "[MemoryStorage] Metadata to be sent to Mem0: %s",
                            clean_metadata,
                        )
                        try:
                            result = mem0.add(
                                messages=messages,
                                metadata=clean_metadata,
                                user_id="kawaro",
                                infer=False,
                            )
                            mem0_operations_count += 1
                            logger.debug(
                                "[MemoryStorage] Successfully added dict content to Mem0. Result: %s",
                                str(result)[:200] if result else "None",
                            )
            logger.info("[MemoryStorage] 记忆处理完成 count=%d", len(memories))
                            logger.debug(
                                "[MemoryStorage] Full result from Mem0: %s", result
                            )

                            # 验证记忆是否真的存储成功
                            try:
                                search_result = mem0.search(
                                    query=(
                                        item_content[:50]
                                        if len(item_content) > 50
                                        else item_content
                                    ),
                                    user_id="kawaro",
                                )
                                logger.debug(
                                    "[MemoryStorage] Search result for verification: %s",
                                    search_result,
                                )
                            except Exception as search_error:
                                logger.warning(
                                    "[MemoryStorage] Failed to search for verification: %s",
                                    str(search_error),
                                )
                        except Exception as mem0_error:
                            logger.error(
                                "[MemoryStorage] Failed to add dict content to Mem0: %s",
                                str(mem0_error),
                            )
                            logger.error(
                                "[MemoryStorage] Full traceback: ", exc_info=True
                            )
                            raise
                    else:
                        logger.warning(
                            "[MemoryStorage] Dict content has no summary/details"
                        )

                else:  # 其他情况，直接使用原始content
                    logger.debug(
                        "[MemoryStorage] Processing raw content of type: %s",
                        content_type,
                    )

                    if ai_summary_content:
                        logger.debug(
                            "[MemoryStorage] Raw content: %s",
                            (
                                str(ai_summary_content)[:100]
                                if len(str(ai_summary_content)) > 100
                                else str(ai_summary_content)
                            ),
                        )

                        # 确保content是字符串
                        content_str = self._ensure_string(ai_summary_content)

                        # 清理metadata，确保所有值都是字符串
                        clean_metadata = self._prepare_metadata(base_mem0_metadata)

                        # 创建符合规范的对话格式
                        messages = self._create_conversation_messages(content_str)

                        # 提交到Mem0
                        logger.debug("[MemoryStorage] Submitting raw content to Mem0")
                        logger.debug(
                            "[MemoryStorage] Messages to be sent to Mem0: %s", messages
                        )
                        logger.debug(
                            "[MemoryStorage] Metadata to be sent to Mem0: %s",
                            clean_metadata,
                        )
                        try:
                            result = mem0.add(
                                messages=messages,
                                metadata=clean_metadata,
                                user_id="kawaro",
                                infer=False,
                            )
                            mem0_operations_count += 1
                            logger.debug(
                                "[MemoryStorage] Successfully added raw content to Mem0. Result: %s",
                                str(result)[:200] if result else "None",
                            )
                            logger.debug(
                                "[MemoryStorage] Full result from Mem0: %s", result
                            )

                            # 验证记忆是否真的存储成功
                            try:
                                search_result = mem0.search(
                                    query=(
                                        content_str[:50]
                                        if len(content_str) > 50
                                        else content_str
                                    ),
                                    user_id="kawaro",
                                )
                                logger.debug(
                                    "[MemoryStorage] Search result for verification: %s",
                                    search_result,
                                )
                            except Exception as search_error:
                                logger.warning(
                                    "[MemoryStorage] Failed to search for verification: %s",
                                    str(search_error),
                                )
                        except Exception as mem0_error:
                            logger.error(
                                "[MemoryStorage] Failed to add raw content to Mem0: %s",
                                str(mem0_error),
                            )
                            logger.error(
                                "[MemoryStorage] Full traceback: ", exc_info=True
                            )
                            raise
                    else:
                        logger.warning("[MemoryStorage] Raw content is empty or None")

            logger.info(
                "[MemoryStorage] Processing completed: %d memories processed, %d operations sent to Mem0",
                len(memories),
                mem0_operations_count,
            )

            return True
        except Exception as e:
            logger.error(
                "[MemoryStorage] Failed to store memory: %s", str(e), exc_info=True
            )
            raise RuntimeError(f"记忆存储失败: {str(e)}")
