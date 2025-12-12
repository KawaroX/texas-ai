#!/usr/bin/env python3
"""
图片生成模型对比测试脚本

比较两个模型的图片生成效果：
1. gpt-image-1-all (当前使用)
2. doubao-seedream-4-5-251128 (待测试)

使用方法：
    python scripts/test_model_comparison.py --prompt "你的测试提示词"
"""

import os
import sys
import argparse
import json
import time
import httpx
import base64
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logging_config import get_logger

logger = get_logger(__name__)

# API 配置
API_BASE_URL = os.getenv("IMAGE_GENERATION_API_URL", "https://yunwu.ai/v1")
API_KEY = os.getenv("IMAGE_GENERATION_API_KEY")

# 测试输出目录
OUTPUT_DIR = Path("/tmp/model_comparison_test")
OUTPUT_DIR.mkdir(exist_ok=True)


def test_gpt_image_model(prompt: str, output_path: str):
    """
    测试 gpt-image-1-all 模型

    Args:
        prompt: 生成提示词
        output_path: 输出图片路径

    Returns:
        dict: 测试结果
    """
    logger.info("=" * 60)
    logger.info("🎨 测试模型: gpt-image-1-all")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        payload = {
            "model": "gpt-image-1-all",
            "prompt": prompt,
            "size": "1024x1536",
            "n": 1
        }

        logger.info(f"📝 提示词: {prompt}")
        logger.info(f"🔧 参数: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        logger.info("⏳ 发送请求...")

        response = httpx.post(
            f"{API_BASE_URL}/images/generations",
            headers=headers,
            json=payload,
            timeout=300.0
        )

        response.raise_for_status()
        result = response.json()

        elapsed_time = time.time() - start_time
        logger.info(f"⏱️  生成耗时: {elapsed_time:.2f} 秒")

        # 下载图片
        data_item = result.get("data", [{}])[0]
        image_url = data_item.get("url")

        if image_url:
            logger.info(f"🌐 图片URL: {image_url}")
            logger.info("📥 下载图片...")

            img_response = httpx.get(image_url, follow_redirects=True, timeout=60)
            img_response.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(img_response.content)

            logger.info(f"✅ 图片已保存: {output_path}")

            return {
                "success": True,
                "model": "gpt-image-1-all",
                "elapsed_time": elapsed_time,
                "output_path": output_path,
                "image_url": image_url,
                "file_size": len(img_response.content)
            }
        elif data_item.get("b64_json"):
            logger.info("📦 使用 base64 格式...")
            image_data = base64.b64decode(data_item["b64_json"])

            with open(output_path, "wb") as f:
                f.write(image_data)

            logger.info(f"✅ 图片已保存: {output_path}")

            return {
                "success": True,
                "model": "gpt-image-1-all",
                "elapsed_time": elapsed_time,
                "output_path": output_path,
                "file_size": len(image_data)
            }
        else:
            raise ValueError("API 未返回图片数据")

    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"❌ 生成失败: {e}")
        return {
            "success": False,
            "model": "gpt-image-1-all",
            "elapsed_time": elapsed_time,
            "error": str(e)
        }


def test_seedream_model(prompt: str, output_path: str, base_image_url: str = None):
    """
    测试 doubao-seedream-4-5-251128 模型

    Args:
        prompt: 生成提示词
        output_path: 输出图片路径
        base_image_url: 参考图片URL（可选）

    Returns:
        dict: 测试结果
    """
    logger.info("=" * 60)
    logger.info("🎨 测试模型: doubao-seedream-4-5-251128")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "doubao-seedream-4-5-251128",
            "prompt": prompt,
            "size": "2K",  # SeeDream 支持 2K 分辨率
            "watermark": False
        }

        # 如果提供了参考图片，添加到 payload
        if base_image_url:
            payload["image"] = base_image_url
            logger.info(f"🖼️  参考图片: {base_image_url}")

        logger.info(f"📝 提示词: {prompt}")
        logger.info(f"🔧 参数: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        logger.info("⏳ 发送请求...")

        response = httpx.post(
            f"{API_BASE_URL}/images/generations",
            headers=headers,
            json=payload,
            timeout=300.0
        )

        response.raise_for_status()
        result = response.json()

        elapsed_time = time.time() - start_time
        logger.info(f"⏱️  生成耗时: {elapsed_time:.2f} 秒")

        # 下载图片
        data_item = result.get("data", [{}])[0]
        image_url = data_item.get("url")

        if image_url:
            logger.info(f"🌐 图片URL: {image_url}")
            logger.info("📥 下载图片...")

            img_response = httpx.get(image_url, follow_redirects=True, timeout=60)
            img_response.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(img_response.content)

            logger.info(f"✅ 图片已保存: {output_path}")

            return {
                "success": True,
                "model": "doubao-seedream-4-5-251128",
                "elapsed_time": elapsed_time,
                "output_path": output_path,
                "image_url": image_url,
                "file_size": len(img_response.content)
            }
        elif data_item.get("b64_json"):
            logger.info("📦 使用 base64 格式...")
            image_data = base64.b64decode(data_item["b64_json"])

            with open(output_path, "wb") as f:
                f.write(image_data)

            logger.info(f"✅ 图片已保存: {output_path}")

            return {
                "success": True,
                "model": "doubao-seedream-4-5-251128",
                "elapsed_time": elapsed_time,
                "output_path": output_path,
                "file_size": len(image_data)
            }
        else:
            raise ValueError("API 未返回图片数据")

    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"❌ 生成失败: {e}")
        return {
            "success": False,
            "model": "doubao-seedream-4-5-251128",
            "elapsed_time": elapsed_time,
            "error": str(e)
        }


