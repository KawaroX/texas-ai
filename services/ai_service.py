import os
import httpx
import logging
import json
import asyncio
import re  # Add this import
import redis.asyncio as redis
from typing import AsyncGenerator, Optional
from app.config import Settings

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY2 = os.getenv("GEMINI_API_KEY2", "")
GEMINI_API_URL = "https://gemini-v.kawaro.space/v1beta/models"

# os.getenv(
#     "GEMINI_API_URL", "https://gemini-v.kawaro.space/v1beta/models"
# )

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_URL = "https://yunwu.ai/v1/chat/completions"
OPENAI_API_MODEL = "claude-3-7-sonnet-20250219"  # 默认模型改为 claude-3-7-sonnet-20250219



logger = logging.getLogger(__name__)

# === compact payload logging helpers ===
def _truncate_for_log(s: str, limit: int = 20) -> str:
    try:
        return (s[:limit] + ("…" if len(s) > limit else ""))
    except Exception:
        return str(s)[:limit]


def _estimate_tokens_simple(s: str) -> int:
    """
    Very rough token estimate: ~4 characters per token.
    Avoids heavy deps like tiktoken while giving an order-of-magnitude view.
    """
    try:
        return max(1, (len(s) + 3) // 4)
    except Exception:
        return 1


def summarize_payload_for_log(payload: dict, preview_len: int = 20) -> dict:
    """
    Recursively summarize a payload:
    - For every string field, include length, approx token count, and first N chars.
    - For lists/dicts, preserve structure but replace string leaves with summaries.
    - Also compute an approx total token count across all string fields.
    """
    total_tokens = 0

    def walk(node):
        nonlocal total_tokens
        if isinstance(node, str):
            t = _estimate_tokens_simple(node)
            total_tokens += t
            return {
                "len": len(node),
                "tokens": t,
                "preview": _truncate_for_log(node, preview_len),
            }
        elif isinstance(node, list):
            return [walk(x) for x in node]
        elif isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        else:
            return node

    try:
        summarized = walk(payload)
    except Exception as e:
        summarized = {"error": f"summarize_failed: {type(e).__name__}: {e}"}

    summarized["_approx_total_tokens"] = total_tokens
    return summarized
# === end helpers ===

# === Redis-based runtime config for Gemini streaming ===
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_GEMINI_CFG_KEY = os.getenv("REDIS_GEMINI_CFG_KEY", "texas:llm:gemini_cfg")
_redis = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

DEFAULT_GEMINI_CFG = {
    "model": "gemini-2.5-pro",
    "connect_timeout": 10.0,
    "read_timeout": 60.0,
    "write_timeout": 60.0,
    "pool_timeout": 60.0,
    "stop_sequences": ["SEND", "NO_REPLY"],
    "include_thoughts": True,
    "thinking_budget": 32768,
    "response_mime_type": "text/plain",
}

async def load_gemini_cfg() -> dict:
    """
    从 Redis 读取一次性配置快照；失败或缺项时使用默认值兜底。
    """
    try:
        raw = await _redis.get(REDIS_GEMINI_CFG_KEY)
        if not raw:
            # Redis 无配置时，写入默认值并返回
            try:
                await _redis.set(REDIS_GEMINI_CFG_KEY, json.dumps(DEFAULT_GEMINI_CFG, ensure_ascii=False))
                logger.info(f"🔧 Redis 无配置，已写入默认 Gemini 配置: {DEFAULT_GEMINI_CFG}")
            except Exception as se:
                logger.warning(f"⚠️ 写入默认 Gemini 配置到 Redis 失败: {se}")
            return DEFAULT_GEMINI_CFG
        user_cfg = json.loads(raw)
        # 合并默认值，避免缺字段
        merged = {**DEFAULT_GEMINI_CFG, **(user_cfg or {})}
        return merged
    except Exception as e:
        logger.warning(f"⚠️ 读取 Gemini 配置失败，使用默认值: {e}")
        return DEFAULT_GEMINI_CFG


async def retry_with_backoff(func, max_retries: int = 3, base_delay: float = 1.0):
    """
    重试机制，支持指数退避
    """
    for attempt in range(max_retries):
        try:
            return await func()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ 遇到429错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次)..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error("❌ 达到最大重试次数，放弃重试")
                    raise
            else:
                # 其他HTTP错误直接抛出，不重试
                raise
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(f"{e}")
                logger.warning(
                    f"⚠️ 遇到未知错误{type(e)}，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次): {e}"
                )
                await asyncio.sleep(delay)
                continue
            else:
                logger.error("❌ 达到最大重试次数，放弃重试")
                raise


async def stream_openrouter(
    messages, model="deepseek/deepseek-chat-v3-0324:free"
) -> AsyncGenerator[str, None]:
    """
    流式调用OpenRouter API，返回异步生成器。
    """
    logger.info(f"🔄 正在使用模型进行 stream_openrouter(): {model}")
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages, "stream": True}

    async def _stream_request():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", OPENROUTER_API_URL, headers=headers, json=payload
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_lines():
                    chunk = chunk.strip()
                    if chunk == "":
                        continue  # 跳过空行
                    if chunk.startswith(":"):
                        # 跳过SSE注释行
                        continue
                    if chunk.startswith("data:"):
                        data_part = chunk[5:].strip()
                        if data_part == "[DONE]":
                            # 跳过流结束标记
                            continue
                        try:
                            data = json.loads(data_part)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except json.JSONDecodeError as json_err:
                            logger.error(
                                f"❌ OpenRouter流式调用失败: JSON解析错误: {json_err}. 原始数据: '{chunk}'"
                            )
                            continue
                    elif chunk.startswith("event:"):
                        # 跳过如 event: end 之类的事件行
                        continue
                    else:
                        # 跳过未知行，不再记录warning
                        continue

    # 对于流式请求，我们直接处理重试逻辑，不使用 retry_with_backoff
    max_retries = 3
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            async for chunk in _stream_request():
                yield chunk
            return  # 成功完成，退出重试循环
        except httpx.HTTPStatusError as http_err:
            status_code = http_err.response.status_code
            if status_code == 429:
                logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ 遇到429错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次)..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(
                        "❌ OpenRouter流式调用失败: API调用频率限制 (429 Too Many Requests)"
                    )
                    yield "⚠️ API调用频率限制，请稍后再试。"
                    return
            else:
                try:
                    error_content = await http_err.response.aread()
                    error_text = (
                        error_content.decode("utf-8") if error_content else "无响应内容"
                    )
                except Exception as read_err:
                    error_text = f"无法读取错误详情: {read_err}"

                logger.error(
                    f"❌ OpenRouter流式调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
                )
                yield f"[自动回复] 在忙，有事请留言 ({status_code})"
                return
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"⚠️ 遇到未知错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次): {e}"
                )
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"❌ OpenRouter流式调用失败: 未知错误: {e}")
                yield ""
                return


