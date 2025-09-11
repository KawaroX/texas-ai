from utils.logging_config import get_logger

logger = get_logger(__name__)

import os
from mem0 import Memory


# 初始化 Mem0 使用 Qdrant
config = {
    "llm": {
        "provider": "openai",
        "config": {
            "api_key": os.environ["OPENAI_API_KEY"],
            "openai_base_url": "https://yunwu.ai/v1",
            "model": "gpt-4o-mini",
            "temperature": 0.3,
        },
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "test",
            "host": "qdrant",
            "port": 6333,
            "embedding_model_dims": 4096,
        },
    },
    "embedder": {
        "provider": "openai",
        "config": {
            "openai_base_url": "https://api.siliconflow.cn/v1",
            "api_key": os.environ["SILICON_API_KEY"],
            "model": "Qwen/Qwen3-Embedding-8B",
            "embedding_dims": 4096,
        },
    },
}

mem0 = Memory.from_config(config)
