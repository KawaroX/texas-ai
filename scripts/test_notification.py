#!/usr/bin/env python3
"""
from utils.logging_config import get_logger

logger = get_logger(__name__)

测试图片分析通知功能

⚠️ 注意：此测试脚本已废弃
原因：image_content_analyzer.py 已重构，send_analysis_notification 功能已移除
建议：使用 scene_pre_analyzer.py 中的通知功能替代
"""

import asyncio
import sys
from pathlib import Path

print("⚠️ 此测试脚本已废弃：image_content_analyzer.py 已重构")
print("🔄 请使用 scene_pre_analyzer.py 中的新通知系统")
sys.exit(1)

# 已废弃的代码 - 保留用于参考
# from services.image_content_analyzer import send_analysis_notification


async def test_success_notification():
    """测试成功通知"""
    print("🧪 测试成功通知...")
    
    await send_analysis_notification(
        image_path="/test/sample_image.png",
        success=True,
        description="德克萨斯在企鹅物流办公室查看文件，桌上放着咖啡杯和一些重要资料"
    )
    print("✅ 成功通知测试完成")


async def test_failure_notification():
    """测试失败通知"""
    print("\n🧪 测试失败通知...")
    
    await send_analysis_notification(
        image_path="/test/sample_image.png",
        success=False,
        error="API请求失败: 429 - Rate limit exceeded. Please try again later."
    )
    print("✅ 失败通知测试完成")


async def main():
    """主测试函数"""
    print("📢 图片分析通知功能测试")
    print("=" * 50)
    
    try:
        # 测试成功通知
        await test_success_notification()
        
        # 等待一下再发送第二个
        await asyncio.sleep(2)
        
        # 测试失败通知
        await test_failure_notification()
        
        print("\n🎉 所有测试完成！")
        print("💡 请检查Mattermost频道是否收到了通知消息")
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())