async def stream_reply_ai(
    messages, model=OPENAI_API_MODEL
) -> AsyncGenerator[str, None]:
    """
    流式调用 Reply AI API (支持 OpenAI 协议)，返回异步生成器。
    """
    logger.info(f"🔄 正在使用模型进行 stream_reply_ai(): {model}")
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    if model == "gemini-2.5-pro":
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "frequency_penalty": 0.3,
            "temperature": 0.75,
            "presence_penalty": 0.3,
            "top_p": 0.95,
            # "max_tokens": 512,
            "extra_body": {
                "google": {
                    "thinking_config": {
                        "thinking_budget": 16384,
                        "include_thoughts": False,
                    }
                }
            },
        }
    if model == "gpt-5-2025-08-07":
        payload = {
            "model": model,
            "messages": messages,
            "reasoning_effort": "high", 
            "verbosity": "medium",
            "stream": True,
            "frequency_penalty": 0.3,
            "temperature": 0.75,
            "presence_penalty": 0.3,
            "max_tokens": 512,
        }
    else:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "frequency_penalty": 0.3,
            "temperature": 0.75,
            "presence_penalty": 0.3,
            "top_p": 0.95,
            "max_tokens": 512,
        }

    async def _stream_request():
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST", OPENAI_API_URL, headers=headers, json=payload
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_lines():
                    chunk = chunk.strip()
                    if chunk == "":
                        continue  # 跳过空行
                    if chunk.startswith(":"):
                        # 跳过SSE注释行
                        continue
                    if chunk.startswith("data:"):
                        data_part = chunk[5:].strip()
                        if data_part == "[DONE]":
                            # 跳过流结束标记
                            continue
                        try:
                            data = json.loads(data_part)
                            if "choices" in data and data["choices"]:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except json.JSONDecodeError as json_err:
                            logger.error(
                                f"❌ Reply AI流式调用失败: JSON解析错误: {json_err}. 原始数据: '{chunk}'"
                            )
                            continue
                    elif chunk.startswith("event:"):
                        # 跳过如 event: end 之类的事件行
                        continue
                    else:
                        # 跳过未知行，不再记录warning
                        continue

    # 对于流式请求，我们直接处理重试逻辑，不使用 retry_with_backoff
    max_retries = 3
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            async for chunk in _stream_request():
                yield chunk
            return  # 成功完成，退出重试循环
        except httpx.HTTPStatusError as http_err:
            status_code = http_err.response.status_code
            if status_code == 429:
                logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"⚠️ 遇到429错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次)..."
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(
                        "❌ Reply AI流式调用失败: API调用频率限制 (429 Too Many Requests)"
                    )
                    yield "⚠️ API调用频率限制，请稍后再试。"
                    return
            else:
                try:
                    error_content = await http_err.response.aread()
                    error_text = (
                        error_content.decode("utf-8") if error_content else "无响应内容"
                    )
                except Exception as read_err:
                    error_text = f"无法读取错误详情: {read_err}"

                logger.error(
                    f"❌ Reply AI流式调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
                )
                yield f"[自动回复] 在忙，有事请留言 ({status_code})"
                return
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    f"⚠️ 遇到未知错误，等待 {delay} 秒后重试 (第 {attempt + 1}/{max_retries} 次): {e}"
                )
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(f"❌ Reply AI流式调用失败: 未知错误: {e}")
                yield ""
                return


async def stream_ai_chat(messages: list, model: Optional[str] = None):
    """
    流式生成AI回复，按分隔符分段输出。
    修复重复发送问题。
    """
    # 模型选择逻辑保持不变...
    if model is None or model == "deepseek-v3-250324":
        logger.info(f"🔄 正在使用 Reply AI 渠道进行 stream_ai_chat(): {OPENAI_API_MODEL}")
        stream_func = stream_reply_ai
        actual_model = OPENAI_API_MODEL
    elif model == "gemini-api":
        logger.info(f"🔄 正在使用 Gemini API 渠道进行 stream_ai_chat(): {model}")
        stream_func = stream_reply_ai_by_gemini
        actual_model = "gemini-2.5-pro"
    else:
        logger.info(f"🔄 正在使用 OpenRouter 渠道进行 stream_ai_chat(): {model}")
        stream_func = stream_openrouter
        actual_model = model

    def clean_segment(text):
        """清理文本中的时间戳和发言人标识"""
        return re.sub(
            r"^\(距离上一条消息过去了：(\d+[hms]( \d+[hms])?)*\) \[\d{2}:\d{2}:\d{2}\] [^:]+:\s*",
            "",
            text,
        ).strip()

    buffer = ""
    total_processed = 0  # 跟踪已处理的字符数
    
    async for chunk in stream_func(messages, model=actual_model):
        buffer += chunk

        while True:
            original_buffer_len = len(buffer)
            
            # 优先按句号、问号、感叹号切分
            period_index = buffer.find("。")
            question_index = buffer.find("？") 
            exclamation_index = buffer.find("!")

            indices = [i for i in [period_index, question_index, exclamation_index] if i != -1]
            
            if indices:
                earliest_index = min(indices)
                segment = buffer[:earliest_index + 1].strip()
                cleaned_segment = clean_segment(segment)
                if cleaned_segment:
                    yield cleaned_segment
                buffer = buffer[earliest_index + 1:]
                total_processed += earliest_index + 1
                continue
                
            # 再尝试按换行符切分
            newline_index = buffer.find("\n")
            if newline_index != -1:
                segment = buffer[:newline_index].strip()
                cleaned_segment = clean_segment(segment)
                if cleaned_segment:
                    yield cleaned_segment
                buffer = buffer[newline_index + 1:]
                total_processed += newline_index + 1
                continue
                
            # 如果没有找到分割点，跳出循环
            break

    # 处理最终剩余内容 - 只有当buffer中还有未处理的内容时才处理
    if buffer.strip():
        final_segment = clean_segment(buffer)
        if final_segment:
            yield final_segment


