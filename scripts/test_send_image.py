import asyncio
import logging
import os

# 确保脚本可以找到 app 模块
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.mattermost_client import MattermostWebSocketClient
from app.main import setup_logging

# --- SVG 图片创建函数 ---
def create_test_svg_image(path: str):
    """在指定路径创建一个简单的SVG格式的测试图片。"""
    svg_content = '''
    <svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
        <rect width="100" height="100" fill="#f0f0f0" />
        <text x="50%" y="50%" font-family="sans-serif" font-size="14" fill="#333" text-anchor="middle" dy=".3em">
            TEST IMG
        </text>
    </svg>
    '''
    with open(path, 'w') as f:
        f.write(svg_content)
    logging.info(f"✅ 已在 {path} 创建测试SVG图片。")

async def main():
    """测试发送带图片的消息到 kawaro 的私聊频道。"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("--- 开始执行图片发送测试脚本 ---")

    # 1. 定义测试图片路径和测试消息
    test_image_path = os.path.join(os.path.dirname(__file__), "test_image.svg")
    test_message = "🤖 这是一条来自测试脚本的图片消息。如果能看到一个带文字的方块图片，说明功能正常。"

    # 动态创建测试图片
    create_test_svg_image(test_image_path)

    # 2. 初始化 Mattermost 客户端
    ws_client = MattermostWebSocketClient()
    logger.info("Mattermost 客户端已初始化。")

    # 3. 获取与 kawaro 的私聊频道信息
    logger.info("正在获取 'kawaro' 的私聊频道信息...")
    kawaro_info = await ws_client.get_kawaro_user_and_dm_info()
    if not kawaro_info or not kawaro_info.get("channel_id"):
        logger.error("❌ 未能获取到 'kawaro' 的私聊频道信息，测试终止。")
        return
    
    channel_id = kawaro_info["channel_id"]
    logger.info(f"✅ 成功获取到私聊频道 ID: {channel_id}")

    # 4. 调用发送带图片消息的方法
    logger.info(f"准备向频道 {channel_id} 发送图片 {test_image_path}...")
    try:
        await ws_client.post_message_with_image(
            channel_id=channel_id,
            message=test_message,
            image_path=test_image_path
        )
        logger.info("✅ 图片消息发送调用完成。请检查 Mattermost 是否收到。")
    except Exception as e:
        logger.error(f"❌ 调用 post_message_with_image 时发生异常: {e}", exc_info=True)
    finally:
        # 清理测试图片
        if os.path.exists(test_image_path):
            os.remove(test_image_path)
            logger.info(f"🗑️ 已清理测试图片: {test_image_path}")

    logger.info("--- 图片发送测试脚本执行完毕 ---")


if __name__ == "__main__":
    asyncio.run(main())