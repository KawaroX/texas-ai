"""
图片生成性能监控和分析服务 (Image Generation Performance Monitoring & Analytics Service)

主要功能:
- 图片生成过程的详细数据记录(JSONL格式)
- 每日汇总报告生成和分析
- 成功率、耗时、错误类型等关键指标统计
- 角色检测和生成类型分布分析

服务关系:
- 被 image_generation_tasks.py 调用记录生成尝试
- 独立存储监控数据到本地文件系统
- 为运维和优化提供数据支持
- 不影响主业务流程，失败不中断其他功能

数据结构:
- ImageGenerationRecord: 单次生成记录的完整数据模型
- 包含时间戳、成功状态、耗时、错误信息、角色信息等

核心功能:
- record_generation_attempt(): 记录单次生成尝试
- generate_daily_summary(): 生成每日汇总分析
- get_recent_summaries(): 获取历史汇总数据

文件组织:
- /app/image_generation_logs/{date}/generation_log.jsonl (详细记录)
- /app/image_generation_logs/{date}/daily_summary.json (每日汇总)

监控指标:
- 总尝试次数、成功次数、成功率
- 平均生成耗时
- 生成类型分布(selfie/scene/scene_with_characters)
- 错误统计分析
- 角色检测统计
"""

import os
import json
from utils.logging_config import get_logger

logger = get_logger(__name__)
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict


@dataclass
class ImageGenerationRecord:
    """单次图片生成记录"""
    timestamp: str
    experience_id: str
    generation_type: str  # selfie|scene|scene_with_characters
    success: bool
    duration_seconds: float
    error: Optional[str]
    image_path: Optional[str]
    prompt_length: int
    detected_characters: List[str]
    api_model: str = "gpt-image-1"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class ImageGenerationMonitor:
    """图片生成监控器"""
    
    def __init__(self):
        self.base_dir = "/app/image_generation_logs"
        os.makedirs(self.base_dir, exist_ok=True)
    
    def _get_daily_log_path(self, date: str = None) -> str:
        """获取当日日志文件路径"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        daily_dir = os.path.join(self.base_dir, date)
        os.makedirs(daily_dir, exist_ok=True)
        return os.path.join(daily_dir, "generation_log.jsonl")
    
    def _get_daily_summary_path(self, date: str = None) -> str:
        """获取当日汇总文件路径"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        daily_dir = os.path.join(self.base_dir, date)
        os.makedirs(daily_dir, exist_ok=True)
        return os.path.join(daily_dir, "daily_summary.json")
    
    def record_generation(self, record: ImageGenerationRecord) -> bool:
        """记录单次图片生成数据"""
        try:
            log_path = self._get_daily_log_path()
            with open(log_path, 'a', encoding='utf-8') as f:
                json.dump(record.to_dict(), f, ensure_ascii=False)
                f.write('\n')
            logger.debug(f"图片生成记录已保存: {record.experience_id}")
            return True
        except Exception as e:
            logger.error(f"保存图片生成记录失败: {e}")
            return False
    
    def record_generation_attempt(self, 
                                experience_id: str,
                                generation_type: str,
                                start_time: datetime,
                                success: bool,
                                image_path: Optional[str] = None,
                                error: Optional[str] = None,
                                prompt_length: int = 0,
                                detected_characters: List[str] = None) -> bool:
        """便捷方法：记录图片生成尝试"""
        try:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            record = ImageGenerationRecord(
                timestamp=start_time.isoformat(),
                experience_id=experience_id,
                generation_type=generation_type,
                success=success,
                duration_seconds=duration,
                error=error,
                image_path=image_path,
                prompt_length=prompt_length,
                detected_characters=detected_characters or []
            )
            
            return self.record_generation(record)
        except Exception as e:
            logger.error(f"创建图片生成记录失败: {e}")
            return False
    
    def _load_daily_records(self, date: str = None) -> List[Dict[str, Any]]:
        """加载当日所有记录"""
        log_path = self._get_daily_log_path(date)
        records = []
        
        if not os.path.exists(log_path):
            return records
            
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
            return records
        except Exception as e:
            logger.error(f"读取每日记录失败: {e}")
            return records
    
    def generate_daily_summary(self, date: str = None) -> Dict[str, Any]:
        """生成每日汇总报告"""
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
            
        records = self._load_daily_records(date)
        
        if not records:
            summary = {
                "date": date,
                "total_attempts": 0,
                "successful_generations": 0,
                "success_rate": 0.0,
                "average_duration": 0.0,
                "type_distribution": {},
                "error_summary": {},
                "character_detection_stats": {}
            }
        else:
            successful_records = [r for r in records if r['success']]
            failed_records = [r for r in records if not r['success']]
            
            # 类型分布统计
            type_dist = {}
            for record in records:
                gen_type = record['generation_type']
                type_dist[gen_type] = type_dist.get(gen_type, 0) + 1
            
            # 错误统计
            error_summary = {}
            for record in failed_records:
                error = record.get('error', 'Unknown')
                error_summary[error] = error_summary.get(error, 0) + 1
            
            # 角色检测统计
            char_stats = {}
            for record in records:
                chars = record.get('detected_characters', [])
                for char in chars:
                    char_stats[char] = char_stats.get(char, 0) + 1
            
            # 平均耗时
            if successful_records:
                avg_duration = sum(r['duration_seconds'] for r in successful_records) / len(successful_records)
            else:
                avg_duration = 0.0
            
            summary = {
                "date": date,
                "total_attempts": len(records),
                "successful_generations": len(successful_records),
                "success_rate": len(successful_records) / len(records) if records else 0.0,
                "average_duration": round(avg_duration, 2),
                "type_distribution": type_dist,
                "error_summary": error_summary,
                "character_detection_stats": char_stats,
                "generated_at": datetime.now().isoformat()
            }
        
        # 保存汇总文件
        try:
            summary_path = self._get_daily_summary_path(date)
            with open(summary_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            logger.info(f"📊 每日汇总已生成: {date} - 成功率 {summary['success_rate']:.2%}")
        except Exception as e:
            logger.error(f"保存每日汇总失败: {e}")
        
        return summary
    
    def get_recent_summaries(self, days: int = 7) -> List[Dict[str, Any]]:
        """获取最近几天的汇总数据"""
        summaries = []
        
        from datetime import timedelta
        base_date = datetime.now().date()
        
        for i in range(days):
            date = (base_date - timedelta(days=i)).strftime('%Y-%m-%d')
            summary_path = self._get_daily_summary_path(date)
            
            if os.path.exists(summary_path):
                try:
                    with open(summary_path, 'r', encoding='utf-8') as f:
                        summary = json.load(f)
                        summaries.append(summary)
                except Exception as e:
                    logger.error(f"读取汇总文件失败 {date}: {e}")
        
        return summaries

# 全局监控实例
image_generation_monitor = ImageGenerationMonitor()