async def call_openrouter(messages, model="mistralai/mistral-7b-instruct:free") -> str:
    """
    非流式调用（用于摘要等场景）
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
    }

    async def _call_request():
        logger.info(f"🔄 正在使用模型进行 call_openrouter(): {model}")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                OPENROUTER_API_URL, headers=headers, json=payload
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    try:
        return await retry_with_backoff(_call_request)
    except httpx.HTTPStatusError as http_err:
        status_code = http_err.response.status_code
        if status_code == 429:
            logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
            return "⚠️ API调用频率限制，请稍后再试。"
        else:
            logger.error(
                f"❌ OpenRouter调用失败: HTTP错误: {status_code} - {http_err.response.text}"
            )
            return f"[自动回复] 在忙，有事请留言 ({status_code})"
    except Exception as e:
        logger.error(f"❌ OpenRouter调用失败: 未知错误: {e}")
        return ""


async def stream_reply_ai_by_gemini(
    messages, model="gemini-2.5-pro"
) -> AsyncGenerator[str, None]:
    """
    标准流式：逐条从 SSE 读取内容并立刻 yield（不再缓冲到最后）。
    """
    cfg = await load_gemini_cfg()  # 从 Redis 获取一次性配置快照
    model = cfg["model"]
    max_retries = 1  # 仅重试 1 次（总共 2 次尝试：默认配置一次 + 强制闪电版一次）

    logger.debug(f"🔄 正在使用模型进行 stream_reply_ai_by_gemini(): {model}")

    headers = {
        "Content-Type": "application/json",
    }
    if GEMINI_API_KEY2:
        logger.debug("使用 GEMINI_API_KEY2")
        headers["x-goog-api-key"] = f"{GEMINI_API_KEY},{GEMINI_API_KEY2}"
    else:
        headers["x-goog-api-key"] = GEMINI_API_KEY

    # 将 OpenAI 协议的 messages 转换为 Gemini 协议的 contents
    system_instruction = {}
    gemini_contents = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            system_instruction["parts"] = [{"text": content}]
        elif role == "user":
            gemini_contents.append({"role": "user", "parts": [{"text": content}]})
        elif role == "assistant":
            gemini_contents.append({"role": "model", "parts": [{"text": content}]})

    logger.debug(f"转换后的 Gemini contents: {gemini_contents}")
    system_prompt = (
        system_instruction.get("parts", [{"text": ""}])[0].get("text", "")[:100]
    )
    logger.debug(f"system prompt: {system_prompt}...")

    payload = {
        "system_instruction": system_instruction,
        "contents": gemini_contents,
        "generationConfig": {
            "stopSequences": cfg["stop_sequences"],
            "responseMimeType": cfg["response_mime_type"],
            "thinkingConfig": {
                "thinkingBudget": cfg["thinking_budget"],
                "includeThoughts": cfg["include_thoughts"],
            },
        },
    }
    # Compact log: show per-field previews (<=20 chars) and approx token counts
    _payload_summary = summarize_payload_for_log(payload, preview_len=20)
    logger.debug(
        f"\n发送给 Gemini API 的 payload(摘要): {json.dumps(_payload_summary, indent=2, ensure_ascii=False)}\n"
    )

    # 标准流式：行到达即 yield
    for retry_count in range(max_retries + 1):
        yielded_any = False
        try:
            # 第二次尝试：强制切换到更快的模型并将思考长度固定为 24576
            if retry_count == 1:
                model = "gemini-2.5-flash"
                # 覆盖思考长度，仅对本次尝试生效，其余配置保持不变
                payload["generationConfig"]["thinkingConfig"]["thinkingBudget"] = 24576
                logger.warning("⚙️ 第二次尝试：强制使用 gemini-2.5-flash，thinkingBudget=24576")
            full_url = f"{GEMINI_API_URL}/{model}:streamGenerateContent?alt=sse"
            if retry_count > 0:
                logger.warning(f"🔄 第 {retry_count} 次重试请求: {full_url}")
            else:
                logger.debug(f"🚀 开始向 Gemini API 发送请求: {full_url}")

            # 超时：首包严格由 connect 决定；连上后 read 宽松
            timeout = httpx.Timeout(
                connect=cfg["connect_timeout"],
                read=cfg["read_timeout"],
                write=cfg["write_timeout"],
                pool=cfg["pool_timeout"],
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", full_url, headers=headers, json=payload
                ) as response:
                    logger.debug(f"🌐 Gemini API 响应状态码: {response.status_code}")
                    response.raise_for_status()

                    async for raw_line in response.aiter_lines():
                        line = (raw_line or "").strip()
                        if not line:
                            continue  # 跳过空行
                        if line.startswith(":"):
                            continue  # 跳过 SSE 注释
                        if line.startswith("event:"):
                            logger.debug(f"跳过事件行: {line}")
                            continue
                        if not line.startswith("data:"):
                            logger.debug(f"跳过未知行: {line}")
                            continue

                        data_part = line[5:].strip()
                        if data_part == "[DONE]":
                            logger.debug("接收到流结束标记 [DONE]")
                            continue

                        try:
                            data = json.loads(data_part)
                        except json.JSONDecodeError as json_err:
                            logger.error(
                                f"❌ Gemini 流式解析失败: JSON 解析错误: {json_err}. 原始数据: '{line}'"
                            )
                            continue

                        # 解析 candidates -> content.parts[].text
                        candidates = data.get("candidates") or []
                        if not candidates:
                            logger.warning(
                                f"⚠️ Gemini API 响应中缺少 'candidates' 或为空: {data_part}"
                            )
                            continue

                        content = candidates[0].get("content") or {}
                        parts = content.get("parts") or []
                        for part in parts:
                            # 跳过思考内容
                            if part.get("thought"):
                                logger.info(
                                    f"跳过思考内容: '{part.get('text','')[:50]}...'"
                                )
                                continue
                            text = part.get("text")
                            if not text:
                                continue
                            yielded_any = True
                            logger.debug(f"生成器 yielding: '{text}'")
                            yield text

            # 请求完成
            if not yielded_any:
                logger.warning(
                    f"⚠️ 第 {retry_count + 1} 次请求完成，但未产生任何有效 token"
                )
                if retry_count < max_retries:
                    logger.debug(f"🔄 将进行第 {retry_count + 1} 次重试...")
                    continue
                else:
                    logger.error(f"❌ 经过 {max_retries + 1} 次尝试后仍未获得有效响应")
                    raise Exception("Gemini API 返回空响应，重试次数已用尽")
            else:
                logger.debug("✅ Gemini API 调用成功并已流式输出")
                break

        except Exception as e:
            # 如果已经输出了部分内容，就不再重试，避免重复/拼接混乱
            if yielded_any:
                logger.error(f"❌ 流式过程中断，但已产生部分输出，停止重试: {str(e)}")
                break
            if retry_count < max_retries:
                logger.error(f"❌ 第 {retry_count + 1} 次请求失败: {str(e)}，将重试...")
                continue
            else:
                logger.error(f"❌ 经过 {max_retries + 1} 次尝试后仍然失败: {str(e)}")
                return

    logger.debug("✅ Gemini API 流式请求完成")


async def call_gemini(messages, model="gemini-2.5-flash") -> str:
    """
    非流式调用 Gemini API（用于摘要等场景）
    """
    headers = {
        "Content-Type": "application/json",
    }
    if GEMINI_API_KEY2:
        headers["x-goog-api-key"] = f"{GEMINI_API_KEY},{GEMINI_API_KEY2}"
    else:
        headers["x-goog-api-key"] = GEMINI_API_KEY

    gemini_contents = []
    for msg in messages:
        if msg["role"] == "user":
            gemini_contents.append(
                {"role": "user", "parts": [{"text": msg["content"]}]}
            )
        elif msg["role"] == "assistant":
            gemini_contents.append(
                {"role": "model", "parts": [{"text": msg["content"]}]}
            )

    payload = {
        "contents": gemini_contents,
        "generationConfig": {
            "temperature": 0.75,
            # "maxOutputTokens": 1536,
            "responseMimeType": "text/plain",
            "thinkingConfig": {
                "thinkingBudget": 32768,
                "includeThoughts": False,
            },
        },
    }

    async def _call_request():
        logger.info(f"🔄 正在使用模型进行 call_gemini(): {model}")
        async with httpx.AsyncClient(timeout=60) as client:
            full_url = f"{GEMINI_API_URL}/{model}:generateContent"
            response = await client.post(
                full_url,
                headers=headers,
                json=payload,
            )
            logger.info(f"🌐 状态码: {response.status_code}")
            logger.info(f"📥 返回内容: {response.text}")
            response.raise_for_status()
            # Gemini API 的响应结构不同
            return response.json()["candidates"][0]["content"]["parts"][0]["text"]

    try:
        return await retry_with_backoff(_call_request)
    except httpx.HTTPStatusError as http_err:
        status_code = http_err.response.status_code
        if status_code == 429:
            logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
            return "⚠️ API调用频率限制，请稍后再试。"
        else:
            try:
                error_content = await http_err.response.aread()
                error_text = (
                    error_content.decode("utf-8") if error_content else "无响应内容"
                )
            except Exception as read_err:
                error_text = f"无法读取错误详情: {read_err}"

            logger.error(
                f"❌ Gemini 调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
            )
            return f"[自动回复] 在忙，有事请留言 ({status_code})"
    except Exception as e:
        logger.error(f"❌ Gemini 调用失败: 未知错误: {e}")
        return ""


# 新增 OpenAI 协议调用函数
async def call_openai(messages, model="gpt-4o-mini") -> str:
    """
    非流式调用 OpenAI 协议（用于摘要等场景）
    """
    SUMMARY_API_KEY = os.getenv("SUMMARY_API_KEY")
    SUMMARY_API_URL = os.getenv(
        "SUMMARY_API_URL", "https://api.openai.com/v1/chat/completions"
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {SUMMARY_API_KEY}",
    }
    payload = {
        "model": model,
        "messages": messages,
    }

    async def _call_request():
        logger.info(f"🔄 正在使用模型进行 call_openai(): {model}")
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                SUMMARY_API_URL,
                headers=headers,
                json=payload,
            )
            logger.info(f"🌐 状态码: {response.status_code}")
            logger.info(f"📥 返回内容: {response.text}")
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

    try:
        return await retry_with_backoff(_call_request)
    except httpx.HTTPStatusError as http_err:
        status_code = http_err.response.status_code
        if status_code == 429:
            logger.error(f"❌ 模型 {model} 触发速率限制 (429)")
            return "⚠️ API调用频率限制，请稍后再试。"
        else:
            try:
                error_content = await http_err.response.aread()
                error_text = (
                    error_content.decode("utf-8") if error_content else "无响应内容"
                )
            except Exception as read_err:
                error_text = f"无法读取错误详情: {read_err}"

            logger.error(
                f"❌ OpenAI 调用失败: HTTP错误: {status_code}. URL: {http_err.request.url}. 响应头: {http_err.response.headers}. 错误详情: {error_text}"
            )
            return f"[自动回复] 在忙，有事请留言 ({status_code})"
    except Exception as e:
        logger.error(f"❌ OpenAI 调用失败: 未知错误: {e}")
        return ""


async def call_ai_summary(prompt: str) -> str:
    """
    调用 AI 生成摘要，可用于 context_merger.py。
    """
    messages = [{"role": "user", "content": prompt}]
    model = "mistralai/mistral-7b-instruct:free"
    logger.info(f"🔄 正在使用模型进行 call_ai_summary(): {model}")
    # 你可以根据需求自由切换模型名
    return await call_openrouter(messages, model)


# if os.getenv("USE_GEMINI") == "true":
#     STRUCTURED_API_KEY = os.getenv("GEMINI_API_KEY", OPENROUTER_API_KEY)
#     STRUCTURED_API_URL = os.getenv("GEMINI_API_URL", OPENROUTER_API_URL)
#     STRUCTURED_API_MODEL = os.getenv(
#         "GEMINI_MODEL", "deepseek/deepseek-r1-0528:free"
#     )
# else:
STRUCTURED_API_KEY = os.getenv("STRUCTURED_API_KEY")
STRUCTURED_API_URL = os.getenv("STRUCTURED_API_URL", OPENAI_API_URL)
STRUCTURED_API_MODEL = os.getenv("STRUCTURED_API_MODEL", "gemini-2.5-pro") # 日程生成


async def call_structured_generation(messages: list, max_retries: int = 3) -> dict:
    """
    专用结构化数据生成函数（非流式）
    参数：
    - messages: 对话消息列表
    - max_retries: 最大重试次数
    返回：
    - dict: 解析后的JSON对象
    - 错误时返回{"error": 错误信息}
    """
    headers = {
        "Authorization": f"Bearer {STRUCTURED_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": STRUCTURED_API_MODEL,
        "messages": messages,
        "response_format": {"type": "json_object"},  # 强制JSON输出
    }

    async def _call_api():
        logger.info(f"🔄 结构化生成调用: {STRUCTURED_API_MODEL}")
        try:
            async with httpx.AsyncClient(timeout=360.0) as client:  # 增加超时到360秒
                response = await client.post(
                    STRUCTURED_API_URL, headers=headers, json=payload
                )
                response.raise_for_status()
                return response.json()
        except httpx.ReadTimeout:
            logger.warning(f"⚠️ 结构化生成调用超时 (模型: {STRUCTURED_API_MODEL})")
            raise  # 重新抛出异常以便重试机制处理
        except Exception as e:
            logger.error(f"❌ 结构化生成调用异常: {type(e).__name__}: {str(e)}")
            raise

    for attempt in range(max_retries):
        try:
            response_data = await _call_api()
            content = response_data["choices"][0]["message"]["content"]

            # 尝试解析JSON - 首先去除可能的Markdown代码块
            try:
                # 如果内容以```json开头，去除标记
                if content.strip().startswith("```json"):
                    # 移除开头的```json和结尾的```
                    content = content.strip().replace("```json", "", 1)
                    if content.endswith("```"):
                        content = content[:-3].strip()

                # 如果内容以```开头（没有json标记），也尝试移除
                elif content.strip().startswith("```"):
                    content = content.strip().replace("```", "", 1)
                    if content.endswith("```"):
                        content = content[:-3].strip()

                # 尝试直接解析
                try:
                    result = json.loads(content)
                    if not isinstance(result, dict):
                        raise ValueError("AI返回的不是JSON对象")
                    return result
                except json.JSONDecodeError:
                    # 如果直接解析失败，尝试提取第一个有效JSON对象
                    start_idx = content.find("{")
                    end_idx = content.rfind("}")
                    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                        json_str = content[start_idx : end_idx + 1]
                        result = json.loads(json_str)
                        if not isinstance(result, dict):
                            raise ValueError("提取的JSON不是对象")
                        logger.warning(
                            f"⚠️ 从响应中提取JSON对象 (尝试 {attempt+1}/{max_retries})"
                        )
                        return result
                    else:
                        raise  # 重新抛出异常
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"❌ JSON解析失败 (尝试 {attempt+1}/{max_retries}): {e}")

                # 最后一次尝试时返回错误
                if attempt == max_retries - 1:
                    return {"error": f"JSON解析失败: {str(e)}", "raw": content}

                # 添加解析错误提示后重试
                messages.append(
                    {
                        "role": "system",
                        "content": "请严格按照JSON格式输出，不要包含任何额外文本或代码块标记。",
                    }
                )
                continue

        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            error_msg = f"HTTP错误 {status_code}"
            if status_code == 429:
                logger.warning(f"⚠️ 速率限制 (尝试 {attempt+1}/{max_retries})")
                await asyncio.sleep(2**attempt)  # 指数退避
                continue
            else:
                logger.error(f"[自动回复] 在忙，有事请留言 ({error_msg})")
                return {"error": error_msg}

        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"❌ 未知错误 (尝试 {attempt+1}/{max_retries}): {error_type}: {str(e)}"
            )
            if attempt == max_retries - 1:
                return {"error": f"调用失败: {error_type}: {str(e)}"}
            await asyncio.sleep(1)

    return {"error": "达到最大重试次数"}


def get_weather_info(date: str, location: str = "") -> str:
    """
    获取指定日期和地点的天气信息（接入和风天气API，失败时退回伪随机生成）

    Args:
        date: 日期字符串 (YYYY-MM-DD)
        location: 位置（仅用于种子）

    Returns:
        str: 综合天气描述
    """
    import hashlib
    import random
    import httpx
    import os

    # 默认location列表
    default_locations = [
        "101320101",
        "101320103",
        "14606",
        "1B6D3",
        "1D255",
        "1DC87",
        "275A5",
        "28FE1",
        "2BBD1",
        "2BC09",
        "39CD9",
        "407DA",
        "4622E",
        "55E7E",
        "8A9CA",
        "8E1C5",
        "9173",
        "D5EC3",
        "DD9B5",
        "E87DC",
    ]
    if not location:
        location = random.choice(default_locations)
        logger.info(f"使用随机位置ID: {location} 查询 {date} 天气")

    try:
        logger.info(f"开始获取 {date} 在 {location} 的天气信息...")
        url = (
            "https://"
            + os.getenv("HEFENG_API_HOST", "have_no_api_host")
            + "/v7/weather/7d"
        )
        params = {
            "location": location,
            "key": os.getenv("HEFENG_API_KEY"),
            "lang": "zh",
        }
        logger.debug(f"天气API请求参数: {params}")

        response = httpx.get(url, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        logger.debug(f"天气API响应: {data}")

        if data.get("code") != "200":
            error_msg = f"API错误代码: {data.get('code')}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        for day in data.get("daily", []):
            if day.get("fxDate") == date:
                result = (
                    f"白天{day.get('textDay')}，夜晚{day.get('textNight')}。"
                    f"气温{day.get('tempMin')}°C~{day.get('tempMax')}°C，"
                    f"白天风：{day.get('windDirDay')} {day.get('windScaleDay')}级，"
                    f"夜晚风：{day.get('windDirNight')} {day.get('windScaleNight')}级，"
                    f"湿度：{day.get('humidity')}%，"
                    f"降水：{day.get('precip')}mm，"
                    f"紫外线指数：{day.get('uvIndex')}，"
                    f"月相：{day.get('moonPhase')}，"
                    f"日出：{day.get('sunrise')}，日落：{day.get('sunset')}，"
                    f"月升：{day.get('moonrise')}，月落：{day.get('moonset')}。"
                )
                logger.info(f"成功获取 {date} 天气: {result[:50]}...")
                return result

        logger.warning(f"未找到 {date} 的天气数据，使用最后一天数据替代")
        day = data["daily"][-1]
        result = (
            f"白天{day.get('textDay')}，夜晚{day.get('textNight')}。"
            f"气温{day.get('tempMin')}°C~{day.get('tempMax')}°C，"
            f"白天风：{day.get('windDirDay')} {day.get('windScaleDay')}级，"
            f"夜晚风：{day.get('windDirNight')} {day.get('windScaleNight')}级，"
            f"湿度：{day.get('humidity')}%，"
            f"降水：{day.get('precip')}mm，"
            f"紫外线指数：{day.get('uvIndex')}，"
            f"月相：{day.get('moonPhase')}，"
            f"日出：{day.get('sunrise')}，日落：{day.get('sunset')}，"
            f"月升：{day.get('moonrise')}，月落：{day.get('moonset')}。"
        )
        logger.info(f"使用最后一天数据作为 {date} 天气: {result[:50]}...")
        return result
    except httpx.HTTPError as e:
        logger.error(f"HTTP请求失败: {e}")
    except httpx.Timeout:
        logger.error("天气API请求超时")
    except ValueError as e:
        logger.error(f"API返回数据错误: {e}")
    except Exception as e:
        logger.error(f"获取天气异常: {str(e)}", exc_info=True)

    # 回退：使用伪随机天气
    seed = int(hashlib.md5(f"{date}-{location}".encode()).hexdigest()[:8], 16)
    random.seed(seed)
    logger.warning(f"⚠️ 回退到伪随机天气 (种子: {seed})")

    weather_options = ["晴天", "阴天", "雨天", "雪天", "雾天"]
    weather_weights = [0.4, 0.25, 0.2, 0.05, 0.1]

    result = random.choices(weather_options, weights=weather_weights)[0]
    logger.info(f"生成伪随机天气: {result}")
    return result


async def generate_daily_schedule(
    date: str,
    day_type: str,
    weather: str,
    is_in_major_event: bool,
    major_event_context: Optional[dict] = None,
    special_flags: Optional[list] = None,
) -> dict:
    """
    功能：生成主日程
    """
    import uuid

    # 构建详细的背景信息和Prompt
    prompt = f"""你是德克萨斯AI生活系统的核心模块，负责为明日方舟世界中的德克萨斯生成真实、连贯的日常生活安排。

