#!/usr/bin/env python3
"""
from utils.logging_config import get_logger

logger = get_logger(__name__)

验证图片生成API Key配置的脚本
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def mask_api_key(key):
    """安全地显示API Key（隐藏中间部分）"""
    if not key:
        return "未设置"
    if len(key) < 20:
        return "***"
    return f"{key[:10]}...{key[-6:]}"

def verify_config():
    """验证配置"""
    print("🔍 验证图片生成API配置:")
    print("=" * 50)
    
    try:
        from app.config import settings
        
        # 检查新的图片生成API Key
        img_api_key = settings.IMAGE_GENERATION_API_KEY
        img_api_url = settings.IMAGE_GENERATION_API_URL
        
        print(f"📝 配置项检查:")
        print(f"   IMAGE_GENERATION_API_KEY: {mask_api_key(img_api_key)}")
        print(f"   IMAGE_GENERATION_API_URL: {img_api_url}")
        
        # 验证API Key格式
        if img_api_key and img_api_key.startswith('sk-') and len(img_api_key) > 40:
            print("✅ 图片生成API Key格式正确")
        elif not img_api_key:
            print("❌ 图片生成API Key未设置")
            return False
        else:
            print("⚠️ 图片生成API Key格式可能不正确")
        
        # 验证URL
        if img_api_url and 'yunwu.ai' in img_api_url:
            print("✅ 图片生成API URL配置正确")
        else:
            print("⚠️ 图片生成API URL配置可能不正确")
        
        return bool(img_api_key)
        
    except Exception as e:
        print(f"❌ 配置验证失败: {e}")
        return False

def verify_service():
    """验证服务配置"""
    print(f"\n🎨 验证图片生成服务:")
    print("=" * 50)
    
    try:
        from services.image_generation_service import image_generation_service
        
        # 检查服务实例配置
        api_key = image_generation_service.api_key
        gen_url = image_generation_service.generation_url
        edit_url = image_generation_service.edit_url
        
        print(f"📝 服务配置检查:")
        print(f"   API Key: {mask_api_key(api_key)}")
        print(f"   生成URL: {gen_url}")
        print(f"   编辑URL: {edit_url}")
        
        # 检查超时配置
        print(f"   生成超时: {image_generation_service.generation_timeout}秒")
        print(f"   自拍超时: {image_generation_service.selfie_timeout}秒")
        print(f"   下载超时: {image_generation_service.download_timeout}秒")
        
        if api_key and gen_url and edit_url:
            print("✅ 图片生成服务配置完整")
            return True
        else:
            print("❌ 图片生成服务配置不完整")
            return False
        
    except Exception as e:
        print(f"❌ 服务验证失败: {e}")
        return False

def verify_bark_notifier():
    """验证Bark通知服务"""
    print(f"\n📢 验证Bark通知服务:")
    print("=" * 50)
    
    try:
        from services.bark_notifier import bark_notifier
        
        print(f"📝 Bark配置检查:")
        print(f"   Base URL: {bark_notifier.base_url}")
        print(f"   API Key: {bark_notifier.api_key}")
        
        if hasattr(bark_notifier, 'api_key'):
            print("✅ Bark通知服务配置正常")
            return True
        else:
            print("❌ Bark通知服务配置异常")
            return False
        
    except Exception as e:
        print(f"❌ Bark通知服务验证失败: {e}")
        return False

def main():
    """主函数"""
    print("🚀 图片生成API配置验证工具")
    print(f"📅 配置的API Key: sk-ohCxo0MtUuQ8PkTX0r...4ucQUuKILJw")
    print()
    
    # 验证各个组件
    config_ok = verify_config()
    service_ok = verify_service()
    bark_ok = verify_bark_notifier()
    
    print(f"\n🏁 验证结果:")
    print("=" * 50)
    
    if config_ok and service_ok and bark_ok:
        print("🎉 所有配置验证通过！")
        print("💡 接下来可以:")
        print("   1. 重启Docker服务: docker-compose restart bot")
        print("   2. 运行图片生成测试: python scripts/test_image_generation_debug.py")
    else:
        print("❌ 部分配置验证失败")
        if not config_ok:
            print("   - 请检查.env文件中的IMAGE_GENERATION_API_KEY配置")
        if not service_ok:
            print("   - 请检查图片生成服务配置")
        if not bark_ok:
            print("   - 请检查Bark通知服务配置")
    
    print(f"\n🔄 记住重启服务以应用新配置:")
    print("   docker-compose restart bot celery-worker celery-beat")

if __name__ == "__main__":
    main()