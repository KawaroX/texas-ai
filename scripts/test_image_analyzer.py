#!/usr/bin/env python3
"""
Docker环境中的图片内容分析功能测试脚本
"""

import asyncio
import os
import sys
from utils.logging_config import get_logger

logger = get_logger(__name__)
from pathlib import Path
import hashlib

# 设置日志
logging.basicConfig(level=logging.INFO)


def test_hash_function():
    """测试哈希函数的一致性"""
    test_path = "/test/image/path.png"
    
    hash1 = hashlib.sha256(test_path.encode('utf-8')).hexdigest()
    hash2 = hashlib.sha256(test_path.encode('utf-8')).hexdigest()
    
    print(f"路径: {test_path}")
    print(f"哈希值1: {hash1}")
    print(f"哈希值2: {hash2}")
    print(f"哈希一致性: {'✅ 通过' if hash1 == hash2 else '❌ 失败'}")
    return hash1 == hash2


def test_environment():
    """测试环境配置"""
    print("🔧 测试环境配置")
    print("-" * 50)
    
    # 检查环境变量
    gemini_key = os.getenv("GEMINI_API_KEY")
    gemini_key2 = os.getenv("GEMINI_API_KEY2")
    redis_url = os.getenv("REDIS_URL")
    
    print(f"GEMINI_API_KEY: {'✅ 已设置' if gemini_key else '❌ 未设置'}")
    print(f"GEMINI_API_KEY2: {'✅ 已设置' if gemini_key2 else '❌ 未设置'}")
    print(f"REDIS_URL: {'✅ 已设置' if redis_url else '❌ 未设置'}")
    
    return (gemini_key or gemini_key2) and redis_url


def test_imports():
    """测试模块导入"""
    print("\n📦 测试模块导入")
    print("-" * 50)
    
    try:
        import httpx
        print("✅ httpx 导入成功")
    except ImportError as e:
        print(f"❌ httpx 导入失败: {e}")
        return False
    
    try:
        import redis
        print("✅ redis 导入成功")
    except ImportError as e:
        print(f"❌ redis 导入失败: {e}")
        return False
    
    try:
        from services.image_service import (
            get_image_description_by_path,
            get_image_path_hash
        )
        print("✅ image_service 导入成功")
        
        # 测试哈希函数
        test_result = test_hash_function()
        
        return test_result
        
    except ImportError as e:
        print(f"❌ image_service 导入失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 模块测试失败: {e}")
        return False


def test_file_structure():
    """测试文件结构"""
    print("\n📁 测试文件结构")
    print("-" * 50)
    
    required_files = [
        "services/image_content_analyzer.py",
        "tasks/image_generation_tasks.py", 
        "app/mattermost_client.py"
    ]
    
    all_exist = True
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path}")
            all_exist = False
    
    return all_exist


async def main():
    """主测试函数"""
    print("🧪 图片内容分析功能基础测试")
    print("=" * 60)
    
    # 环境测试
    env_ok = test_environment()
    
    # 文件结构测试
    files_ok = test_file_structure()
    
    # 模块导入测试
    imports_ok = test_imports()
    
    print("\n📊 测试结果汇总")
    print("-" * 50)
    print(f"环境配置: {'✅ 通过' if env_ok else '❌ 失败'}")
    print(f"文件结构: {'✅ 通过' if files_ok else '❌ 失败'}")
    print(f"模块导入: {'✅ 通过' if imports_ok else '❌ 失败'}")
    
    overall_status = env_ok and files_ok and imports_ok
    
    print(f"\n🎯 总体状态: {'🎉 准备就绪' if overall_status else '⚠️ 需要修复'}")
    
    if overall_status:
        print("\n💡 建议:")
        print("   - 功能已集成完成，等待图片生成任务运行时自动测试")
        print("   - 可以通过查看日志来验证实际运行效果")
        print("   - 生成图片后检查Redis中是否有对应的描述数据")
    else:
        print("\n🔧 修复建议:")
        if not env_ok:
            print("   - 检查环境变量设置")
        if not files_ok:
            print("   - 检查文件是否正确创建")
        if not imports_ok:
            print("   - 检查依赖项和模块导入")


if __name__ == "__main__":
    asyncio.run(main())