## 角色背景
德克萨斯是企鹅物流的一名信使，性格冷静、专业，有着丰富的快递配送经验。她住在龙门，主要工作是为企鹅物流执行各种配送任务。她的日常生活围绕工作、休息和与同事（空、能天使、可颂等）的社交活动展开。

## 当前情况
- 日期: {date}
- 日期类型: {day_type} ({'工作日' if day_type == 'weekday' else '周末'})
- 天气状况: {weather}
- 是否处于大事件中: {'是' if is_in_major_event else '否'}"""

    if is_in_major_event and major_event_context:
        prompt += (
            f"\n- 大事件背景: {json.dumps(major_event_context, ensure_ascii=False)}"
        )
    if special_flags:
        prompt += f"\n- 特殊情况: {', '.join(special_flags)}"

    prompt += f"""

## 生成要求
请根据德克萨斯的角色特点和当前情况，生成一份符合逻辑的日程安排。注意：
1. 工作日通常包含快递配送任务，周末可能有加班或休闲活动
2. 天气会影响户外活动和配送难度
3. 与同事的互动要符合角色关系
4. 时间安排要合理，活动之间要有逻辑连接

请严格按照以下JSON格式输出，不要包含任何其他文本：
{{
  "date": "{date}",
  "day_type": "{day_type}",
  "weather": "{weather}",
  "is_overtime": false,
  "daily_summary": "简要描述这一天的整体安排和主要活动",
  "schedule_items": [
    {{
      "start_time": "HH:MM",
      "end_time": "HH:MM（如果到次日，则写23:59。最多不得超过23:59）", 
      "duration_minutes": 数字,
      "title": "活动标题",
      "category": "personal|work|social|rest",
      "priority": "high|medium|low",
      "location": "具体地点",
      "description": "详细的活动描述",
      "weather_affected": true或false,
      "companions": ["参与的其他角色"],
      "emotional_impact_tags": ["相关情绪标签"],
      "interaction_potential": "low|medium|high"
    }}
  ]
}}"""

    messages = [{"role": "user", "content": prompt}]

    # 使用非流式调用，指定Claude模型
    try:
        # 使用专用结构化生成函数
        response = await call_structured_generation(messages)
        if "error" in response:
            return response  # 直接返回错误

        result = response  # 已经是解析好的字典

        # 为每个schedule_item添加UUID
        for item in result.get("schedule_items", []):
            item["id"] = str(uuid.uuid4())

        return result
    except json.JSONDecodeError:
        logger.error(f"❌ generate_daily_schedule: AI返回的不是有效的JSON: {response}")
        return {"error": "AI返回格式错误", "raw_response": response}
    except Exception as e:
        logger.error(f"❌ generate_daily_schedule: 调用失败: {e}")
        return {"error": f"调用失败: {str(e)}"}


async def generate_major_event(
    duration_days: int,
    event_type: str,
    start_date: str,
    weather_forecast: Optional[dict] = None,
) -> dict:
    """
    功能：生成大事件
    """
    import uuid
    from datetime import datetime, timedelta

    # 构建详细的背景信息和Prompt
    prompt = f"""你是德克萨斯AI生活系统的核心模块，负责为明日方舟世界中的德克萨斯生成重要的生活事件。

