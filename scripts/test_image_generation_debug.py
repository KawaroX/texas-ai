#!/usr/bin/env python3
"""
调试图片生成问题的脚本
"""

import asyncio
import sys
import os
import logging

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_imports():
    """测试所有必要的导入"""
    logger.info("🔍 测试导入...")
    
    try:
        from app.config import settings
        logger.info("✅ settings导入成功")
    except Exception as e:
        logger.error(f"❌ settings导入失败: {e}")
        return False
    
    try:
        from services.bark_notifier import bark_notifier
        logger.info("✅ bark_notifier导入成功")
        logger.info(f"   bark_notifier.api_key = {getattr(bark_notifier, 'api_key', 'NOT_FOUND')}")
    except Exception as e:
        logger.error(f"❌ bark_notifier导入失败: {e}")
        return False
    
    try:
        from services.image_generation_service import image_generation_service
        logger.info("✅ image_generation_service导入成功")
    except Exception as e:
        logger.error(f"❌ image_generation_service导入失败: {e}")
        return False
        
    return True


async def test_basic_image_generation():
    """测试基本的图片生成功能"""
    logger.info("🎨 测试图片生成...")
    
    try:
        from services.image_generation_service import image_generation_service
        
        # 测试简单的场景图生成
        test_content = "测试图片生成：在公园里散步"
        logger.info(f"尝试生成场景图: {test_content}")
        
        image_path = await image_generation_service.generate_image_from_prompt(test_content)
        
        if image_path:
            logger.info(f"✅ 场景图生成成功: {image_path}")
            return True
        else:
            logger.warning("⚠️ 场景图生成返回None")
            return False
            
    except Exception as e:
        logger.error(f"❌ 图片生成测试失败: {e}", exc_info=True)
        return False


async def test_selfie_generation():
    """测试自拍生成功能"""
    logger.info("📸 测试自拍生成...")
    
    try:
        from services.image_generation_service import image_generation_service
        
        test_content = "测试自拍生成：在咖啡店里休息"
        logger.info(f"尝试生成自拍: {test_content}")
        
        image_path = await image_generation_service.generate_selfie(test_content)
        
        if image_path:
            logger.info(f"✅ 自拍生成成功: {image_path}")
            return True
        else:
            logger.warning("⚠️ 自拍生成返回None")
            return False
            
    except Exception as e:
        logger.error(f"❌ 自拍生成测试失败: {e}", exc_info=True)
        return False


def test_bark_notifier():
    """测试Bark通知服务"""
    logger.info("📢 测试Bark通知...")
    
    try:
        from services.bark_notifier import bark_notifier
        
        # 测试属性
        logger.info(f"bark_notifier.base_url = {getattr(bark_notifier, 'base_url', 'NOT_FOUND')}")
        logger.info(f"bark_notifier.api_key = {getattr(bark_notifier, 'api_key', 'NOT_FOUND')}")
        
        # 尝试异步调用
        async def test_notification():
            await bark_notifier.send_notification(
                title="测试通知",
                body="这是一条测试通知",
                group="TexasAITest"
            )
        
        asyncio.run(test_notification())
        logger.info("✅ Bark通知测试完成")
        return True
        
    except Exception as e:
        logger.error(f"❌ Bark通知测试失败: {e}", exc_info=True)
        return False


def test_config():
    """测试配置"""
    logger.info("⚙️ 测试配置...")
    
    try:
        from app.config import settings
        
        logger.info(f"OPENAI_API_KEY存在: {bool(getattr(settings, 'OPENAI_API_KEY', None))}")
        logger.info(f"REDIS_URL存在: {bool(getattr(settings, 'REDIS_URL', None))}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ 配置测试失败: {e}")
        return False


async def main():
    """主函数"""
    logger.info("🚀 开始图片生成调试")
    
    # 1. 测试导入
    if not test_imports():
        logger.error("❌ 导入测试失败，停止测试")
        return
    
    # 2. 测试配置
    if not test_config():
        logger.error("❌ 配置测试失败，停止测试")
        return
    
    # 3. 测试Bark通知
    test_bark_notifier()
    
    # 4. 测试图片生成 (如果前面的测试都通过)
    logger.info("开始图片生成测试...")
    
    # 测试场景图生成
    await test_basic_image_generation()
    
    # 测试自拍生成
    await test_selfie_generation()
    
    logger.info("🎉 调试测试完成！")


if __name__ == "__main__":
    asyncio.run(main())