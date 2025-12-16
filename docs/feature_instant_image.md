# 实时图片生成功能 - 技术设计文档

## 1. 功能概述

### 1.1 需求描述
实现一个基于对话的即时图片生成功能，能够：
- 根据用户请求即时生成图片（区别于定时批量生成）
- 基于最近对话内容（3分钟或10-25条消息）
- 复用现有的 `scene_pre_analyzer.py` 生成提示词
- 复用现有的图片生成逻辑（定时任务使用的同一套）
- 自然地融入对话流程

### 1.2 与现有系统的区别

| 特性 | 定时图片生成(现有) | 即时图片生成(新) |
|------|------------------|----------------|
| **触发时机** | 每天4:50定时 | 用户请求时 |
| **数据来源** | 微观经历(结构化) | 最近对话(非结构化) |
| **数量** | 批量(全天的30%) | 单张 |
| **场景分析** | scene_pre_analyzer | scene_pre_analyzer(复用) |
| **图片生成** | image_generation_service | image_generation_service(复用) |
| **上下文** | schedule_item + 微观经历 | 最近对话历史 |
| **存储** | 映射到interaction_id | 直接发送到频道 |

### 1.3 核心价值
- **即时性**：用户想看就能立即生成
- **互动性**：增强AI与用户的互动体验
- **场景丰富**：可以拍摄任何聊到的场景
- **复用性**：最大化利用现有基础设施

---

## 2. 系统架构

### 2.1 整体流程图

```
┌──────────────┐
│ 用户请求     │ ("拍张照"、"发个照片")
└──────┬───────┘
       │
       v
┌──────────────────────────┐
│ 意图识别                  │
│ (关键词/AI判断)           │
└──────┬───────────────────┘
       │
       v
┌──────────────────────────┐
│ 提取最近对话上下文         │
│ - Redis buffer (优先)     │
│ - PostgreSQL (备用)       │
│ - 3分钟或10-25条消息      │
└──────┬───────────────────┘
       │
       v
┌──────────────────────────┐
│ 构建场景数据              │
│ - 格式化对话为场景描述     │
│ - 添加时间地点上下文       │
└──────┬───────────────────┘
       │
       v
┌──────────────────────────┐
│ AI场景预分析              │
│ (scene_pre_analyzer.py)  │
│ - 判断selfie/scene       │
│ - 生成增强提示词          │
└──────┬───────────────────┘
       │
       v
┌──────────────────────────┐
│ 图片生成                  │
│ (image_generation_service)│
└──────┬───────────────────┘
       │
       v
┌──────────────────────────┐
│ 上传并发送到频道          │
│ (MattermostWebSocketClient)│
└──────────────────────────┘
```

### 2.2 核心组件

#### 2.2.1 新增组件
- **InstantImageTrigger**: 触发器（意图识别）
- **RecentContextExtractor**: 上下文提取器
- **InstantImageGenerator**: 即时生成协调器

#### 2.2.2 复用组件
- **scene_pre_analyzer.py**: 场景预分析
- **image_generation_service.py**: 图片生成
- **memory_buffer.py**: 对话历史获取
- **MattermostWebSocketClient**: 消息发送

---

## 3. 触发机制设计

### 3.1 方案对比

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|-------|
| **A: 关键词触发** | 实现简单，响应快 | 可能误触发，不够智能 | ⭐⭐⭐ |
| **B: AI意图识别** | 智能，准确率高 | 增加延迟，成本略高 | ⭐⭐⭐⭐⭐ |
| **C: 专用命令** | 明确，无误触发 | 用户体验不自然 | ⭐⭐ |

**推荐方案：B (AI意图识别) + A (关键词快速通道)**

### 3.2 方案B: AI意图识别 (推荐)

#### 3.2.1 实现位置

