# 图片生成逻辑重构总结

生成日期: 2025-12-12

## 📋 重构目标

将图片生成决策从**概率驱动**改为**AI 决策驱动**，让生成微观经历的 AI 判断是否需要生成图片以及生成什么类型的图片。

## ✅ 完成的修改

### 1. 修改主日程生成 AI 提示词 ✅

**文件**: `services/ai_service.py` (第535-542行)

**修改内容**:
- 添加了明确要求：日程的第一项必须是起床，最后一项必须是睡觉
- 指定了合理的时间范围：起床 06:00-08:00，睡觉 22:00-23:59

```python
## 生成要求
1. **必须明确起床和睡觉时间**：日程的第一项应该是起床（例如 06:30-07:00），最后一项应该是睡觉（例如 23:00-23:59）
...
6. 起床时间一般在 06:00-08:00 之间，睡觉时间一般在 22:00-23:59 之间，根据当天的活动安排适当调整
```

### 2. 修改微观经历生成 AI 提示词 ✅

**文件**: `services/ai_service.py` (第702-765行)

**新增字段**:
```json
{
  "need_image": true或false,
  "image_type": "selfie"或"scene"或null,
  "image_reason": "生成图片的原因"
}
```

**AI 决策指导**:

**是否生成图片 (need_image)** 的触发条件：
1. 遇到美丽的风景、特殊的天气景观（日落、晚霞、雨后彩虹等）
2. 重要的时刻或事件（完成重要任务、特殊庆祝、难忘瞬间等）
3. 有趣的场景或经历（意外发生的趣事、特别的互动等）
4. 与朋友的温馨时刻（一起用餐、聊天、合作等）
5. **起床或睡觉相关的经历，通常设置为true（自拍类型）**

**图片类型 (image_type)**：
- **"selfie"（自拍）**：德克萨斯想要分享自己的状态、表情、或与朋友的合影
  - 示例：起床后的状态、心情好时的自拍、与朋友的合照
- **"scene"（场景）**：重点是展示环境、风景、或第一人称视角的场景
  - 示例：美丽的风景、工作场景、特殊的环境

### 3. 修改早安/晚安逻辑 ✅

**文件**: `services/ai_service.py` (第715-719行)

**修改内容**:
```python
**特别注意**：
- **只有当日程标题包含"起床"或"睡觉"时**，才需要在某个合适的item中包含早安或晚安的问候
- 如果是起床相关日程，在第一个item中设置need_interaction为true，交互内容包含道早安
- 如果是睡觉相关日程，在最后一个item中设置need_interaction为true，交互内容包含道晚安
- 其他日程项不需要早安/晚安问候
```

**改进点**：
- 之前：所有微观经历的第一项都可能包含早安
- 现在：只有起床相关的微观经历才包含早安，只有睡觉相关的才包含晚安

### 4. 修改图片生成任务逻辑 ✅

**文件**: `tasks/image_generation_tasks.py` (第274-291行)

**删除的旧逻辑**:
```python
# ❌ 删除：基于概率的图片生成决策
# 🌅🌙 识别首末事件（早安/晚安）并设置特殊概率
is_first_or_last = (index == 0 or index == total_events - 1)

if is_first_or_last:
    generation_probability = 1.0    # 首末事件100%生成图片
    selfie_probability = 0.6        # 60%自拍40%场景
else:
    generation_probability = 0.3   # 其他事件30%概率
    selfie_probability = 0.4        # 40%自拍60%场景

# 应用动态概率判断
if random.random() < generation_probability:
    is_selfie = random.random() < selfie_probability
```

