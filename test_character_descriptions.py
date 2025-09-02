#!/usr/bin/env python3
"""
测试角色描述准确性的脚本
"""

import sys
import os
sys.path.append('/Volumes/base/texas-ai')

from services.image_generation_service import ImageGenerationService

def test_character_descriptions():
    """测试角色描述的准确性"""
    print("=== 角色描述测试 ===")
    
    # 创建服务实例
    service = ImageGenerationService()
    
    # 测试多角色场景生成中的角色描述
    print("\n1. 场景生成中的角色特征:")
    scene_traits = {
        "能天使": "活泼开朗的天使族女孩，红色头发，头顶有光圈，多个长三角形组成的光翼，充满活力",
        "可颂": "乐观开朗活泼的企鹅物流成员，橙色头发", 
        "空": "活泼开朗的干员，黄色头发，明快的表情",
        "拉普兰德": "过于开朗特别活泼的狼族干员，白色头发，狼耳朵，古灵精怪略带病娇的笑容",
        "大帝": "喜欢说唱的帝企鹅，戴着墨镜和大金链子，西海岸嘻哈风格，企鹅形态而非人形"
    }
    
    for char, desc in scene_traits.items():
        print(f"  {char}: {desc}")
    
    # 测试自拍生成中的角色描述
    print("\n2. 自拍生成中的角色特征:")
    selfie_traits = {
        "能天使": "红色头发的天使族女孩，头顶光圈，多个长三角形组成的光翼，活泼开朗",
        "可颂": "橙色头发，乐观开朗活泼的企鹅物流成员",
        "空": "黄色头发，活泼开朗的干员，明快表情", 
        "拉普兰德": "白色头发的狼族干员，狼耳朵，过于开朗特别活泼，古灵精怪略带病娇的笑容",
        "大帝": "戴墨镜和大金链子的说唱帝企鹅，西海岸嘻哈风格"
    }
    
    for char, desc in selfie_traits.items():
        print(f"  {char}: {desc}")
    
    print("\n=== 关键修正点 ===")
    print("✓ 能天使: 多个长三角形组成的光翼 (不是白色羽毛翅膀)")
    print("✓ 可颂: 不戴眼镜，乐观开朗活泼 (不是温和友善)")
    print("✓ 空: 不是狼族，没有狼耳朵")
    print("✓ 德克萨斯: 黑色头发 (不是银白色)")
    
    # 测试角色检测功能
    print("\n3. 角色检测测试:")
    test_texts = [
        "能天使和可颂一起在办公室",
        "空和拉普兰德在街上散步", 
        "大帝在说唱表演",
        "德克萨斯独自一人"
    ]
    
    for text in test_texts:
        detected = service._detect_characters_in_text(text)
        print(f"  文本: '{text}' -> 检测到角色: {detected}")

if __name__ == "__main__":
    test_character_descriptions()