```python
# core/chat_engine.py

async def generate_response(
    self,
    channel_id: str,
    user_id: str,
    user_message: str,
    context: dict
) -> str:
    """生成AI响应"""

    # 1. 快速关键词检测（快速通道）
    if self._has_image_keywords(user_message):
        # 立即触发图片生成（不等待AI判断）
        asyncio.create_task(
            self._trigger_instant_image(channel_id, user_id, force=True)
        )
        # 继续生成文本响应
        return await self._generate_text_response(channel_id, user_message, context)

    # 2. AI意图检测（更智能）
    image_intent = await self._detect_image_intent(user_message, context)

    if image_intent['should_generate']:
        asyncio.create_task(
            self._trigger_instant_image(
                channel_id,
                user_id,
                image_type=image_intent.get('image_type'),
                force=False
            )
        )

    # 3. 生成文本响应
    response = await self._generate_text_response(channel_id, user_message, context)

    return response
```

#### 3.2.2 关键词快速通道

```python
def _has_image_keywords(self, message: str) -> bool:
    """快速关键词检测"""
    keywords = [
        "拍照", "拍张照", "拍个照",
        "发张照片", "发个照片", "发照片",
        "看看你", "自拍",
        "来张", "拍一张",
        "照片", "图片"
    ]

    # 转小写匹配
    message_lower = message.lower()

    # 精确匹配或包含匹配
    for keyword in keywords:
        if keyword in message_lower:
            # 排除否定句
            negative_patterns = ["不要", "别", "不用", "不拍"]
            if any(neg in message_lower for neg in negative_patterns):
                continue
            return True

    return False
```

#### 3.2.3 AI意图识别

```python
async def _detect_image_intent(
    self,
    user_message: str,
    recent_context: list
) -> dict:
    """
    使用AI判断是否应该生成图片

    Returns:
        {
            "should_generate": bool,
            "image_type": "selfie"|"scene"|None,
            "confidence": float,
            "reason": str
        }
    """
    from services.ai_service import call_structured_generation

    # 格式化最近对话
    context_text = "\n".join([
        f"{msg['role']}: {msg['content']}"
        for msg in recent_context[-5:]  # 最近5条
    ])

    prompt = f"""判断用户是否想让德克萨斯生成/发送图片。

## 最近对话
{context_text}

## 最新消息
用户: {user_message}

## 判断标准
1. **明确请求**: 用户直接要求"拍照"、"发照片"、"看看你"等
2. **暗示请求**: 聊到有趣场景，用户表示"想看看"、"真好"等
3. **适合场景**: 对话内容适合用图片展示（风景、活动、自拍等）

## 图片类型
- **selfie**: 用户想看德克萨斯本人（自拍、合照、日常状态）
- **scene**: 用户想看场景（风景、环境、事物）

请严格按照JSON格式输出：
{{
  "should_generate": true/false,
  "image_type": "selfie"|"scene"|null,
  "confidence": 0.0-1.0,
  "reason": "判断理由"
}}

注意：
- 只有置信度>=0.7才建议生成
- 默认优先selfie类型
- 如果对话与视觉内容无关，should_generate为false
"""

    try:
        result = await asyncio.wait_for(
            call_structured_generation([{"role": "user", "content": prompt}]),
            timeout=1.5  # 1.5秒超时，避免阻塞
        )

        # 只有高置信度才触发
        if result.get('confidence', 0) >= 0.7:
            return result
        else:
            return {"should_generate": False}

    except asyncio.TimeoutError:
        logger.warning("图片意图识别超时")
        return {"should_generate": False}
    except Exception as e:
        logger.error(f"图片意图识别失败: {e}")
        return {"should_generate": False}
```

### 3.3 方案A+C: 关键词 + 命令混合

```python
async def process_user_message(self, channel_id: str, user_message: str):
    """处理用户消息"""

    # 1. 检查专用命令
    if user_message.strip().startswith('/photo') or user_message.strip().startswith('/拍照'):
        await self._trigger_instant_image(channel_id, force=True)
        return "正在生成图片..."

    # 2. 关键词检测
    if self._has_image_keywords(user_message):
        asyncio.create_task(self._trigger_instant_image(channel_id))

    # 3. 正常处理
    return await self.generate_response(channel_id, user_message)
```

---

## 4. 上下文提取器

### 4.1 文件: `services/recent_context_extractor.py`

