#!/usr/bin/env python3
"""
手动清理图片文件的脚本
支持按日期范围、文件大小等条件清理图片
"""

import os
import sys
import glob
import shutil
from datetime import datetime, timedelta
from typing import List, Dict

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

IMAGE_DIR = "/app/generated_content/images"


def get_image_directories() -> List[str]:
    """获取所有按日期分组的图片目录"""
    if not os.path.exists(IMAGE_DIR):
        print(f"❌ 图片目录不存在: {IMAGE_DIR}")
        return []
    
    dirs = []
    for item in os.listdir(IMAGE_DIR):
        dir_path = os.path.join(IMAGE_DIR, item)
        if os.path.isdir(dir_path) and item.count('-') == 2:  # YYYY-MM-DD格式
            dirs.append(dir_path)
    
    return sorted(dirs)


def get_directory_stats(dir_path: str) -> Dict:
    """获取目录统计信息"""
    if not os.path.exists(dir_path):
        return {"file_count": 0, "total_size": 0, "size_mb": 0}
    
    file_count = 0
    total_size = 0
    
    for file_name in os.listdir(dir_path):
        file_path = os.path.join(dir_path, file_name)
        if os.path.isfile(file_path):
            file_count += 1
            total_size += os.path.getsize(file_path)
    
    return {
        "file_count": file_count,
        "total_size": total_size,
        "size_mb": total_size / (1024 * 1024)
    }


def list_image_directories():
    """列出所有图片目录及其统计信息"""
    print("📂 图片目录统计:")
    print("=" * 60)
    
    dirs = get_image_directories()
    if not dirs:
        print("   暂无图片目录")
        return
    
    total_files = 0
    total_size_mb = 0
    
    for dir_path in dirs:
        dir_name = os.path.basename(dir_path)
        stats = get_directory_stats(dir_path)
        
        print(f"📅 {dir_name}: {stats['file_count']} 文件, {stats['size_mb']:.1f} MB")
        total_files += stats['file_count']
        total_size_mb += stats['size_mb']
    
    print("-" * 60)
    print(f"📊 总计: {len(dirs)} 目录, {total_files} 文件, {total_size_mb:.1f} MB")


def cleanup_by_date_range(start_date: str, end_date: str, dry_run: bool = True) -> Dict:
    """
    按日期范围清理图片
    
    Args:
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        dry_run: 是否只是预览而不实际删除
    """
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        print("❌ 日期格式错误，请使用 YYYY-MM-DD 格式")
        return {"error": "invalid_date_format"}
    
    if start_dt > end_dt:
        print("❌ 开始日期不能晚于结束日期")
        return {"error": "invalid_date_range"}
    
    dirs = get_image_directories()
    to_remove = []
    
    for dir_path in dirs:
        dir_name = os.path.basename(dir_path)
        try:
            dir_date = datetime.strptime(dir_name, "%Y-%m-%d")
            if start_dt <= dir_date <= end_dt:
                to_remove.append(dir_path)
        except ValueError:
            continue
    
    if not to_remove:
        print(f"📋 在日期范围 {start_date} 到 {end_date} 内没有找到要清理的目录")
        return {"removed": 0, "total_size_mb": 0}
    
    total_files = 0
    total_size_mb = 0
    
    print(f"🗑️ {'预览' if dry_run else '执行'}清理操作:")
    print("-" * 40)
    
    for dir_path in to_remove:
        stats = get_directory_stats(dir_path)
        dir_name = os.path.basename(dir_path)
        
        print(f"{'[预览]' if dry_run else '[删除]'} {dir_name}: {stats['file_count']} 文件, {stats['size_mb']:.1f} MB")
        
        total_files += stats['file_count']
        total_size_mb += stats['size_mb']
        
        if not dry_run:
            try:
                shutil.rmtree(dir_path)
            except Exception as e:
                print(f"❌ 删除目录失败 {dir_path}: {e}")
    
    print("-" * 40)
    print(f"📊 {'将' if dry_run else '已'}清理: {len(to_remove)} 目录, {total_files} 文件, {total_size_mb:.1f} MB")
    
    return {
        "removed": len(to_remove),
        "total_files": total_files,
        "total_size_mb": total_size_mb
    }


def cleanup_before_date(date_str: str, dry_run: bool = True) -> Dict:
    """清理指定日期之前的所有图片"""
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print("❌ 日期格式错误，请使用 YYYY-MM-DD 格式")
        return {"error": "invalid_date_format"}
    
    # 清理到前一天
    end_date = (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = "2020-01-01"  # 一个足够早的日期
    
    print(f"🗑️ 清理 {date_str} 之前的所有图片...")
    return cleanup_by_date_range(start_date, end_date, dry_run)


def interactive_cleanup():
    """交互式清理"""
    print("🖼️ 图片清理工具")
    print("=" * 50)
    
    while True:
        print("\n请选择操作:")
        print("1. 查看目录统计")
        print("2. 按日期范围清理 (预览)")
        print("3. 按日期范围清理 (执行)")
        print("4. 清理指定日期之前 (预览)")
        print("5. 清理指定日期之前 (执行)")
        print("0. 退出")
        
        choice = input("\n输入选择 (0-5): ").strip()
        
        if choice == "0":
            print("👋 再见!")
            break
        elif choice == "1":
            list_image_directories()
        elif choice in ["2", "3"]:
            start_date = input("输入开始日期 (YYYY-MM-DD): ").strip()
            end_date = input("输入结束日期 (YYYY-MM-DD): ").strip()
            dry_run = choice == "2"
            
            if not dry_run:
                confirm = input(f"⚠️ 确定要删除 {start_date} 到 {end_date} 的图片吗? (yes/no): ").strip().lower()
                if confirm != "yes":
                    print("❌ 操作已取消")
                    continue
            
            cleanup_by_date_range(start_date, end_date, dry_run)
            
        elif choice in ["4", "5"]:
            date_str = input("输入日期 (YYYY-MM-DD): ").strip()
            dry_run = choice == "4"
            
            if not dry_run:
                confirm = input(f"⚠️ 确定要删除 {date_str} 之前的所有图片吗? (yes/no): ").strip().lower()
                if confirm != "yes":
                    print("❌ 操作已取消")
                    continue
            
            cleanup_before_date(date_str, dry_run)
        else:
            print("❌ 无效选择")


def main():
    """主函数"""
    if len(sys.argv) > 1:
        # 命令行模式
        command = sys.argv[1]
        if command == "list":
            list_image_directories()
        elif command == "cleanup" and len(sys.argv) >= 4:
            start_date = sys.argv[2]
            end_date = sys.argv[3]
            dry_run = "--dry-run" in sys.argv
            cleanup_by_date_range(start_date, end_date, dry_run)
        else:
            print("用法:")
            print("  python manual_cleanup_images.py list")
            print("  python manual_cleanup_images.py cleanup YYYY-MM-DD YYYY-MM-DD [--dry-run]")
            print("  python manual_cleanup_images.py  # 交互式模式")
    else:
        # 交互式模式
        interactive_cleanup()


if __name__ == "__main__":
    main()