**新增的 AI 决策逻辑**:
```python
# ✅ 新增：读取 AI 生成的图片决策字段
need_image = event_data.get("need_image", False)
image_type = event_data.get("image_type")  # "selfie" | "scene" | null
image_reason = event_data.get("image_reason", "")

# 如果 AI 决定不需要生成图片，跳过
if not need_image:
    logger.debug(f"[image_gen] 事件 {experience_id} AI决定不生成图片，跳过。")
    continue

# 如果 image_type 无效，跳过
if image_type not in ["selfie", "scene"]:
    logger.warning(f"[image_gen] 事件 {experience_id} 的 image_type 无效: {image_type}，跳过。")
    continue

# 根据 AI 决策设置图片类型
is_selfie = (image_type == "selfie")
logger.info(f"[image_gen] ✨ AI决定为事件 {experience_id} 生成{image_type}图片，原因: {image_reason}")
```

## 📊 重构前后对比

### 重构前（概率驱动）
- ❌ 图片生成完全依赖硬编码的概率（30%、60%等）
- ❌ 无法根据实际内容智能决策
- ❌ 首末事件强制生成图片（不管是否合适）
- ❌ 自拍/场景类型随机决定
- ❌ 早安/晚安在所有第一项微观经历中都可能出现

### 重构后（AI 决策驱动）
- ✅ AI 根据经历内容智能判断是否需要生成图片
- ✅ AI 根据场景决定图片类型（自拍 vs 场景）
- ✅ 提供了明确的决策指导（美丽风景、重要事件、有趣场景等）
- ✅ 记录生成原因，便于日志追踪和调试
- ✅ 早安/晚安只在起床/睡觉相关的微观经历中出现
- ✅ 主日程明确起床和睡觉时间

## 🔍 数据流程

```
1. 生成主日程
   ├─ AI 明确指定起床时间（第一项）
   └─ AI 明确指定睡觉时间（最后一项）

2. 生成微观经历
   ├─ AI 为每个经历判断：need_image, image_type, image_reason
   ├─ 只在起床微观经历中包含早安
   └─ 只在睡觉微观经历中包含晚安

3. 图片生成任务
   ├─ 读取 need_image 字段（而不是随机概率）
   ├─ 读取 image_type 字段（而不是随机决定）
   ├─ 根据 AI 决策执行生成
   └─ 记录 image_reason 到日志
```

## 🎯 预期效果

1. **更智能的图片生成**：
   - 美丽的风景会触发场景图生成
   - 重要时刻会触发自拍或合影
   - 平淡无奇的经历不会生成图片

2. **更合理的早安/晚安**：
   - 只在真正起床时说早安
   - 只在真正睡觉时说晚安
   - 不会在中午或下午出现早安

3. **更好的可追踪性**：
   - `image_reason` 字段记录了生成原因
   - 日志中可以清晰看到 AI 的决策过程

4. **更符合角色设定**：
   - AI 可以根据德克萨斯的性格特点决策
   - 冷静内敛的她不会频繁发自拍
   - 但遇到特别的场景或重要时刻会分享

## 🚀 后续建议

### 1. 调整 AI 决策倾向
如果发现图片生成太少或太多，可以在提示词中调整指导：
```python
# 如果图片太少，可以放宽条件
"当满足以下条件之一时，设置为true（建议 50% 的经历生成图片）"

# 如果图片太多，可以收紧条件
"只有在特别值得记录的时刻才生成图片（建议 20-30% 的经历生成图片）"
```

### 2. 监控 AI 决策质量
定期检查日志中的 `image_reason` 字段，评估 AI 决策是否合理：
```bash
# 查看最近的图片生成决策
grep "AI决定为事件" worker-logs.txt | tail -20
```

### 3. A/B 测试
可以保留一个备份的概率版本，对比两种方式的效果：
- 图片生成数量
- 图片质量和相关性
- 用户反馈

### 4. 微调提示词
根据实际运行效果，可以进一步细化触发条件：
- 添加负面条件（哪些情况**不**生成图片）
- 区分工作日和周末的图片生成策略
- 考虑天气、情绪等因素

### 5. 扩展 image_reason
可以让 AI 生成更详细的原因，用于：
- 数据分析和优化
- 生成图片时的额外上下文
- 向用户展示（"我想分享这个给你看，因为..."）

