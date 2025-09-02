#!/usr/bin/env python3
"""
测试优化后的自拍生成功能
"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(__file__))

def test_multipart_method():
    """测试multipart数据构建方法"""
    from services.image_generation_service import ImageGenerationService
    import asyncio
    
    # 模拟测试数据
    test_image_data = b"fake_image_data_for_testing"
    test_prompt = "测试prompt内容"
    
    service = ImageGenerationService()
    
    async def run_test():
        result = await service._build_multipart_data(test_image_data, test_prompt)
        
        print("🧪 Multipart 数据构建测试:")
        print(f"   Content-Type: {result['content_type']}")
        print(f"   Body 长度: {len(result['body'])} bytes")
        print("   Body 前100字符预览:")
        try:
            preview = result['body'][:100].decode('utf-8', errors='ignore')
            print(f"   {preview}")
        except:
            print(f"   {result['body'][:100]}")
    
    asyncio.run(run_test())

def test_local_image_manager():
    """测试本地图片管理器"""
    try:
        from services.selfie_base_image_manager import selfie_manager
        
        print("📂 本地图片管理器测试:")
        
        # 检查状态
        status = selfie_manager.check_images_status()
        print(f"   配置的底图数量: {status['total_configured']}")
        print(f"   已下载数量: {status['total_downloaded']}")
        print(f"   缺失数量: {len(status['missing'])}")
        
        if status['available']:
            print("   可用的底图:")
            for img in status['available']:
                print(f"     📸 {img['filename']} ({img['size']} bytes)")
        
        # 测试随机选择
        random_path = selfie_manager.get_random_local_image()
        if random_path:
            print(f"   随机选择的底图: {os.path.basename(random_path)}")
        else:
            print("   ❌ 没有可用的本地底图")
            
    except ImportError as e:
        print(f"❌ 导入错误: {e}")
    except Exception as e:
        print(f"❌ 测试错误: {e}")

if __name__ == "__main__":
    print("🔧 优化后的自拍生成功能测试")
    print("=" * 50)
    
    print("\n1. 测试 Multipart 数据构建方法:")
    test_multipart_method()
    
    print("\n2. 测试本地图片管理器:")
    test_local_image_manager()
    
    print("\n✅ 测试完成")