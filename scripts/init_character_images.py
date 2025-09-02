#!/usr/bin/env python3
"""
角色图片初始化脚本
下载并管理明日方舟角色的基础图片
"""
import sys
import os
import asyncio

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.character_manager import character_manager

async def main():
    print("🎭 明日方舟角色图片初始化工具")
    print("=" * 50)
    
    # 检查当前状态
    status = character_manager.get_characters_status()
    print(f"📊 当前状态:")
    print(f"   配置的角色数量: {status['total_configured']}")
    print(f"   已下载数量: {status['total_downloaded']}")
    print(f"   缺失数量: {len(status['missing'])}")
    
    if status['missing']:
        print(f"\n🔽 需要下载的角色:")
        for i, name in enumerate(status['missing'], 1):
            print(f"   {i}. {name}")
        
        print(f"\n🚀 开始下载角色图片...")
        results = await character_manager.download_all_characters()
        
        print(f"\n📋 下载结果:")
        for result in results:
            print(f"   {result}")
    else:
        print(f"\n✅ 所有角色图片都已下载完成！")
    
    # 显示最终状态
    final_status = character_manager.get_characters_status()
    if final_status['available']:
        print(f"\n📂 可用的角色图片:")
        for char in final_status['available']:
            print(f"   🎭 {char['name']}: {char['filename']} ({char['size']} bytes)")
    
    # 测试角色检测功能
    test_text = "今天能天使和可颂一起在办公室整理文件，大帝在一旁指导工作"
    detected = character_manager.detect_characters_in_text(test_text)
    print(f"\n🔍 测试角色检测:")
    print(f"   测试文本: {test_text}")
    print(f"   检测到的角色: {detected}")
    
    success_count = len([r for r in results if r.startswith("✅")]) if 'results' in locals() else final_status['total_downloaded']
    total_count = final_status['total_configured']
    
    print(f"\n🎉 完成! 总计: {success_count}/{total_count} 成功")

if __name__ == "__main__":
    asyncio.run(main())