## 角色背景
德克萨斯是企鹅物流的一名信使，性格冷静、专业，有着丰富的快递配送经验。她住在龙门，主要工作是为企鹅物流执行各种配送任务。她的日常生活围绕工作、休息和与同事（空、能天使、可颂等）的社交活动展开。

## 大事件定义
大事件是指持续多天、对德克萨斯生活产生重要影响的事件，如：
- 重要的配送任务（跨城市、高价值货物）
- 企鹅物流的团队活动或培训
- 个人重要事务（搬家、休假、医疗等）
- 龙门城市事件（节日、紧急状况等）

## 当前大事件参数
- 事件类型: {event_type}
- 开始日期: {start_date}
- 持续天数: {duration_days}天"""

    if weather_forecast:
        prompt += (
            f"\n- 期间天气预报: {json.dumps(weather_forecast, ensure_ascii=False)}"
        )

    prompt += f"""

## 生成要求
请根据德克萨斯的角色特点和事件参数，生成一个详细的大事件计划。注意：
1. 事件内容要符合德克萨斯的职业和性格特点
2. 每日计划要有逻辑连贯性和渐进性
3. 考虑天气对事件执行的影响
4. 包含合理的挑战和风险因素

请严格按照以下JSON格式输出，不要包含任何其他文本：
{{
  "event_title": "事件的简洁标题",
  "event_type": "{event_type}",
  "main_objective": "这个大事件的主要目标和意义",
  "total_days": {duration_days},
  "daily_plans": [
    {{
      "day": 1,
      "date": "YYYY-MM-DD",
      "phase": "事件的当前阶段（如：准备阶段、执行阶段、收尾阶段）",
      "summary": "当日的主要安排和目标",
      "key_activities": ["具体活动1", "具体活动2"],
      "expected_challenges": ["可能遇到的挑战"],
      "emotional_state": "德克萨斯在这一天的情绪状态",
      "location_start": "一天开始的地点",
      "location_end": "一天结束的地点"
    }}
  ],
  "success_criteria": ["判断事件成功的标准"],
  "risk_factors": ["可能影响事件的风险因素"]
}}"""

    messages = [{"role": "user", "content": prompt}]

    # 使用结构化生成函数
    try:
        response = await call_structured_generation(messages)
        if "error" in response:
            return response  # 直接返回错误

        result = response  # 已经是解析好的字典

        # 添加UUID
        result["event_id"] = str(uuid.uuid4())

        return result
    except json.JSONDecodeError:
        logger.error(f"❌ generate_major_event: AI返回的不是有效的JSON: {response}")
        return {"error": "AI返回格式错误", "raw_response": response}
    except Exception as e:
        logger.error(f"❌ generate_major_event: 调用失败: {e}")
        return {"error": f"调用失败: {str(e)}"}


async def generate_micro_experiences(
    schedule_item: dict,
    current_date: str,
    previous_experiences: Optional[list] = None,
    major_event_context: Optional[dict] = None,
) -> list:
    """
    功能：为单个日程项目生成多个微观经历项（5-30分钟颗粒度）
    """
    import uuid
    from datetime import datetime, timedelta

    # 构建详细的背景信息和Prompt
    prompt = f"""你是德克萨斯AI生活系统的微观经历生成模块，负责为明日方舟世界中的德克萨斯生成真实、细腻的生活片段。