```python
"""
最近对话上下文提取器
用于即时图片生成时获取相关对话历史
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
from utils.logging_config import get_logger

logger = get_logger(__name__)


class RecentContextExtractor:
    """最近对话上下文提取器"""

    def __init__(self):
        from core.memory_buffer import get_channel_memory
        from utils.postgres_service import get_recent_conversations

        self.get_channel_memory = get_channel_memory
        self.get_recent_conversations = get_recent_conversations

    async def extract_recent_context(
        self,
        channel_id: str,
        window_minutes: int = 3,
        max_messages: int = 25,
        include_assistant: bool = True
    ) -> List[Dict]:
        """
        提取最近的对话上下文

        Args:
            channel_id: 频道ID
            window_minutes: 时间窗口（分钟）
            max_messages: 最大消息数量
            include_assistant: 是否包含AI的回复

        Returns:
            消息列表，格式: [{"role": "user", "content": "...", "timestamp": "..."}]
        """
        logger.info(f"[context_extractor] 提取最近对话: channel={channel_id}, window={window_minutes}min, max={max_messages}")

        # 策略1: 从Redis buffer获取（优先）
        messages = self._extract_from_redis(channel_id, window_minutes, max_messages)

        # 策略2: 如果Redis没有足够数据，从PostgreSQL获取
        if len(messages) < 3:  # 至少需要3条消息才有意义
            logger.debug("[context_extractor] Redis数据不足，从数据库获取")
            messages = await self._extract_from_database(channel_id, window_minutes, max_messages)

        # 过滤AI回复（可选）
        if not include_assistant:
            messages = [msg for msg in messages if msg['role'] == 'user']

        logger.info(f"[context_extractor] 提取到 {len(messages)} 条消息")
        return messages

    def _extract_from_redis(
        self,
        channel_id: str,
        window_minutes: int,
        max_messages: int
    ) -> List[Dict]:
        """从Redis buffer提取"""
        try:
            # 获取频道的所有缓存消息
            buffer_messages = self.get_channel_memory(channel_id)

            if not buffer_messages:
                return []

            # 计算时间窗口
            cutoff_time = datetime.now() - timedelta(minutes=window_minutes)

            # 过滤时间窗口内的消息
            recent_messages = []
            for msg in buffer_messages:
                # 解析时间戳
                msg_time = self._parse_timestamp(msg.get('timestamp'))
                if msg_time and msg_time > cutoff_time:
                    recent_messages.append(msg)

            # 限制数量（取最近的N条）
            recent_messages = recent_messages[-max_messages:]

            logger.debug(f"[context_extractor] Redis提取: {len(recent_messages)}条")
            return recent_messages

        except Exception as e:
            logger.error(f"[context_extractor] Redis提取失败: {e}")
            return []

    async def _extract_from_database(
        self,
        channel_id: str,
        window_minutes: int,
        max_messages: int
    ) -> List[Dict]:
        """从PostgreSQL提取（备用方案）"""
        try:
            messages = await self.get_recent_conversations(
                channel_id=channel_id,
                minutes=window_minutes,
                limit=max_messages
            )

            logger.debug(f"[context_extractor] 数据库提取: {len(messages)}条")
            return messages

        except Exception as e:
            logger.error(f"[context_extractor] 数据库提取失败: {e}")
            return []

    def _parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """解析时间戳字符串"""
        if not timestamp_str:
            return None

        try:
            # 尝试ISO格式
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except:
            try:
                # 尝试其他格式
                return datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            except:
                return None

    def format_context_for_scene(self, messages: List[Dict]) -> str:
        """
        将对话格式化为场景描述

        Args:
            messages: 消息列表

        Returns:
            格式化的场景描述文本
        """
        if not messages:
            return "当前对话内容为空。"

        context_lines = []

        for msg in messages:
            # 角色名称
            role_name = "kawaro" if msg['role'] == 'user' else "德克萨斯"

            # 消息内容
            content = msg.get('content', '').strip()

            if content:
                context_lines.append(f"{role_name}: {content}")

        # 添加时间信息
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        header = f"当前时间: {current_time}\n最近的对话内容:\n\n"

        return header + "\n".join(context_lines)


# 全局实例
recent_context_extractor = RecentContextExtractor()
```

### 4.2 数据库工具函数

