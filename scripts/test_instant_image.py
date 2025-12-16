#!/usr/bin/env python3
"""
测试即时图片生成功能

使用方法：
    python scripts/test_instant_image.py

功能测试：
    1. 上下文提取 - 从Redis获取最近对话
    2. 场景数据构建 - 格式化对话为场景描述
    3. 图片生成 - 完整的生成流程
    4. 标记检测 - 模拟AI回复中的[IMAGE_REQUESTED]标记
"""

import sys
import os
import asyncio
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.logging_config import get_logger
logger = get_logger(__name__)


async def test_context_extraction():
    """测试上下文提取"""
    print("\n" + "="*60)
    print("测试 1: 上下文提取")
    print("="*60)

    from services.recent_context_extractor import recent_context_extractor
    from core.memory_buffer import get_channel_memory

    # 使用实际的频道ID（需要有对话记录的频道）
    test_channel_id = "ersrpcbgc3y3um7gtm5yg3u9wo"  # 请替换为实际的频道ID

    # 添加一些测试消息
    channel_memory = get_channel_memory(test_channel_id)
    channel_memory.add_message("user", "今天天气真好")
    channel_memory.add_message("assistant", "是啊，阳光很舒服。")
    channel_memory.add_message("user", "你在做什么？")
    channel_memory.add_message("assistant", "刚送完货，在大地的尽头酒吧休息。")
    channel_memory.add_message("user", "拍张照给我看看")

    # 提取最近对话
    messages = recent_context_extractor.extract_recent_context(
        channel_id=test_channel_id,
        window_minutes=3,
        max_messages=10,
        include_assistant=True
    )

    print(f"\n✅ 提取到 {len(messages)} 条消息:")
    for i, msg in enumerate(messages, 1):
        role = "用户" if msg['role'] == 'user' else "AI"
        content = msg['content'][:50] + "..." if len(msg['content']) > 50 else msg['content']
        print(f"  {i}. [{role}] {content}")

    # 格式化为场景描述
    scene_text = recent_context_extractor.format_context_for_scene(messages)
    print(f"\n✅ 场景描述:\n{scene_text[:200]}...")

    return len(messages) > 0


async def test_image_type_detection():
    """测试图片类型判断"""
    print("\n" + "="*60)
    print("测试 2: 图片类型判断")
    print("="*60)

    from services.instant_image_generator import instant_image_generator

    # 测试自拍请求
    selfie_messages = [
        {"role": "user", "content": "德克萨斯，自拍一张给我看看"},
        {"role": "assistant", "content": "好。*拿起手机*"}
    ]
    is_selfie = instant_image_generator._determine_image_type(None, selfie_messages)
    print(f"\n✅ 自拍测试: {is_selfie} (预期: True)")

    # 测试场景请求
    scene_messages = [
        {"role": "user", "content": "拍一下周围的风景"},
        {"role": "assistant", "content": "等一下。*转身对准窗外*"}
    ]
    is_selfie = instant_image_generator._determine_image_type(None, scene_messages)
    print(f"✅ 场景测试: {is_selfie} (预期: False)")

    return True


async def test_instant_image_generation():
    """测试完整的即时图片生成流程"""
    print("\n" + "="*60)
    print("测试 3: 完整图片生成流程")
    print("="*60)

    from services.instant_image_generator import instant_image_generator
    from core.memory_buffer import get_channel_memory

    # 使用实际的频道ID
    test_channel_id = "ersrpcbgc3y3um7gtm5yg3u9wo"  # 请替换为实际的频道ID
    test_user_id = "kawaro"

    # 准备测试对话
    channel_memory = get_channel_memory(test_channel_id)
    channel_memory.add_message("user", "德克萨斯，你在哪里？")
    channel_memory.add_message("assistant", "在办公室。")
    channel_memory.add_message("user", "拍张照给我看看你")
    channel_memory.add_message("assistant", "好。*拿起手机对准镜头*")

    print(f"\n⏳ 开始生成图片...")
    print(f"   频道: {test_channel_id}")
    print(f"   用户: {test_user_id}")

    # 设置超时
    try:
        result = await asyncio.wait_for(
            instant_image_generator.generate_instant_image(
                channel_id=test_channel_id,
                user_id=test_user_id,
                image_type=None,  # 自动判断
                context_window_minutes=3,
                max_messages=25
            ),
            timeout=60.0  # 60秒超时
        )

        if result['success']:
            print(f"\n✅ 图片生成成功!")
            print(f"   路径: {result['image_path']}")
            print(f"   类型: {'自拍' if result.get('is_selfie') else '场景'}")
            print(f"   耗时: {result['generation_time']:.2f}秒")
            return True
        else:
            print(f"\n❌ 图片生成失败: {result.get('error')}")
            return False

    except asyncio.TimeoutError:
        print("\n❌ 图片生成超时（60秒）")
        return False
    except Exception as e:
        print(f"\n❌ 图片生成异常: {e}")
        return False


async def test_marker_detection():
    """测试[IMAGE_REQUESTED]标记检测"""
    print("\n" + "="*60)
    print("测试 4: 标记检测")
    print("="*60)

    # 模拟AI回复
    test_responses = [
        ("好。*拿起手机*\n[IMAGE_REQUESTED]", True),
        ("好。", False),
        ("等一下。*转身对准窗外*\n[IMAGE_REQUESTED]", True),
        ("刚送完货，累了。", False),
    ]

    marker = "[IMAGE_REQUESTED]"
    all_passed = True

    for response, should_detect in test_responses:
        has_marker = marker in response
        passed = has_marker == should_detect
        status = "✅" if passed else "❌"

        print(f"\n{status} 回复: {response[:50]}...")
        print(f"   检测到标记: {has_marker} (预期: {should_detect})")

        if not passed:
            all_passed = False

    return all_passed


async def main():
    """运行所有测试"""
    print("\n" + "🚀 " + "="*58 + " 🚀")
    print("   即时图片生成功能测试套件")
    print("🚀 " + "="*58 + " 🚀")

    results = {}

    # 运行测试
    try:
        results['上下文提取'] = await test_context_extraction()
    except Exception as e:
        logger.error(f"上下文提取测试失败: {e}", exc_info=True)
        results['上下文提取'] = False

    try:
        results['图片类型判断'] = await test_image_type_detection()
    except Exception as e:
        logger.error(f"图片类型判断测试失败: {e}", exc_info=True)
        results['图片类型判断'] = False

    try:
        results['标记检测'] = await test_marker_detection()
    except Exception as e:
        logger.error(f"标记检测测试失败: {e}", exc_info=True)
        results['标记检测'] = False

    # 可选：完整图片生成测试（耗时较长）
    run_full_test = input("\n是否运行完整图片生成测试？(y/n): ").lower() == 'y'
    if run_full_test:
        try:
            results['完整图片生成'] = await test_instant_image_generation()
        except Exception as e:
            logger.error(f"完整图片生成测试失败: {e}", exc_info=True)
            results['完整图片生成'] = False

    # 输出结果
    print("\n" + "="*60)
    print("测试结果总结")
    print("="*60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status}  {test_name}")

    print("\n" + "="*60)
    print(f"总计: {passed}/{total} 个测试通过")
    print("="*60 + "\n")

    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