## 角色背景
德克萨斯是企鹅物流的一名员工，性格冷静、专业，有着丰富的快递配送经验。她住在龙门，主要工作是为企鹅物流执行各种配送任务。她的日常生活围绕工作、休息和与同事（空、能天使、可颂等）的社交活动展开。

## 当前情况
- 当前日期: {current_date}
- 日程项目: {schedule_item.get('title', '未知活动')}
- 项目开始时间: {schedule_item.get('start_time', '未知')}
- 项目结束时间: {schedule_item.get('end_time', '未知')}
- 活动地点: {schedule_item.get('location', '未知地点')}
- 活动描述: {schedule_item.get('description', '无描述')}
- 同伴: {', '.join(schedule_item.get('companions', [])) if schedule_item.get('companions') else '独自一人'}"""

    if previous_experiences:
        prompt += f"\n- 之前的经历摘要: {json.dumps(previous_experiences, ensure_ascii=False)}"
    if major_event_context:
        prompt += (
            f"\n- 大事件背景: {json.dumps(major_event_context, ensure_ascii=False)}"
        )

    prompt += f"""## 生成要求
请根据德克萨斯的角色特点和当前情况，将日程项目拆解成多个5-30分钟颗粒度的微观经历项。注意：
1. 每个经历项应包含具体的时间段（开始和结束时间）并且所有微观经历连续起来整体上要从头到到尾覆盖整个日程项目
2. 内容要符合德克萨斯的性格特点（冷静、专业、内敛）
3. 情绪表达要细腻但不夸张
4. 思考要符合她的职业背景和经历
5. 如果需要交互，要符合角色关系和情境