```python
# utils/postgres_service.py 中添加

async def get_recent_conversations(
    channel_id: str,
    minutes: int = 3,
    limit: int = 25
) -> List[Dict]:
    """
    从数据库获取最近的对话

    Args:
        channel_id: 频道ID
        minutes: 最近N分钟
        limit: 最大数量

    Returns:
        消息列表
    """
    cutoff_time = datetime.now() - timedelta(minutes=minutes)

    query = """
        SELECT role, content, timestamp
        FROM conversations
        WHERE channel_id = %s
          AND timestamp > %s
        ORDER BY timestamp DESC
        LIMIT %s
    """

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (channel_id, cutoff_time, limit))
            rows = cursor.fetchall()

            messages = []
            for row in reversed(rows):  # 反转顺序，从旧到新
                messages.append({
                    "role": row[0],
                    "content": row[1],
                    "timestamp": row[2].isoformat()
                })

            return messages
```

---

## 5. 即时生成协调器

### 5.1 文件: `services/instant_image_generator.py`

```python
"""
即时图片生成协调器
整合上下文提取、场景分析、图片生成的完整流程
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional, Dict
from utils.logging_config import get_logger

logger = get_logger(__name__)


class InstantImageGenerator:
    """即时图片生成协调器"""

    def __init__(self):
        from services.recent_context_extractor import recent_context_extractor
        from services.scene_pre_analyzer import analyze_scene_with_ai
        from services.image_generation_service import image_generation_service
        from app.mattermost_client import MattermostWebSocketClient

        self.context_extractor = recent_context_extractor
        self.scene_analyzer = analyze_scene_with_ai
        self.image_service = image_generation_service
        self.ws_client = MattermostWebSocketClient()

        # 并发控制（同一频道同时只能生成1张）
        self._generating_channels = set()

    async def generate_instant_image(
        self,
        channel_id: str,
        user_id: str,
        image_type: Optional[str] = None,  # "selfie"|"scene"|None(自动判断)
        context_window_minutes: int = 3,
        max_messages: int = 25
    ) -> Dict:
        """
        生成即时图片的完整流程

        Args:
            channel_id: 频道ID
            user_id: 用户ID
            image_type: 强制指定图片类型
            context_window_minutes: 上下文时间窗口
            max_messages: 最大消息数

        Returns:
            {
                "success": bool,
                "image_path": str or None,
                "error": str or None,
                "generation_time": float
            }
        """
        start_time = datetime.now()
        logger.info(f"[instant_image] 开始生成即时图片: channel={channel_id}")

        # 1. 并发控制
        if channel_id in self._generating_channels:
            logger.warning(f"[instant_image] 频道正在生成图片，跳过: {channel_id}")
            return {
                "success": False,
                "error": "正在生成图片，请稍候...",
                "generation_time": 0
            }

        self._generating_channels.add(channel_id)

        try:
            # 2. 提取最近对话上下文
            recent_messages = await self.context_extractor.extract_recent_context(
                channel_id=channel_id,
                window_minutes=context_window_minutes,
                max_messages=max_messages,
                include_assistant=True
            )

            if not recent_messages:
                logger.warning("[instant_image] 未找到最近对话，无法生成图片")
                return {
                    "success": False,
                    "error": "没有找到最近的对话内容",
                    "generation_time": 0
                }

            # 3. 构建场景数据
            scene_data = self._build_scene_data(recent_messages, channel_id)

            # 4. 判断图片类型（selfie vs scene）
            is_selfie = self._determine_image_type(image_type, recent_messages)

            logger.info(f"[instant_image] 图片类型: {'自拍' if is_selfie else '场景'}")

            # 5. AI场景预分析（复用现有逻辑）
            logger.debug("[instant_image] 开始场景预分析")
            analysis_result = await self.scene_analyzer(
                scene_data=scene_data,
                is_selfie=is_selfie
            )

            if not analysis_result or 'enhanced_prompt' not in analysis_result:
                logger.error("[instant_image] 场景预分析失败")
                return {
                    "success": False,
                    "error": "场景分析失败",
                    "generation_time": (datetime.now() - start_time).total_seconds()
                }

            enhanced_prompt = analysis_result['enhanced_prompt']
            logger.debug(f"[instant_image] 增强提示词: {enhanced_prompt[:100]}...")

            # 6. 生成图片（复用现有逻辑）
            logger.debug("[instant_image] 开始生成图片")
            image_path = await self.image_service.generate_image(
                enhanced_prompt=enhanced_prompt,
                is_selfie=is_selfie,
                base_prompt=scene_data.get('content', '')
            )

            if not image_path:
                logger.error("[instant_image] 图片生成失败")
                return {
                    "success": False,
                    "error": "图片生成失败",
                    "generation_time": (datetime.now() - start_time).total_seconds()
                }

            logger.info(f"[instant_image] 图片生成成功: {image_path}")

            # 7. 上传并发送到频道
            await self._send_image_to_channel(channel_id, image_path, is_selfie)

            # 8. 返回结果
            generation_time = (datetime.now() - start_time).total_seconds()
            logger.info(f"[instant_image] 完成，耗时: {generation_time:.2f}秒")

            return {
                "success": True,
                "image_path": image_path,
                "error": None,
                "generation_time": generation_time
            }

        except asyncio.TimeoutError:
            logger.error("[instant_image] 生成超时")
            return {
                "success": False,
                "error": "生成超时，请稍后重试",
                "generation_time": (datetime.now() - start_time).total_seconds()
            }

        except Exception as e:
            logger.error(f"[instant_image] 生成失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"生成失败: {str(e)}",
                "generation_time": (datetime.now() - start_time).total_seconds()
            }

        finally:
            # 移除并发标记
            self._generating_channels.discard(channel_id)

    def _build_scene_data(self, messages: List[Dict], channel_id: str) -> Dict:
        """构建场景数据（模拟微观经历的格式）"""
        # 格式化对话为场景描述
        scene_content = self.context_extractor.format_context_for_scene(messages)

        scene_data = {
            "id": str(uuid.uuid4()),
            "content": scene_content,
            "timestamp": datetime.now().isoformat(),
            "channel_id": channel_id,
            "source": "instant_generation"
        }

        return scene_data

    def _determine_image_type(
        self,
        forced_type: Optional[str],
        messages: List[Dict]
    ) -> bool:
        """
        判断图片类型（selfie vs scene）

        Args:
            forced_type: 强制指定的类型
            messages: 最近消息

        Returns:
            True=selfie, False=scene
        """
        # 如果强制指定，直接返回
        if forced_type == "selfie":
            return True
        elif forced_type == "scene":
            return False

        # 否则根据对话内容判断
        # 简单规则：如果提到"你"、"自拍"、"看看你"，则为selfie
        combined_text = " ".join([msg.get('content', '') for msg in messages[-5:]])
        combined_text = combined_text.lower()

        selfie_keywords = ["你", "自拍", "看看你", "你在", "你的"]
        scene_keywords = ["风景", "景色", "这里", "那里", "环境", "看看"]

        selfie_score = sum(1 for kw in selfie_keywords if kw in combined_text)
        scene_score = sum(1 for kw in scene_keywords if kw in combined_text)

        # 默认优先selfie（与现有逻辑一致：40%概率）
        if selfie_score > scene_score:
            return True
        elif scene_score > selfie_score:
            return False
        else:
            # 平局，随机（40%概率selfie）
            import random
            return random.random() < 0.4

    async def _send_image_to_channel(
        self,
        channel_id: str,
        image_path: str,
        is_selfie: bool
    ):
        """上传并发送图片到频道"""
        try:
            # 确保bot user ID已获取
            if self.ws_client.user_id is None:
                await self.ws_client.fetch_bot_user_id()

            # 生成随机的发送文本
            import random
            if is_selfie:
                messages = [
                    "拍好了~",
                    "来，看这里。",
                    "这张怎么样？",
                    "刚拍的。",
                ]
            else:
                messages = [
                    "拍到了。",
                    "这就是现在的场景。",
                    "看，就是这样。",
                    "给你看看。",
                ]

            caption = random.choice(messages)

            # 上传并发送文件
            await self.ws_client.upload_and_send_file(
                channel_id=channel_id,
                file_path=image_path,
                message=caption
            )

            logger.info(f"[instant_image] 图片已发送到频道: {channel_id}")

        except Exception as e:
            logger.error(f"[instant_image] 发送图片失败: {e}", exc_info=True)
            raise


# 全局实例
instant_image_generator = InstantImageGenerator()
```