## 📝 测试建议

1. **生成一天的完整日程**：
   ```bash
   curl -X GET "http://localhost:8000/generate-daily-life?target_date=2025-12-13"
   ```

2. **检查主日程**：
   - 验证第一项是否是起床
   - 验证最后一项是否是睡觉

3. **检查微观经历**：
   - 查看哪些经历的 `need_image` 为 true
   - 查看 `image_type` 的分布（selfie vs scene）
   - 阅读 `image_reason` 是否合理

4. **观察图片生成任务**：
   - 查看 Worker 日志中的 "AI决定为事件...生成图片"
   - 确认只有 `need_image=true` 的经历触发生成
   - 确认图片类型与 AI 决策一致

5. **验证早安/晚安**：
   - 检查起床微观经历是否包含早安
   - 检查睡觉微观经历是否包含晚安
   - 确认其他时间段没有早安/晚安

## 🔧 故障排查

### 问题：没有生成任何图片
**可能原因**：
- AI 返回的 `need_image` 全部为 false
- `image_type` 字段格式不正确（不是 "selfie" 或 "scene"）

**解决方案**：
1. 检查微观经历的 JSON 输出
2. 调整提示词，引导 AI 更倾向于生成图片
3. 检查日志中的警告信息

### 问题：图片类型不符合预期
**可能原因**：
- AI 对自拍和场景的理解与预期不同

**解决方案**：
1. 在提示词中添加更多示例
2. 明确区分两种类型的使用场景

### 问题：早安/晚安出现在错误的时间
**可能原因**：
- 主日程中起床/睡觉的标题不包含关键词
- 微观经历生成时 AI 没有正确识别

**解决方案**：
1. 确保主日程的起床项标题包含"起床"
2. 确保主日程的睡觉项标题包含"睡觉"或"睡眠"
3. 检查 `schedule_item.get("title")` 的值

## 🔧 额外优化：统一 AI 模型配置和 API 格式

### 5. 修改场景预分析器完全统一为生成日程的方式 ✅

**文件**: `services/scene_pre_analyzer.py` (完整重构)

**问题**：
- 之前硬编码使用 Gemini 原生 API 格式 (`/v1beta/models/{model}:generateContent`)
- 之前使用不同的 API URL (`https://gemini-v.kawaro.space`)
- 与生成日程的 OpenAI 兼容格式不一致
- 配置不统一，难以维护

**改进内容**：

1. **API 配置统一** (第14-50行)：
```python
# 🆕 使用和生成日程完全相同的 API 方式
STRUCTURED_API_KEY = os.getenv("STRUCTURED_API_KEY")
STRUCTURED_API_URL = os.getenv("STRUCTURED_API_URL", "https://yunwu.ai/v1/chat/completions")
STRUCTURED_API_MODEL = os.getenv("STRUCTURED_API_MODEL", "gemini-2.5-flash")

# 🆕 根据生成日程的模型，自动选择对应的 lite 版本
def get_scene_analyzer_model(base_model: str) -> str:
    if "gemini" in base_model.lower():
        if "-lite" in base_model.lower():
            return base_model
        if base_model.endswith("-flash"):
            return base_model + "-lite"
        elif base_model.endswith("-pro"):
            return base_model.replace("-pro", "-flash-lite")
        else:
            return base_model + "-lite"
    else:
        return base_model

SCENE_ANALYZER_MODEL = get_scene_analyzer_model(STRUCTURED_API_MODEL)
```

2. **提示词格式转换** (第204-266行)：
```python
# ❌ 旧格式 (Gemini 原生)：
# contents: [{"parts": [{"text": "..."}]}]

# ✅ 新格式 (OpenAI 兼容)：
payload = {
    "model": SCENE_ANALYZER_MODEL,
    "messages": [
        {
            "role": "user",
            "content": user_prompt
        }
    ],
    "response_format": {"type": "json_object"},
    "stream": False
}
```

