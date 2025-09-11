#!/usr/bin/env python3
"""
from utils.logging_config import get_logger

logger = get_logger(__name__)

测试新的AI场景预分析系统
"""
import asyncio
import json
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.scene_pre_analyzer import analyze_scene


async def test_scene_analysis():
    """测试场景分析功能"""
    
    # 测试数据：模拟一个经历事件
    test_scene_data = {
        "id": "test-001",
        "content": "在十字路口前，车流彻底停滞。红灯的倒计时漫长得像是静止。她放下车窗，一股热浪夹杂着食物的香气和尾气味涌入车内。不远处一家面馆的伙计正大声招揽着客人，几个上班族行色匆匆地从车旁跑过。她看着这幅喧闹的城市画卷，表情没有变化。",
        "emotions": "平静",
        "end_time": "09:40",
        "thoughts": "这种无谓的等待最消耗精力。不过，也算是工作的一部分。不知道能天使今天有没有赖床。",
        "start_time": "09:15",
        "need_interaction": True,
        "interaction_content": "堵在路上了。看到一家面馆的招牌，突然有点想吃辣。任务结束后要不要去试试。"
    }
    
    print("🔍 测试AI场景预分析系统")
    print("=" * 50)
    
    # 测试场景模式分析
    print("\n📸 测试场景模式分析:")
    scene_result = await analyze_scene(test_scene_data, is_selfie=False)
    
    if scene_result:
        print("✅ 场景分析成功!")
        print(f"📝 描述: {scene_result.get('description', 'N/A')}")
        print(f"👥 角色: {scene_result.get('characters', [])}")
        print(f"📍 地点: {scene_result.get('location', 'N/A')}")
        print(f"⏰ 时间氛围: {scene_result.get('time_atmosphere', 'N/A')}")
        print(f"😊 情感状态: {scene_result.get('emotional_state', 'N/A')}")
        print(f"🌤️ 天气环境: {scene_result.get('weather_context', 'N/A')}")
        print(f"🎬 活动背景: {scene_result.get('activity_background', 'N/A')}")
        print(f"💡 光线氛围: {scene_result.get('lighting_mood', 'N/A')}")
        print(f"🖼️ 构图风格: {scene_result.get('composition_style', 'N/A')}")
        print(f"🎨 色彩基调: {scene_result.get('color_tone', 'N/A')}")
        print(f"🎯 画面重点: {scene_result.get('scene_focus', 'N/A')}")
        
        character_expressions = scene_result.get('character_expressions', [])
        if character_expressions:
            print(f"😀 角色表情:")
            for expr in character_expressions:
                print(f"  - {expr.get('name', 'Unknown')}: {expr.get('expression', 'N/A')}")
    else:
        print("❌ 场景分析失败!")
    
    # 测试自拍模式分析
    print("\n🤳 测试自拍模式分析:")
    selfie_result = await analyze_scene(test_scene_data, is_selfie=True)
    
    if selfie_result:
        print("✅ 自拍分析成功!")
        print(f"📝 描述: {selfie_result.get('description', 'N/A')}")
        print(f"👥 角色: {selfie_result.get('characters', [])}")
        
        # 检查是否包含德克萨斯
        characters = selfie_result.get('characters', [])
        if '德克萨斯' in characters:
            print("✅ 自拍模式正确包含德克萨斯")
        else:
            print("⚠️ 自拍模式缺少德克萨斯角色")
            
        character_expressions = selfie_result.get('character_expressions', [])
        if character_expressions:
            print(f"😀 角色表情:")
            for expr in character_expressions:
                print(f"  - {expr.get('name', 'Unknown')}: {expr.get('expression', 'N/A')}")
    else:
        print("❌ 自拍分析失败!")
    
    print("\n" + "=" * 50)
    print("🏁 测试完成")


async def test_character_detection():
    """测试角色检测的准确性"""
    print("\n🔍 测试角色检测准确性")
    print("-" * 30)
    
    # 测试包含角色名的场景
    test_cases = [
        {
            "name": "明确提及能天使",
            "data": {
                "id": "test-002",
                "content": "和能天使一起在企鹅物流的办公室里整理快递包裹。",
                "interaction_content": "能天使又在偷懒，不过这种轻松的氛围还不错。"
            },
            "expected_chars": ["能天使"]
        },
        {
            "name": "容易误判的文本",
            "data": {
                "id": "test-003", 
                "content": "空气中弥漫着咖啡的香味，让人想起能天使平时的习惯。",
                "interaction_content": "这种空气让我想到了能天使，但她今天不在这里。"
            },
            "expected_chars": []  # 不应该检测到"空"和"能天使"，因为只是想到而非在场
        },
        {
            "name": "多角色场景",
            "data": {
                "id": "test-004",
                "content": "在休息室里，能天使和可颂正在讨论今天的配送路线。",
                "interaction_content": "看起来今天又要和能天使、可颂一起行动了。"
            },
            "expected_chars": ["能天使", "可颂"]
        }
    ]
    
    for test_case in test_cases:
        print(f"\n测试案例: {test_case['name']}")
        result = await analyze_scene(test_case['data'], is_selfie=False)
        
        if result:
            detected = result.get('characters', [])
            expected = test_case['expected_chars']
            
            print(f"期望角色: {expected}")
            print(f"检测角色: {detected}")
            
            if set(detected) == set(expected):
                print("✅ 角色检测准确")
            else:
                print("⚠️ 角色检测存在差异")
        else:
            print("❌ 分析失败")


if __name__ == "__main__":
    asyncio.run(test_scene_analysis())
    asyncio.run(test_character_detection())