---

## 6. API端点

### 6.1 文件: `app/main.py` 中添加

```python
@app.post("/generate-instant-image")
async def generate_instant_image(
    channel_id: str,
    user_id: str = "kawaro",
    image_type: Optional[str] = None,
    context_window_minutes: int = 3,
    max_messages: int = 25
):
    """
    即时生成图片API

    Args:
        channel_id: 频道ID
        user_id: 用户ID
        image_type: 图片类型 ("selfie"|"scene"|None)
        context_window_minutes: 上下文时间窗口（分钟）
        max_messages: 最大消息数

    Returns:
        {
            "success": bool,
            "image_path": str,
            "generation_time": float,
            "error": str
        }
    """
    from services.instant_image_generator import instant_image_generator

    logger.info(f"[API] 接收即时图片生成请求: channel={channel_id}, type={image_type}")

    try:
        result = await instant_image_generator.generate_instant_image(
            channel_id=channel_id,
            user_id=user_id,
            image_type=image_type,
            context_window_minutes=context_window_minutes,
            max_messages=max_messages
        )

        return result

    except Exception as e:
        logger.error(f"[API] 即时图片生成失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "generation_time": 0
        }
```

---

## 7. 集成到聊天引擎

### 7.1 修改: `core/chat_engine.py`

```python
class ChatEngine:
    def __init__(self):
        # ... 现有初始化 ...
        self.instant_image_enabled = True  # 开关

    async def process_user_message(
        self,
        channel_id: str,
        user_id: str,
        message: str
    ) -> str:
        """处理用户消息（集成即时图片生成）"""

        # 1. 存储消息到buffer
        await self._store_message(channel_id, user_id, message)

        # 2. 检测图片生成意图（异步，不阻塞响应）
        if self.instant_image_enabled:
            asyncio.create_task(
                self._check_and_trigger_image(channel_id, user_id, message)
            )

        # 3. 生成AI文本响应
        response = await self.generate_response(channel_id, user_id, message)

        return response

    async def _check_and_trigger_image(
        self,
        channel_id: str,
        user_id: str,
        message: str
    ):
        """检测并触发图片生成"""
        try:
            # 快速关键词检测
            if self._has_image_keywords(message):
                logger.info(f"[chat_engine] 检测到图片关键词，触发生成")
                await self._trigger_instant_image(channel_id, user_id, force=True)
                return

            # AI意图检测（更智能但稍慢）
            recent_context = await self._get_recent_context(channel_id, limit=5)
            intent = await self._detect_image_intent(message, recent_context)

            if intent.get('should_generate'):
                logger.info(f"[chat_engine] AI检测到图片意图，触发生成")
                await self._trigger_instant_image(
                    channel_id,
                    user_id,
                    image_type=intent.get('image_type'),
                    force=False
                )

        except Exception as e:
            logger.error(f"[chat_engine] 图片意图检测失败: {e}")

    async def _trigger_instant_image(
        self,
        channel_id: str,
        user_id: str,
        image_type: Optional[str] = None,
        force: bool = False
    ):
        """触发即时图片生成"""
        from services.instant_image_generator import instant_image_generator

        try:
            # 添加超时控制
            result = await asyncio.wait_for(
                instant_image_generator.generate_instant_image(
                    channel_id=channel_id,
                    user_id=user_id,
                    image_type=image_type
                ),
                timeout=30.0  # 30秒超时
            )

            if result['success']:
                logger.info(f"[chat_engine] 图片生成成功: {result['image_path']}")
            else:
                logger.warning(f"[chat_engine] 图片生成失败: {result.get('error')}")

        except asyncio.TimeoutError:
            logger.error("[chat_engine] 图片生成超时")
        except Exception as e:
            logger.error(f"[chat_engine] 图片生成异常: {e}")

    def _has_image_keywords(self, message: str) -> bool:
        """关键词检测（同3.2.2节）"""
        # ... (见前文) ...
        pass

    async def _detect_image_intent(
        self,
        message: str,
        context: list
    ) -> dict:
        """AI意图检测（同3.2.3节）"""
        # ... (见前文) ...
        pass
```

