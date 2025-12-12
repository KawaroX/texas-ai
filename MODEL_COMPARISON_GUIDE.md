# 图片生成模型对比测试指南

## 📋 概述

这个指南将帮助你对比两个图片生成模型的效果：
- **gpt-image-1-all** - 当前使用的模型
- **doubao-seedream-4-5-251128** - 待测试的 SeeDream 模型

## 🚀 部署状态检查

### 1. 检查服务是否正常运行

```bash
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml ps"
```

应该看到以下服务都在运行（STATUS 为 Up）：
- texas-bot
- texas-worker
- texas-postgres
- texas-redis
- texas-qdr (Qdrant)
- mattermost
- nginx_mattermost

### 2. 查看服务日志

```bash
# 查看 bot 日志
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs -f bot --tail=50"

# 查看 worker 日志
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml logs -f worker --tail=50"
```

## 🧪 运行模型对比测试

### 方式 1：本地测试（推荐）

如果你的本地环境已配置好 API KEY：

```bash
# 设置环境变量
export IMAGE_GENERATION_API_KEY="your-api-key-here"

# 运行测试
cd /Volumes/base/texas-ai
python scripts/test_model_comparison.py --prompt "一位黑色长发、兽耳的女性角色，穿着时尚露肩上衣，在浴室镜前自拍。浴室中有水雾和镜面反射效果，光线柔和，氛围性感优雅。明日方舟二次元风格。"
```

### 方式 2：服务器测试

```bash
# 进入服务器 bot 容器
ssh root@115.190.143.80 "cd /root/texas-ai && docker compose -f docker-compose.yml -f docker-compose.nginx.yml exec bot /bin/bash"

# 在容器内运行测试
cd /app
python scripts/test_model_comparison.py --prompt "你的测试提示词"
```

## 📝 测试提示词建议

### 测试场景 1：自拍照（性感风格）

```bash
python scripts/test_model_comparison.py --prompt "德克萨斯（明日方舟），黑色长发，兽耳，穿着露肩V领上衣，在浴室镜前自拍。浴室中有水雾和镜面反射，光线柔和，姿态优雅性感，眼神魅力十足。高质量二次元动漫风格，注重展现身材曲线。"
```

### 测试场景 2：夜景场景

```bash
python scripts/test_model_comparison.py --prompt "龙门城市夜景，霓虹灯光，街道倒影，第一人称视角拍摄。赛博朋克风格，高对比度，长曝光光轨效果。明日方舟二次元风格。"
```

### 测试场景 3：室内光影

```bash
python scripts/test_model_comparison.py --prompt "温馨的室内场景，阳光透过窗帘形成美丽的光束，桌上有咖啡和书籍。浅景深效果，暖色调，电影感构图。明日方舟二次元风格。"
```

### 测试场景 4：雨天氛围

```bash
python scripts/test_model_comparison.py --prompt "雨天的龙门街道，雨滴打在地面形成美丽的倒影，湿润的质感，柔和的光线。纪实摄影风格，梦幻柔焦。明日方舟二次元风格。"
```

## 📊 对比测试结果

测试脚本会自动生成对比报告，包含：

1. **生成状态** - 是否成功生成
2. **生成耗时** - 速度对比
3. **文件大小** - 图片大小对比
4. **输出路径** - 图片保存位置

### 示例输出

```
================================================================================
📊 模型对比报告
================================================================================

| 项目 | gpt-image-1-all | doubao-seedream-4-5 |
|------|----------------|---------------------|
| 生成状态 | ✅ 成功 | ✅ 成功 |
| 生成耗时 | 15.23秒 | 12.45秒 |
| 文件大小 | 245.3KB | 318.7KB |
| 输出路径 | /tmp/model_comparison_test/gpt_image_20251212_230645.png | /tmp/model_comparison_test/seedream_image_20251212_230645.png |

⚡ 速度对比: doubao-seedream-4-5 快 2.78 秒

================================================================================
💡 提示:
   1. 请手动查看生成的图片并对比质量
   2. 考虑提示词风格、分辨率、生成速度等因素
   3. 可以多次测试不同的提示词以获得更全面的对比
================================================================================
```

## 🔍 评估维度

对比两个模型时，请考虑以下维度：