3. **请求头格式转换** (第296-300行)：
```python
# ❌ 旧格式：
# headers = {
#     "x-goog-api-key": api_key
# }

# ✅ 新格式：
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {STRUCTURED_API_KEY}"
}
```

4. **API URL 和响应解析转换** (第306-324行)：
```python
# ❌ 旧格式：
# response = await client.post(GEMINI_API_URL, ...)
# result_text = response_json["candidates"][0]["content"]["parts"][0]["text"]

# ✅ 新格式：
response = await client.post(STRUCTURED_API_URL, ...)
result_text = response_json["choices"][0]["message"]["content"]
```

**改进效果**：
- ✅ 完全使用生成日程的 API 方式（OpenAI 兼容格式）
- ✅ 使用相同的 API URL (`https://yunwu.ai/v1/chat/completions`)
- ✅ 使用相同的认证方式 (`Authorization: Bearer`)
- ✅ 使用相同的 API KEY (`STRUCTURED_API_KEY`)
- ✅ 自动适配生成日程的模型配置
- ✅ 如果生成日程用 `gemini-2.5-flash`，场景分析用 `gemini-2.5-flash-lite`
- ✅ 如果生成日程用 `gemini-2.5-pro`，场景分析用 `gemini-2.5-flash-lite`
- ✅ 如果生成日程用其他非 Gemini 模型，场景分析保持一致
- ✅ 如果修改 `STRUCTURED_API_MODEL` 环境变量，场景分析会自动跟随
- ✅ 启动时会在日志中显示模型配置，便于调试
- ✅ 配置统一，易于维护和故障排查

## 📚 相关文件

修改的文件列表：
1. `services/ai_service.py` - 主日程和微观经历生成 AI 提示词
2. `tasks/image_generation_tasks.py` - 图片生成任务逻辑
3. `services/scene_pre_analyzer.py` - **完整重构**：API 格式、模型配置全面统一
4. `tasks/daily_tasks.py` - 修复日程生成超时问题（增加 300s 超时）
5. `.gitignore` - 代码格式优化和组织

相关文档：
1. `CLAUDE.md` - 项目总体说明
2. `IMPROVEMENT_SUGGESTIONS.md` - 其他改进建议
3. `IMAGE_GENERATION_REFACTOR_SUMMARY.md` - 本文档（重构总结）

---

**重构完成日期**: 2025-12-12
**重构执行者**: Claude Sonnet 4.5
**主要改进**：
1. 图片生成从概率驱动改为 AI 决策驱动
2. 早安/晚安逻辑优化，只在起床/睡觉时出现
3. 场景预分析器完全统一为 OpenAI 兼容 API 格式
4. 修复日程生成超时问题
5. **🎨 新增：高级视觉效果系统（2025-12-12 第二次更新）**
6. **💃 新增：自拍图片性感化增强（2025-12-12 第二次更新）**
7. **🔍 新增：缺失图片检测和自动补全机制（2025-12-12 第二次更新）**
**预计测试时间**: 生成明天的日程后观察效果

## ⚠️ 重要提醒

由于场景预分析器的 API 格式发生了重大变化（从 Gemini 原生格式改为 OpenAI 兼容格式），首次运行时请：

1. **确认环境变量配置正确**：
   ```bash
   # 确保这些环境变量已设置
   echo $STRUCTURED_API_KEY
   echo $STRUCTURED_API_URL
   echo $STRUCTURED_API_MODEL
   ```

2. **观察场景分析日志**：
   ```bash
   # 启动时会显示配置信息
   grep "场景分析配置" logs/*.log

   # 观察场景分析是否成功
   grep "scene_analyzer" logs/*.log | tail -20
   ```

3. **如果遇到问题**：
   - 检查 API URL 是否正确 (`https://yunwu.ai/v1/chat/completions`)
   - 检查 API KEY 是否有效
   - 查看 Mattermost 预分析通知频道的错误信息