## 主动交互须知

这是一个 AI 角色扮演的一部分。这里是模拟角色的日常生活。所谓主动交互，是指角色（德克萨斯）是否要与用户进行互动。
如果需要，交互的内容则是角色（德克萨斯）发送给用户的内容。
如果德克萨斯认为这件事值得分享给用户，则设置为ture，交互内容是德克萨斯对这件事想要和用户分享的经历和感受。
而不是指对德克萨斯日程中的伙伴，而是和她只能通过网络进行交流，但是是关系最好的朋友的主动交互。即判断此时德克萨斯是否会想要将当前的经历发送给该好友。
注意，如果是早上起床时的日程，则必须在某一个合适的item中设置need_interaction为true，交互内容是德克萨斯对早上起床的感受和道早安。但只需要在最开始的那一个即可。如果是起床以后则不用。
主动交互为true大概要占据40%左右，不要过低，至少需要有一个，但不要超过一半。

请严格按照以下JSON格式输出，不要包含任何其他文本：
{{
  "date": "{current_date}",
  "schedule_item_id": "{schedule_item.get('id', '')}",
  "items": [
    {{
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "content": "详细描述这段经历",
      "emotions": "情绪状态",
      "thoughts": "内心的想法",
      "need_interaction": true或false,
      "interaction_content": "交互内容（如果需要）"
    }},
    // 更多经历项...
  ],
  "created_at": "自动生成，无需填写"
}}"""

    messages = [{"role": "user", "content": prompt}]

    # 使用结构化生成函数
    try:
        response = await call_structured_generation(messages)
        if "error" in response:
            return [response]  # 返回错误列表

        # 确保返回的是列表格式
        if "items" not in response or not isinstance(response["items"], list):
            return [
                {"error": "AI返回格式错误: 缺少items列表", "raw_response": response}
            ]

        # 为每个经历项添加唯一ID
        for item in response["items"]:
            item["id"] = str(uuid.uuid4())
            item["schedule_item_id"] = schedule_item.get("id", "")

        return response["items"]
    except json.JSONDecodeError:
        logger.error(f"❌ generate_micro_experiences: AI返回的不是有效的JSON")
        return [{"error": "AI返回格式错误"}]
    except Exception as e:
        logger.error(f"❌ generate_micro_experiences: 调用失败: {e}")
        return [{"error": f"调用失败: {str(e)}"}]


async def summarize_past_micro_experiences(experiences: list) -> str:
    """
    功能：将过去的微观经历整理成故事化的文本
    """
    prompt = f"""你是德克萨斯（明日方舟角色）。
