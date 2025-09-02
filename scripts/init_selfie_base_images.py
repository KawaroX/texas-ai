#!/usr/bin/env python3
"""
初始化德克萨斯自拍底图的脚本
下载并本地化所有底图文件
"""

import asyncio
import sys
import os
import logging

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.selfie_base_image_manager import selfie_manager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """主函数"""
    print("🖼️ 德克萨斯自拍底图初始化工具")
    print("=" * 50)
    
    # 检查当前状态
    status = selfie_manager.check_images_status()
    print(f"📊 当前状态:")
    print(f"   配置的底图数量: {status['total_configured']}")
    print(f"   已下载数量: {status['total_downloaded']}")
    print(f"   缺失数量: {len(status['missing'])}")
    
    if status['missing']:
        print(f"\n🔽 需要下载的底图:")
        for i, url in enumerate(status['missing'], 1):
            print(f"   {i}. {url}")
        
        # 开始下载
        print(f"\n🚀 开始下载底图...")
        results = await selfie_manager.download_all_images()
        
        # 显示结果
        print(f"\n📋 下载结果:")
        for url, success in results.items():
            status_icon = "✅" if success else "❌"
            print(f"   {status_icon} {url}")
        
        # 最终状态
        final_status = selfie_manager.check_images_status()
        print(f"\n🎉 完成! 总计: {final_status['total_downloaded']}/{final_status['total_configured']} 成功")
        
        if final_status['available']:
            print(f"\n📂 可用的底图文件:")
            for img in final_status['available']:
                print(f"   📸 {img['filename']} ({img['size']} bytes)")
    else:
        print(f"\n✅ 所有底图都已下载完成!")
        
        if status['available']:
            print(f"\n📂 可用的底图文件:")
            for img in status['available']:
                print(f"   📸 {img['filename']} ({img['size']} bytes)")
    
    # 测试随机选择
    print(f"\n🎲 测试随机选择底图:")
    random_image = selfie_manager.get_random_local_image()
    if random_image:
        print(f"   选中: {os.path.basename(random_image)}")
        print(f"   路径: {random_image}")
    else:
        print("   ❌ 没有可用的底图")

if __name__ == "__main__":
    asyncio.run(main())