---

## 8. 性能优化

### 8.1 并发控制

```python
# 同一频道同时只能生成1张图片
class InstantImageGenerator:
    def __init__(self):
        self._generating_channels = set()  # 正在生成的频道

    async def generate_instant_image(self, channel_id, ...):
        if channel_id in self._generating_channels:
            return {"success": False, "error": "正在生成图片..."}

        self._generating_channels.add(channel_id)
        try:
            # 生成逻辑
            ...
        finally:
            self._generating_channels.discard(channel_id)
```

### 8.2 超时控制

```python
# 各阶段超时设置
TIMEOUTS = {
    "context_extraction": 1.0,    # 上下文提取：1秒
    "intent_detection": 1.5,      # 意图检测：1.5秒
    "scene_analysis": 10.0,       # 场景分析：10秒
    "image_generation": 20.0,     # 图片生成：20秒
    "total": 30.0,                # 总计：30秒
}

# 应用超时
result = await asyncio.wait_for(
    some_async_function(),
    timeout=TIMEOUTS['scene_analysis']
)
```

### 8.3 缓存优化

```python
# 场景分析结果缓存（复用现有逻辑）
# scene_pre_analyzer.py 已有2小时缓存

# 对话上下文缓存（Redis buffer已有）
# memory_buffer.py 已有2小时缓存
```