### 1. 图片质量
- ✅ 细节是否丰富
- ✅ 色彩是否自然
- ✅ 构图是否合理
- ✅ 是否符合提示词要求

### 2. 风格一致性
- ✅ 是否保持明日方舟二次元风格
- ✅ 角色特征是否准确
- ✅ 场景氛围是否到位

### 3. 特殊效果
- ✅ 水雾、反射等特殊效果是否自然
- ✅ 光影效果是否真实
- ✅ 景深、bokeh 等摄影效果是否明显

### 4. 性能指标
- ✅ 生成速度（秒）
- ✅ 文件大小（KB）
- ✅ 成功率

### 5. 性感度和魅力度（自拍专用）
- ✅ 姿态是否性感优雅
- ✅ 服装是否时尚大胆
- ✅ 表情是否有魅力
- ✅ 身材曲线是否突出

## 📸 查看生成的图片

### 本地测试

图片保存在：`/tmp/model_comparison_test/`

```bash
# 查看生成的图片列表
ls -lh /tmp/model_comparison_test/

# 使用预览打开（macOS）
open /tmp/model_comparison_test/gpt_image_*.png
open /tmp/model_comparison_test/seedream_image_*.png
```

### 服务器测试

```bash
# 从服务器复制图片到本地
scp root@115.190.143.80:/tmp/model_comparison_test/*.png ./local_test_images/

# 或者在服务器上查看
ssh root@115.190.143.80 "ls -lh /tmp/model_comparison_test/"
```

## 🎯 决策建议

根据测试结果，选择模型时考虑：

### 选择 gpt-image-1-all 的理由
- ✅ 图片质量更稳定
- ✅ 对提示词理解更准确
- ✅ 风格一致性更好
- ✅ 已经过实际使用验证

### 选择 doubao-seedream-4-5 的理由
- ✅ 生成速度更快
- ✅ 支持更高分辨率（2K）
- ✅ 特殊效果更出色
- ✅ 支持 image-to-image 功能

## 🔄 切换模型

如果决定切换到 SeeDream 模型，需要修改 `services/image_generation_service.py`：

### 当前配置（gpt-image-1-all）

```python
payload = {
    "size": "1024x1536",
    "prompt": prompt,
    "model": "gpt-image-1-all",
    "n": 1
}
```

### 切换到 SeeDream

```python
payload = {
    "model": "doubao-seedream-4-5-251128",
    "prompt": prompt,
    "size": "2K",  # SeeDream 支持 2K 分辨率
    "watermark": False
}
```

**注意**：切换后需要重新部署服务器。

## ⚠️ 注意事项

1. **API KEY** - 确保 `IMAGE_GENERATION_API_KEY` 已正确配置
2. **网络连接** - 生成图片需要网络连接，超时时间为 300 秒
3. **存储空间** - 测试会生成大量图片，注意清理 `/tmp/model_comparison_test/`
4. **并发测试** - 不要同时运行多个测试，可能导致 API 限流
5. **提示词质量** - 高质量的提示词才能准确对比模型效果

## 🧹 清理测试文件

```bash
# 清理本地测试图片
rm -rf /tmp/model_comparison_test/

# 清理服务器测试图片
ssh root@115.190.143.80 "rm -rf /tmp/model_comparison_test/"
```

## 📞 故障排查

### 问题 1：API KEY 错误

```
❌ 错误: 未设置 IMAGE_GENERATION_API_KEY 环境变量
```

**解决方案**：
```bash
export IMAGE_GENERATION_API_KEY="your-key-here"
```

### 问题 2：连接超时

```
❌ 生成失败: timeout
```

**解决方案**：
- 检查网络连接
- 增加 timeout 时间
- 稍后重试

### 问题 3：API 返回错误

```
❌ 生成失败: API 请求失败
```

**解决方案**：
- 检查 API KEY 是否有效
- 检查 API URL 是否正确
- 查看详细错误信息

## 📚 相关文档

- `DEPLOYMENT.md` - 部署操作指南
- `IMAGE_GENERATION_REFACTOR_SUMMARY.md` - 图片生成系统重构总结
- `CLAUDE.md` - 项目整体说明

---

**最后更新**: 2025-12-12
**创建者**: Claude Sonnet 4.5