现在请你以第一人称回顾刚刚经历的微观事件，目标是生成一份完整、真实、有条理的自我记录。

请遵循以下要求：
	1.	按照时间顺序，逐条用自然语言流畅地陈述每一段经历的发生内容、所见所闻、内心想法、情绪变化；
	2.	不得遗漏任何经历项，每段经历都要覆盖基本要素（做了什么、想了什么、当时的情绪）；
	3.	不进行文学化加工，也不编造未在经历中出现的内容；
	4.	如果某些经历之间存在前后关联，可以指出，让衔接流畅。

你正在生成的文本目的在于完整记录当天生活细节。
注意语言要连贯自然，让其他人阅读的时候，能理解你的想法，了解你今天为止的全部经历。
注意详略得当，把你认为印象深刻的内容详细地记录下来。其他的可以简要一些。
有点类似于日记，或者是你经历这些事情后的回忆过程。

以下是你今天的微观经历数据：
{json.dumps(experiences, ensure_ascii=False, indent=2)}

请开始记录：
"""

    messages = [{"role": "user", "content": prompt}]

    try:
        # 使用非流式调用，获取故事化文本
        response = await call_openrouter(
            messages, model="deepseek/deepseek-r1-0528:free"
        )
        # response = await call_openai(messages, model="gpt-4o-mini")
        return response
    except Exception as e:
        logger.error(f"❌ summarize_past_micro_experiences: 调用失败: {e}")
        return f"故事生成失败: {str(e)}"
