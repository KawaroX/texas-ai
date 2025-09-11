import os
import json
import redis
from utils.logging_config import get_logger

logger = get_logger(__name__)
from typing import Dict
from datetime import datetime
import pytz
from utils.mem0_service import mem0  # 导入mem0实例


class MemoryStorage:
    def __init__(self):
        from utils.redis_manager import get_redis_client
        self.client = get_redis_client()

    def _ensure_string(self, value) -> str:
        """确保值是字符串类型"""
        if isinstance(value, str):
            return value
        elif value is None:
            return ""
        else:
            return str(value)

    def _prepare_metadata(self, metadata_dict) -> Dict[str, str]:
        """确保metadata中所有值都是字符串"""
        cleaned_metadata = {}
        for key, value in metadata_dict.items():
            if value is not None:  # 跳过None值
                cleaned_metadata[key] = self._ensure_string(value)
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

        return "\n".join(combined_parts)

    def _create_conversation_messages(self, content: str) -> list:
        """将单个内容转换为符合规范的对话格式"""
        return [
            {"role": "user", "content": f"{content}"},
        ]

    def store_memory(self, memory_data) -> bool:
        """存储记忆到Redis（24小时过期）并同步到Mem0，支持单个记忆或多个记忆列表"""
        try:
            # 如果是单个记忆项，转换为列表
            memories = (
                [memory_data] if not isinstance(memory_data, list) else memory_data
            )
            logger.info("开始处理记忆 count=%d", len(memories))

            mem0_operations_count = 0  # 计数器

            for i, memory in enumerate(memories):

                # 确保每个记忆有唯一ID
                if "id" not in memory:
                    memory_id = (
                        f"memory_{datetime.now(pytz.utc).strftime('%Y%m%d%H%M%S%f')}"
                    )
                    memory["id"] = memory_id
                else:
                    memory_id = memory["id"]

                # 获取类型和日期，用于构建新的key格式
                memory_type = memory.get("type", "unknown")
                memory_date = memory.get(
                    "date", datetime.now(pytz.utc).date().isoformat()
                )

                # 构建新的key格式：mem0:类型_日期:ID
                key = f"mem0:{memory_type}_{memory_date}"

                logger.debug("Storing memory for key: %s", key)
                serialized = json.dumps(memory, ensure_ascii=False)
                self.client.setex(key, 86400, serialized)

                # 构建Mem0的基础metadata
                base_mem0_metadata = {
                    "original_redis_id": memory_id,
                    "date": memory_date,
                    "type": memory_type,
                }

                # 添加可选字段（确保都是字符串）
                if "source_count" in memory and memory["source_count"] is not None:
                    base_mem0_metadata["source_count"] = str(memory["source_count"])
                if "importance" in memory and memory["importance"] is not None:
                    base_mem0_metadata["importance"] = str(memory["importance"])

                ai_summary_content = memory.get("content")
                content_type = type(ai_summary_content).__name__

                if isinstance(
                    ai_summary_content, list
                ):  # 例如：chat总结，是一个话题列表

                    for j, item in enumerate(ai_summary_content):

                        # 使用新的合并函数获取完整内容
                        item_content = self._combine_summary_and_details(item)

                        if item_content:

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


                            # 清理metadata，确保所有值都是字符串
                            clean_metadata = self._prepare_metadata(item_metadata)

                            # 创建符合规范的对话格式
                            messages = self._create_conversation_messages(content_str)

                            # 提交到Mem0
                            try:
                                result = mem0.add(
                                    messages=messages,
                                    metadata=clean_metadata,
                                    user_id="kawaro",
                                    infer=False,
                                )
                                mem0_operations_count += 1

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

                    # 使用新的合并函数获取完整内容
                    item_content = self._combine_summary_and_details(ai_summary_content)
                    if item_content:

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


                        # 清理metadata，确保所有值都是字符串
                        clean_metadata = self._prepare_metadata(item_metadata)

                        # 创建符合规范的对话格式
                        messages = self._create_conversation_messages(content_str)

                        # 提交到Mem0
                        logger.debug("Submitting dict content to Mem0")
                        try:
                            result = mem0.add(
                                messages=messages,
                                metadata=clean_metadata,
                                user_id="kawaro",
                                infer=False,
                            )
                            mem0_operations_count += 1
                            logger.info(
                                "[MemoryStorage] 记忆处理完成 count=%d", len(memories)
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

                    if ai_summary_content:

                        # 确保content是字符串
                        content_str = self._ensure_string(ai_summary_content)

                        # 清理metadata，确保所有值都是字符串
                        clean_metadata = self._prepare_metadata(base_mem0_metadata)

                        # 创建符合规范的对话格式
                        messages = self._create_conversation_messages(content_str)

                        # 提交到Mem0
                        logger.debug("Submitting raw content to Mem0")
                        try:
                            result = mem0.add(
                                messages=messages,
                                metadata=clean_metadata,
                                user_id="kawaro",
                                infer=False,
                            )
                            mem0_operations_count += 1

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
                        logger.warning("Raw content is empty or None")

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
