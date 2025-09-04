#!/usr/bin/env python3
"""
监控主动交互图片生成和发送状态
"""

import redis
import os
import sys
from datetime import datetime
from typing import Dict, List

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.config import settings

# Redis 客户端
from utils.redis_manager import get_redis_client
redis_client = get_redis_client()

PROACTIVE_IMAGES_KEY = "proactive_interaction_images"


def get_image_mappings() -> Dict[str, str]:
    """获取所有图片映射"""
    try:
        return redis_client.hgetall(PROACTIVE_IMAGES_KEY)
    except Exception as e:
        print(f"❌ 获取图片映射失败: {e}")
        return {}


def check_image_files(mappings: Dict[str, str]) -> Dict[str, Dict]:
    """检查图片文件状态"""
    results = {}
    for experience_id, image_path in mappings.items():
        file_exists = os.path.exists(image_path) if image_path else False
        file_size = 0
        if file_exists:
            try:
                file_size = os.path.getsize(image_path)
            except:
                file_size = 0
        
        results[experience_id] = {
            "path": image_path,
            "exists": file_exists,
            "size_kb": file_size / 1024 if file_size > 0 else 0
        }
    return results


def get_interaction_events() -> List[Dict]:
    """获取今天的交互事件"""
    today = datetime.now().strftime('%Y-%m-%d')
    today_key = f"interaction_needed:{today}"
    
    try:
        events = redis_client.zrange(today_key, 0, -1, withscores=True)
        result = []
        for event_json, score in events:
            try:
                import json
                event_data = json.loads(event_json)
                event_data['scheduled_time'] = datetime.fromtimestamp(score).strftime('%H:%M:%S')
                result.append(event_data)
            except:
                continue
        return result
    except Exception as e:
        print(f"❌ 获取交互事件失败: {e}")
        return []


def get_interacted_events() -> List[str]:
    """获取已处理的事件ID"""
    today = datetime.now().strftime('%Y-%m-%d')
    interacted_key = f"interacted_schedule_items:{today}"
    
    try:
        return list(redis_client.smembers(interacted_key))
    except Exception as e:
        print(f"❌ 获取已处理事件失败: {e}")
        return []


def print_status_report():
    """打印状态报告"""
    print("=" * 60)
    print(f"🖼️  主动交互图片状态监控 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # 1. 图片映射状态
    print("\n📋 图片映射状态:")
    mappings = get_image_mappings()
    if not mappings:
        print("   暂无图片映射")
    else:
        file_status = check_image_files(mappings)
        for experience_id, info in file_status.items():
            status_icon = "✅" if info["exists"] else "📁"  # 📁 表示文件暂时不存在但映射保留
            size_info = f"({info['size_kb']:.1f}KB)" if info["exists"] else "(映射已保留)"
            print(f"   {status_icon} {experience_id}: {info['path']} {size_info}")
    
    # 2. 今日交互事件
    print(f"\n📅 今日交互事件:")
    events = get_interaction_events()
    if not events:
        print("   暂无待处理的交互事件")
    else:
        for event in events:
            event_id = event.get('id', 'Unknown')
            scheduled_time = event.get('scheduled_time', 'Unknown')
            content = event.get('interaction_content', '')[:50] + "..." if len(event.get('interaction_content', '')) > 50 else event.get('interaction_content', '')
            has_image = "🖼️" if event_id in mappings else "📝"
            print(f"   {has_image} {event_id} [{scheduled_time}]: {content}")
    
    # 3. 已处理事件
    print(f"\n✅ 已处理事件:")
    interacted = get_interacted_events()
    if not interacted:
        print("   今日暂无已处理的事件")
    else:
        for event_id in sorted(interacted):
            print(f"   ✓ {event_id}")
    
    # 4. 统计信息
    print(f"\n📊 统计信息:")
    print(f"   图片映射总数: {len(mappings)}")
    print(f"   待处理事件: {len(events)}")
    print(f"   已处理事件: {len(interacted)}")
    
    valid_images = sum(1 for info in check_image_files(mappings).values() if info["exists"])
    print(f"   有效图片: {valid_images}/{len(mappings)}")
    
    print("\n" + "=" * 60)


def main():
    """主函数"""
    try:
        # 测试Redis连接
        redis_client.ping()
        print_status_report()
    except Exception as e:
        print(f"❌ 连接Redis失败: {e}")


if __name__ == "__main__":
    main()