def generate_comparison_report(gpt_result: dict, seedream_result: dict):
    """
    生成对比报告

    Args:
        gpt_result: GPT 模型测试结果
        seedream_result: SeeDream 模型测试结果
    """
    logger.info("\n" + "=" * 60)
    logger.info("📊 模型对比报告")
    logger.info("=" * 60)

    # 模型对比表格
    logger.info("\n| 项目 | gpt-image-1-all | doubao-seedream-4-5 |")
    logger.info("|------|----------------|---------------------|")

    # 成功状态
    gpt_status = "✅ 成功" if gpt_result["success"] else "❌ 失败"
    seedream_status = "✅ 成功" if seedream_result["success"] else "❌ 失败"
    logger.info(f"| 生成状态 | {gpt_status} | {seedream_status} |")

    # 耗时对比
    if gpt_result["success"] and seedream_result["success"]:
        gpt_time = f"{gpt_result['elapsed_time']:.2f}秒"
        seedream_time = f"{seedream_result['elapsed_time']:.2f}秒"
        logger.info(f"| 生成耗时 | {gpt_time} | {seedream_time} |")

        # 文件大小
        gpt_size = f"{gpt_result['file_size'] / 1024:.1f}KB"
        seedream_size = f"{seedream_result['file_size'] / 1024:.1f}KB"
        logger.info(f"| 文件大小 | {gpt_size} | {seedream_size} |")

        # 输出路径
        logger.info(f"| 输出路径 | {gpt_result['output_path']} | {seedream_result['output_path']} |")

        # 性能对比
        if gpt_result['elapsed_time'] < seedream_result['elapsed_time']:
            faster_model = "gpt-image-1-all"
            time_diff = seedream_result['elapsed_time'] - gpt_result['elapsed_time']
        else:
            faster_model = "doubao-seedream-4-5"
            time_diff = gpt_result['elapsed_time'] - seedream_result['elapsed_time']

        logger.info(f"\n⚡ 速度对比: {faster_model} 快 {time_diff:.2f} 秒")

    # 错误信息
    if not gpt_result["success"]:
        logger.error(f"\n❌ gpt-image-1-all 错误: {gpt_result.get('error', 'Unknown')}")

    if not seedream_result["success"]:
        logger.error(f"\n❌ doubao-seedream-4-5 错误: {seedream_result.get('error', 'Unknown')}")

    logger.info("\n" + "=" * 60)
    logger.info("💡 提示:")
    logger.info("   1. 请手动查看生成的图片并对比质量")
    logger.info("   2. 考虑提示词风格、分辨率、生成速度等因素")
    logger.info("   3. 可以多次测试不同的提示词以获得更全面的对比")
    logger.info("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="图片生成模型对比测试")
    parser.add_argument(
        "--prompt",
        type=str,
        required=True,
        help="测试提示词"
    )
    parser.add_argument(
        "--base-image",
        type=str,
        help="参考图片URL（用于 SeeDream 的 image-to-image 功能）"
    )

    args = parser.parse_args()

    if not API_KEY:
        logger.error("❌ 错误: 未设置 IMAGE_GENERATION_API_KEY 环境变量")
        sys.exit(1)

    # 生成时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 输出文件路径
    gpt_output = OUTPUT_DIR / f"gpt_image_{timestamp}.png"
    seedream_output = OUTPUT_DIR / f"seedream_image_{timestamp}.png"

    logger.info("🚀 开始模型对比测试")
    logger.info(f"📁 输出目录: {OUTPUT_DIR}")
    logger.info(f"📝 测试提示词: {args.prompt}\n")

    # 测试 GPT 模型
    gpt_result = test_gpt_image_model(args.prompt, str(gpt_output))
    logger.info("")

    # 测试 SeeDream 模型
    seedream_result = test_seedream_model(args.prompt, str(seedream_output), args.base_image)
    logger.info("")

    # 生成对比报告
    generate_comparison_report(gpt_result, seedream_result)


if __name__ == "__main__":
    main()