---

## 🎨 第二次更新：高级视觉效果和性感化增强（2025-12-12）

### 6. 扩展场景分析 JSON Schema - 添加高级视觉效果字段 ✅

**文件**: `services/scene_pre_analyzer.py` (第236-241行自拍, 第273-275行场景)

**新增字段**：
```json
{
  "visual_effects": "特殊视觉效果（水雾、镜面反射、光束、雨滴、蒸汽、bokeh散景、光晕等）",
  "photographic_technique": "摄影技巧（浅景深、逆光剪影、HDR、长曝光、三分构图等）",
  "artistic_style": "整体艺术风格（电影感、时尚杂志风、赛博朋克、复古胶片质感等）",
  "pose_suggestion": "姿态建议（自拍专用：撩发、回眸、侧身展现曲线、慵懒姿态等）",
  "clothing_details": "服装细节建议（露肩、V领、开叉、透视元素、贴身剪裁等性感元素）"
}
```

**AI 引导优化**：
- 🎨 要求 AI 主动建议高级视觉效果（如：浴室场景→水雾+镜面反射）
- 📸 提供专业摄影艺术指导
- 💃 自拍模式：要求生成更大胆、更性感的姿态和服装建议

### 7. 增强图片生成服务使用新字段 ✅

**文件**: `services/image_generation_service.py`

**场景图增强** (第310-316行)：
```python
# 新增：高级视觉效果
if scene_analysis.get("visual_effects"):
    enhanced_details.append(f"✨ 特殊视觉效果: {scene_analysis['visual_effects']}")
if scene_analysis.get("photographic_technique"):
    enhanced_details.append(f"📸 摄影技巧: {scene_analysis['photographic_technique']}")
if scene_analysis.get("artistic_style"):
    enhanced_details.append(f"🎬 艺术风格: {scene_analysis['artistic_style']}")
```

**自拍图性感化增强** (第578-658行)：

1. **服装建议优化**：
   - 优先使用 AI 建议的性感服装细节
   - 默认建议包含露肩、V领、开叉等元素
   - 强调"时尚、性感、自信"风格

2. **提示词重写**：
   ```python
   base_selfie_prompt = (
       "生成一张充满魅力和自信的高质量二次元风格自拍照片"
       "注重展现角色的性感魅力和身材曲线"
       "💃 身材展现：注重展现优美的身材曲线和线条，姿态要优雅性感"
   )
   ```

3. **姿态建议增强**：
   - 优先使用 AI 的 `pose_suggestion` 字段
   - 默认建议：撩发、回眸、侧身展现曲线、慵懒斜倚、挺胸展现身材等
   - 强调"充满魅力和自信"

4. **表情优化**：
   ```python
   "高冷气质，但眼神更有魅力和吸引力"
   "可以有微笑、媚眼、或性感的眼神"
   "展现冷艳美人的独特魅力"
   ```

5. **视觉效果应用**：
   - 添加 AI 建议的特殊视觉效果
   - 添加摄影技巧指导
   - 添加艺术风格要求

### 8. 实现缺失图片检测和自动生成机制 ✅

**问题**：之前没有机制检测某个日期是否有图片缺失

**解决方案**：

#### 8.1 新增检测函数 (tasks/image_generation_tasks.py)

```python
async def check_missing_images_for_date(target_date: str):
    """
    检查指定日期是否有缺失的图片

    返回：{
        "has_data": bool,
        "total_need_image": int,  # 需要生成的总数
        "already_generated": int,  # 已生成数量
        "missing_count": int,     # 缺失数量
        "has_missing": bool,
        "missing_ids": list       # 缺失的ID列表
    }
    """
```

**检测逻辑**：
1. 读取当天所有微观经历（优先enhanced数据，回退到original）
2. 筛选出 `need_image=true` 的经历
3. 检查 Redis Hash `PROACTIVE_IMAGES_KEY` 中是否存在对应图片
4. 返回详细的统计信息