### 8.4 资源限制

```python
# 限制同时生成的总数（全局）
MAX_CONCURRENT_GENERATIONS = 3

class InstantImageGenerator:
    _active_generations = 0
    _max_concurrent = MAX_CONCURRENT_GENERATIONS

    async def generate_instant_image(self, ...):
        if self._active_generations >= self._max_concurrent:
            return {"success": False, "error": "系统繁忙，请稍后重试"}

        self._active_generations += 1
        try:
            # 生成逻辑
            ...
        finally:
            self._active_generations -= 1
```

---

## 9. 监控和日志

### 9.1 关键指标

```python
# 需要收集的监控指标
metrics = {
    "instant_image.requests.total": "总请求数",
    "instant_image.requests.success": "成功数",
    "instant_image.requests.failure": "失败数",
    "instant_image.generation_time": "生成耗时（直方图）",
    "instant_image.context_extraction_time": "上下文提取耗时",
    "instant_image.scene_analysis_time": "场景分析耗时",
    "instant_image.image_generation_time": "图片生成耗时",
    "instant_image.concurrent_generations": "并发生成数",
}
```

### 9.2 日志记录

```python
# 关键节点日志
logger.info(f"[instant_image] 开始生成: channel={channel_id}")
logger.debug(f"[instant_image] 提取到 {len(messages)} 条消息")
logger.debug(f"[instant_image] 图片类型: {'自拍' if is_selfie else '场景'}")
logger.info(f"[instant_image] 生成成功，耗时: {elapsed:.2f}秒")
logger.error(f"[instant_image] 生成失败: {error}")
```

---

## 10. 测试计划

### 10.1 单元测试

```python
# tests/test_instant_image.py

async def test_context_extraction():
    """测试上下文提取"""
    extractor = RecentContextExtractor()
    messages = await extractor.extract_recent_context(
        channel_id="test_channel",
        window_minutes=3,
        max_messages=10
    )
    assert len(messages) > 0
    assert all('role' in msg and 'content' in msg for msg in messages)

async def test_image_type_detection():
    """测试图片类型判断"""
    generator = InstantImageGenerator()

    # 测试selfie
    messages = [{"role": "user", "content": "德克萨斯，自拍一张"}]
    is_selfie = generator._determine_image_type(None, messages)
    assert is_selfie == True

    # 测试scene
    messages = [{"role": "user", "content": "拍一下周围的风景"}]
    is_selfie = generator._determine_image_type(None, messages)
    assert is_selfie == False

async def test_keyword_detection():
    """测试关键词检测"""
    engine = ChatEngine()

    assert engine._has_image_keywords("拍张照") == True
    assert engine._has_image_keywords("发个照片") == True
    assert engine._has_image_keywords("不要拍照") == False
    assert engine._has_image_keywords("今天天气真好") == False
```

### 10.2 集成测试

