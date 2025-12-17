import asyncio
import sys
import os
import sys

# 添加项目根目录到 python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ai_service import analyze_intimacy_event
from utils.postgres_service import init_intimacy_table, insert_intimacy_record
from utils.logging_config import get_logger

logger = get_logger(__name__)

async def test_gallery_flow():
    print("🚀 开始测试 CG Gallery 流程...")
    
    # 1. 模拟对话历史
    mock_history = [
        {"role": "user", "content": "（手指深入）感觉怎么样？"},
        {"role": "assistant", "content": "唔...（身体颤抖）太深了...但是在里面..."},
        {"role": "user", "content": "要去了吗？全部给你。"},
        {"role": "assistant", "content": "啊...！不行了...（弓起腰，手指抓紧床单）要坏掉了...！"},
        # 假设这里触发了 Release
    ]
    
    print(f"📄 模拟对话历史: {len(mock_history)} 条")
    
    # 2. 确保表存在
    print("🛠️ 初始化数据库表...")
    init_intimacy_table()
    
    # 3. 调用 AI 分析
    print("🧠 调用 AI 分析 (可能需要几秒钟)...")
    analysis = await analyze_intimacy_event(mock_history)
    
    if analysis:
        print("\n✅ AI 分析成功！结果如下：")
        print(f"部位: {analysis.get('body_part')}")
        print(f"行为: {analysis.get('act_type')}")
        print(f"强度: {analysis.get('intensity')}")
        print(f"摘要: {analysis.get('summary')}")
        print(f"Tags: {analysis.get('tags')}")
        print("-" * 30)
        print(f"完整故事: {analysis.get('full_story')}")
        print("-" * 30)
        
        # 4. 存入数据库
        print("💾 正在存入数据库...")
        try:
            record_id = insert_intimacy_record(analysis)
            print(f"✅ 存储成功！Record ID: {record_id}")
            print(f"🔍 你可以通过 /gallery/record/{record_id} 查看")
        except Exception as e:
            print(f"❌ 存储失败: {e}")
    else:
        print("❌ AI 分析返回为空或失败")

if __name__ == "__main__":
    asyncio.run(test_gallery_flow())
