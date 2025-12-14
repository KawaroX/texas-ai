# 图片生成 Provider 统一接口文档

**创建日期**: 2024-12-15
**版本**: 1.0.0

## 📋 概述

本次更新将图片生成功能重构为统一的 Provider 架构，支持：
- ✅ **SeeDream** (doubao-seedream-4-5-251128)
- ✅ **Gemini-2.5-Flash-Image**
- ✅ **多图输入** - 两个模型都支持
- ✅ **模型切换** - 通过配置轻松切换

## 🎯 主要改进

### 1. 统一接口

所有图片生成模型现在实现相同的接口：
```python
class BaseImageProvider(ABC):
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse
    def get_provider_name(self) -> str
    def supports_multi_image_input(self) -> bool
```

### 2. 支持多图输入

**SeeDream** 多图模式：
```python
request = ImageGenerationRequest(
    prompt="将图1的服装换为图2的服装",
    images=[image1_data, image2_data],  # 多张图片
    size="2K"
)
```

**Gemini** 多图模式：
```python
request = ImageGenerationRequest(
    prompt="基于这些参考图片生成新图片",
    images=[image1_data, image2_data, image3_data],  # 多张图片
)
```

### 3. 默认使用 Gemini

根据您的要求，现在**默认使用 Gemini-2.5-Flash-Image**。

## 🔧 配置方法

### 模型选择配置

**直接在代码中配置**（无需重启服务）：

打开 `services/image_generation_service.py`，修改顶部的配置常量：

```python
# ============================================================
# 图片生成模型配置 - 直接在这里修改模型选择
# ============================================================
IMAGE_PROVIDER = "gemini"  # 可选值: "gemini" 或 "seedream"
# ============================================================
```

### 切换模型

只需修改 `IMAGE_PROVIDER` 的值：
- `IMAGE_PROVIDER = "gemini"` - 使用 Gemini-2.5-Flash-Image
- `IMAGE_PROVIDER = "seedream"` - 使用 SeeDream

**优势**：
- ✅ 无需修改 .env 文件
- ✅ 无需重启服务
- ✅ 模型选择不是敏感信息，可以直接在代码中管理

### API Key 配置

在 `.env` 文件中配置 API Key（这是敏感信息）：
```bash
# API Key（两个模型共用）
IMAGE_GENERATION_API_KEY=your-api-key-here
```

## 📁 代码结构

### 新增文件

```
services/image_providers/
├── __init__.py                    # 导出所有 Provider
├── base.py                        # 基类和数据结构
├── seedream_provider.py           # SeeDream 实现
└── gemini_image_provider.py       # Gemini 实现
```

### 修改文件

1. **services/image_generation_service.py**
   - 添加 `IMAGE_PROVIDER` 配置常量（代码顶部）
   - 重构为使用 Provider 架构
   - 支持多图输入（多角色场景）
   - 简化代码，移除重复逻辑

## 🚀 使用示例

### 纯文字生成

```python
from services.image_providers import SeeDreamProvider, ImageGenerationRequest

provider = SeeDreamProvider(api_key="your-key")

request = ImageGenerationRequest(
    prompt="明日方舟风格，龙门城市夜景",
    images=None,  # 无底图
    size="2K"
)

response = await provider.generate_image(request)
```

### 单图生成

```python
request = ImageGenerationRequest(
    prompt="德克萨斯露肩自拍照",
    images=[base_image_data],  # 1张底图
    size="1080x1920"
)

response = await provider.generate_image(request)
```

### 多图生成（新功能！）

```python
# 读取多张角色图片
texas_image = load_image("texas.png")
exusiai_image = load_image("exusiai.png")
croissant_image = load_image("croissant.png")

request = ImageGenerationRequest(
    prompt="企鹅物流办公室，三人在一起讨论任务",
    images=[texas_image, exusiai_image, croissant_image],  # 3张图片
    size="3840x2160"
)

response = await provider.generate_image(request)
```

## 🧪 测试脚本

运行统一接口测试：
```bash
python scripts/test_unified_image_providers.py
```

该脚本会测试：
1. ✅ SeeDream 和 Gemini 的纯文字生成
2. ✅ 单图生成（露肩自拍）
3. ✅ 多图生成（多角色场景）

## 📊 两个模型对比