#### 8.2 新增 API 端点 (app/main.py 第272-330行)

```bash
GET /check-and-generate-missing-images?target_date=2025-12-13
```

**功能**：
- 检查指定日期的图片生成情况
- 如果有缺失，自动触发 4:50 的图片生成任务
- 返回详细的统计信息

**返回示例**：
```json
{
  "status": "triggered",
  "message": "检测到 5 张图片缺失，已触发生成任务",
  "date": "2025-12-13",
  "total_need_image": 10,
  "already_generated": 5,
  "missing_count": 5,
  "missing_ids": ["exp_001", "exp_002", ...]
}
```

## 🎯 新增功能的预期效果

### 1. 更多样化和高级的视觉效果 🎨
- **浴室场景**：自动添加水雾、镜面反射、蒸汽效果
- **夜景场景**：霓虹灯光、光晕、长曝光光轨
- **室内场景**：阳光透过窗帘的光束、景深效果
- **雨天场景**：雨滴、地面倒影、湿润质感

### 2. 更性感、更大胆的自拍图片 💃
- **姿态**：撩发、回眸、侧身展现曲线等性感姿态
- **服装**：露肩、V领、开叉、透视元素、贴身剪裁
- **表情**：高冷中带着魅力，媚眼、性感眼神
- **构图**：突出人物魅力和身材曲线

### 3. 完善的图片生成监控 🔍
- 可以检测任何日期的图片生成完整性
- 自动补全缺失的图片
- 详细的统计信息和缺失列表

## 📝 测试新功能

### 1. 测试高级视觉效果

```bash
# 生成一天的完整日程（会触发AI场景分析）
curl -X GET "http://localhost:8000/generate-daily-life?target_date=2025-12-13"

# 等待 4:50 任务执行或手动触发
curl -X GET "http://localhost:8000/check-and-generate-missing-images?target_date=2025-12-13"

# 检查场景分析日志，查看AI建议的视觉效果
grep -A 5 "visual_effects\|photographic_technique\|artistic_style" logs/worker.log
```

### 2. 测试自拍性感化

```bash
# 检查自拍生成日志，查看新的提示词
grep "充满魅力\|性感\|身材曲线" logs/worker.log

# 查看生成的图片，验证效果
ls -lh /app/generated_content/images/2025-12-13/
```

### 3. 测试缺失图片检测

```bash
# 检查今天的图片生成情况
curl -X GET "http://localhost:8000/check-and-generate-missing-images"

# 检查特定日期
curl -X GET "http://localhost:8000/check-and-generate-missing-images?target_date=2025-12-10"

# 查看返回的统计信息
```

## 🔧 故障排查（新增内容）

### 问题：场景分析没有返回新字段
**可能原因**：
- AI 模型版本不支持 JSON 格式输出
- 提示词过长导致 AI 忽略部分字段

**解决方案**：
1. 检查 `SCENE_ANALYZER_MODEL` 是否支持 `response_format: json_object`
2. 查看场景分析日志中的完整 JSON 输出
3. 如有必要，简化提示词或增加字段权重

### 问题：自拍图片不够性感
**可能原因**：
- AI 预分析没有提供 `pose_suggestion` 和 `clothing_details`
- 图片生成模型对性感元素的理解不同

**解决方案**：
1. 在场景分析提示词中增加更多性感元素的示例
2. 在图片生成服务中增加更明确的性感描述
3. 尝试调整图片生成模型参数

### 问题：缺失图片检测不准确
**可能原因**：
- Redis 数据不一致
- 图片生成任务失败但没有记录

**解决方案**：
1. 检查 Redis 中的 `PROACTIVE_IMAGES_KEY` hash
2. 对比微观经历数据和已生成图片列表
3. 查看 Worker 日志中的图片生成失败记录
