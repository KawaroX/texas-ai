import asyncio
import websockets


async def test():
    uri = "ws://localhost:8065/api/v4/websocket"
    async with websockets.connect(uri) as websocket:
        print("✅ Connected successfully")


asyncio.run(test())