```python
async def test_full_workflow():
    """测试完整流程"""
    # 1. 模拟对话
    await simulate_conversation([
        "今天天气真好",
        "德克萨斯你在干什么",
        "拍张照给我看看"
    ])

    # 2. 检查是否触发生成
    # ...

    # 3. 验证图片生成
    # ...
```

### 10.3 性能测试

```python
async def test_concurrent_limit():
    """测试并发限制"""
    tasks = [
        instant_image_generator.generate_instant_image(f"channel_{i}", "user")
        for i in range(10)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 应该有部分请求被限流
    success_count = sum(1 for r in results if isinstance(r, dict) and r.get('success'))
    assert success_count <= MAX_CONCURRENT_GENERATIONS
```

---

## 11. 部署清单

### 11.1 环境变量

```bash
# .env
ENABLE_INSTANT_IMAGE=true
INSTANT_IMAGE_TIMEOUT=30
INSTANT_IMAGE_MAX_CONCURRENT=3
INSTANT_IMAGE_CONTEXT_WINDOW=3  # 分钟
INSTANT_IMAGE_MAX_MESSAGES=25
```

### 11.2 依赖检查

```bash
# 确保以下服务正常运行
- Redis (对话缓存)
- PostgreSQL (对话历史)
- scene_pre_analyzer (场景分析)
- image_generation_service (图片生成)
- Mattermost (消息发送)
```

---

## 12. 风险和缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 生成耗时过长 | 用户等待 | 1. 异步处理不阻塞<br>2. 超时控制<br>3. 进度提示 |
| 频繁触发导致成本高 | 经济成本 | 1. 并发限制<br>2. 冷却时间<br>3. 关键词+AI双重过滤 |
| 上下文不足导致图片无关 | 用户体验差 | 1. 最少消息数检查<br>2. 场景分析质量控制<br>3. 用户反馈优化 |
| 并发冲突 | 系统不稳定 | 1. 频道级锁<br>2. 全局并发控制<br>3. 请求队列 |
| 误触发（关键词） | 不必要的生成 | 1. 否定句过滤<br>2. AI二次确认<br>3. 冷却机制 |

---

## 13. 未来扩展

### 13.1 可能的增强功能

1. **风格控制**: 用户可以指定图片风格（"卡通风格"、"写实风格"）
2. **场景建议**: AI主动建议适合拍照的时刻
3. **图片历史**: 保存用户的图片请求历史
4. **批量生成**: 一次生成多张不同角度的图片
5. **视频生成**: 支持生成短视频或GIF

### 13.2 技术优化方向

1. **预热机制**: 预测用户可能请求图片，提前准备
2. **增量生成**: 基于之前的图片进行微调
3. **质量评估**: 自动评估生成质量，不满意自动重试
4. **用户偏好学习**: 学习用户喜欢的图片风格

---

## 14. 附录

### 14.1 完整的触发词列表

```python
IMAGE_TRIGGER_KEYWORDS = {
    "explicit": [  # 明确请求
        "拍照", "拍张照", "拍个照",
        "发张照片", "发个照片", "发照片",
        "来张照片", "拍一张",
        "自拍", "看看你",
    ],
    "implicit": [  # 暗示请求
        "想看看", "给我看看",
        "什么样子", "长什么样",
        "现在怎么样",
    ],
    "negation": [  # 否定词（排除）
        "不要", "别", "不用",
        "不拍", "别拍",
    ]
}
```

### 14.2 API使用示例

```bash
# curl 请求示例
curl -X POST "http://localhost:8000/generate-instant-image" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_id": "abc123",
    "user_id": "kawaro",
    "image_type": "selfie",
    "context_window_minutes": 3,
    "max_messages": 20
  }'

# Python 请求示例
import httpx

response = await httpx.post(
    "http://localhost:8000/generate-instant-image",
    json={
        "channel_id": "abc123",
        "user_id": "kawaro",
        "image_type": None,  # 自动判断
    }
)
result = response.json()
print(f"Success: {result['success']}")
print(f"Image: {result['image_path']}")
```

---

**文档版本**: v1.0
**最后更新**: 2024-12-13
**作者**: Claude (Sonnet 4.5)
**审核状态**: 待用户审核