| 特性 | SeeDream | Gemini-2.5-Flash-Image |
|------|----------|------------------------|
| **API结构** | 简单JSON | 嵌套contents/parts |
| **多图输入** | ✅ 支持 (`image: [...]`) | ✅ 支持 (多个`inline_data`) |
| **分辨率** | 2K | 默认 |
| **响应格式** | URL或base64 | inline base64 |
| **面部保持** | 较好 | 需要强化prompt |
| **生成速度** | 11-13秒 | 类似 |
| **水印控制** | ✅ 支持 | ❌ 不支持 |

## 🔍 关键代码变更

### image_generation_service.py

**Before (旧代码)**:
```python
# 只使用第一个角色的图片
main_character = detected_characters[0]
character_image_path = character_manager.get_character_image_path(main_character)
character_image_data = ...  # 只读取一张图

# 直接调用 SeeDream API
payload = {"model": "doubao-seedream-4-5-251128", ...}
response = await client.post(self.generation_url, ...)
```

**After (新代码)**:
```python
# 读取所有检测到的角色图片
character_images = []
for char_name in detected_characters:
    char_image_path = character_manager.get_character_image_path(char_name)
    character_images.append(char_image_data)

# 使用统一的 Provider 接口
filepath = await self._generate_with_provider(
    prompt=prompt,
    images=character_images,  # 支持多图！
    size=recommended_size
)
```

## 💡 最佳实践

### 1. Gemini 面部保持

Gemini 需要明确指示保持面部特征：
```python
# 在 gemini_image_provider.py 中自动添加
face_preservation_text = (
    "CRITICAL REQUIREMENTS:\n"
    "1. DO NOT modify the character's facial features\n"
    "2. KEEP the exact same hair color and style\n"
    "3. PRESERVE the character's facial identity completely\n"
    ...
)
```

### 2. 多图场景生成

现在系统会自动读取所有检测到的角色图片：
- **检测到**: ["能天使", "可颂", "空"]
- **读取图片**: 3张角色图片
- **生成**: 包含3个角色的合成场景

### 3. 性能优化

- 使用 SeeDream 时启用 `sequential_image_generation: "disabled"` 以加快多图生成
- Gemini 自动在 Provider 层面处理面部保持

## ⚠️ 注意事项

### 1. API Key

两个模型使用相同的 `IMAGE_GENERATION_API_KEY`，确保在 `.env` 中配置。

### 2. 图片尺寸

- **SeeDream**: 支持 "2K", "1080x1920", "3840x2160" 等
- **Gemini**: 使用默认尺寸

### 3. 多图数量

- **SeeDream**: 测试支持2-3张图片
- **Gemini**: 理论上支持更多，但需要测试

### 4. 旧代码兼容

现有的图片生成逻辑完全保留，只是底层实现改为 Provider 架构。

## 🐛 故障排查

### 问题1: 模型未切换

**症状**: 修改配置后仍使用旧模型

**解决**:
```bash
# 1. 确认代码中的 IMAGE_PROVIDER 已修改
grep "IMAGE_PROVIDER =" services/image_generation_service.py

# 2. 查看日志确认使用的模型
docker-compose logs bot | grep "图片生成模型"
```

**注意**: 修改 `IMAGE_PROVIDER` 后无需重启服务，下次生成图片时会自动使用新模型。

### 问题2: Gemini 人物不像

**症状**: Gemini 生成的人物面部特征改变

**解决**: Provider 已自动添加面部保持指令。如果仍有问题，可以：
1. 使用 SeeDream（面部保持更好）
2. 调整 `gemini_image_provider.py` 中的 `face_preservation_instruction`

### 问题3: 多图生成失败

**症状**: 传入多张图片后生成失败

**解决**:
```python
# 检查日志
logger.info(f"📸 共读取 {len(character_images)} 张角色图片")

# 确认模型支持多图
if provider.supports_multi_image_input():
    # 使用多图
else:
    # 只使用第一张图
```

## 📚 相关文档

- `CLAUDE.md` - 项目整体说明
- `IMAGE_GENERATION_REFACTOR_SUMMARY.md` - 之前的重构总结
- `MODEL_COMPARISON_GUIDE.md` - 模型对比指南

## 🔜 未来计划

1. ✅ ~~统一 Provider 接口~~
2. ✅ ~~支持多图输入~~
3. ✅ ~~默认使用 Gemini~~
4. ⏳ 添加更多图片生成模型（DALL-E 3, Stable Diffusion等）
5. ⏳ 优化多图合成的 prompt 策略
6. ⏳ 添加图片质量评估和自动选择最佳模型

---

**更新日期**: 2024-12-15
**作者**: Claude Sonnet 4.5
