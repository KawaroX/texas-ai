"""
独立图片生成监控报告服务

专注于监控和分析增强图片生成功能的效果，通过自然语言报告展示运行状态和AI分析建议。
设计为完全独立的模块，可通过Redis配置动态控制，失败不影响主业务流程。
"""
import json
import os
import logging
import httpx
import redis
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class ReportingConfig:
    """报告系统配置"""
    enabled: bool = True
    frequency: str = "daily"  # daily, weekly, manual
    ai_analysis: bool = True
    
    # 固定配置
    target_channel: str = "eqgikba1opnpupiy3w16icdxoo"
    mattermost_token: str = "8or4yqexc3r6brji6s4acp1ycr"
    mattermost_url: str = "https://prts.kawaro.space"
    
    @property
    def openrouter_api_key(self) -> str:
        """从环境变量获取OpenRouter API密钥"""
        return os.getenv('OPENROUTER_API_KEY', '')

@dataclass 
class EnhancementMetrics:
    """增强功能指标"""
    total_events: int = 0
    enhanced_data_used: int = 0
    fallback_to_original: int = 0
    companions_detection: int = 0
    string_detection: int = 0
    prompt_enhancement_success: int = 0
    prompt_enhancement_failed: int = 0

@dataclass
class GenerationMetrics:
    """图片生成总体指标"""
    total_attempts: int = 0
    successful_generations: int = 0
    failed_generations: int = 0
    average_duration: float = 0.0
    selfie_count: int = 0
    scene_count: int = 0
    scene_with_characters_count: int = 0
    error_types: Dict[str, int] = None
    
    def __post_init__(self):
        if self.error_types is None:
            self.error_types = {}

class ImageGenerationReportingService:
    """图片生成报告服务"""
    
    def __init__(self):
        from app.config import settings
        self.redis_url = settings.REDIS_URL
        self.redis_client = redis.StrictRedis.from_url(self.redis_url, decode_responses=True)
        self.monitoring_logs_dir = Path("/app/image_generation_logs")
        self.process_tracking_key = "image_generation_process_tracking"
        
    def _get_config(self) -> ReportingConfig:
        """从Redis获取报告配置（动态控制）"""
        try:
            config_str = self.redis_client.get("reporting_config")
            config = ReportingConfig()  # 使用默认值（包括固定配置）
            
            if config_str:
                # 只更新动态配置项
                config_data = json.loads(config_str)
                config.enabled = config_data.get('enabled', True)
                config.frequency = config_data.get('frequency', 'daily')
                config.ai_analysis = config_data.get('ai_analysis', True)
            else:
                # 初始化动态配置
                dynamic_config = {
                    'enabled': True,
                    'frequency': 'daily',
                    'ai_analysis': True
                }
                self.redis_client.set("reporting_config", json.dumps(dynamic_config), ex=86400*7)
                
            return config
        except Exception as e:
            logger.warning(f"[reporting] 获取配置失败，使用默认配置: {e}")
            return ReportingConfig()
    
    def _save_config(self, config: ReportingConfig):
        """保存动态配置到Redis"""
        try:
            # 只保存动态配置项
            dynamic_config = {
                'enabled': config.enabled,
                'frequency': config.frequency,
                'ai_analysis': config.ai_analysis
            }
            self.redis_client.set("reporting_config", json.dumps(dynamic_config), ex=86400*7)
            logger.info("[reporting] 动态配置已保存到Redis")
        except Exception as e:
            logger.error(f"[reporting] 保存配置失败: {e}")
    
    async def collect_enhancement_data(self, target_date: str = None) -> EnhancementMetrics:
        """收集增强功能相关数据"""
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')
            
        metrics = EnhancementMetrics()
        
        try:
            # 1. 统计Redis中的数据量对比
            original_key = f"interaction_needed:{target_date}"
            enhanced_key = f"interaction_needed_enhanced:{target_date}"
            
            original_count = self.redis_client.zcard(original_key) if self.redis_client.exists(original_key) else 0
            enhanced_count = self.redis_client.zcard(enhanced_key) if self.redis_client.exists(enhanced_key) else 0
            
            metrics.total_events = max(original_count, enhanced_count)  # 应该相等，取较大值作为总数
            
            # 2. 收集实时过程追踪数据（如果有的话）
            tracking_data = self._get_process_tracking_data(target_date)
            if tracking_data:
                metrics.enhanced_data_used = tracking_data.get("enhanced_data_used", 0)
                metrics.fallback_to_original = tracking_data.get("fallback_to_original", 0)
                metrics.companions_detection = tracking_data.get("companions_detection", 0)
                metrics.string_detection = tracking_data.get("string_detection", 0)
                metrics.prompt_enhancement_success = tracking_data.get("prompt_enhancement_success", 0)
                metrics.prompt_enhancement_failed = tracking_data.get("prompt_enhancement_failed", 0)
            
            logger.info(f"[reporting] 增强功能数据收集完成: {target_date}")
            return metrics
            
        except Exception as e:
            logger.error(f"[reporting] 收集增强功能数据失败: {e}")
            return metrics
    
    async def collect_generation_data(self, target_date: str = None) -> GenerationMetrics:
        """收集图片生成总体数据"""
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')
            
        metrics = GenerationMetrics()
        
        try:
            # 从监控文件读取数据
            daily_log_path = self.monitoring_logs_dir / target_date / "generation_log.jsonl"
            daily_summary_path = self.monitoring_logs_dir / target_date / "daily_summary.json"
            
            # 读取详细记录
            if daily_log_path.exists():
                with open(daily_log_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            metrics.total_attempts += 1
                            
                            if record.get("success"):
                                metrics.successful_generations += 1
                            else:
                                metrics.failed_generations += 1
                                # 统计错误类型
                                error = record.get("error", "Unknown")
                                metrics.error_types[error] = metrics.error_types.get(error, 0) + 1
                            
                            # 统计生成类型
                            gen_type = record.get("generation_type", "unknown")
                            if gen_type == "selfie":
                                metrics.selfie_count += 1
                            elif gen_type == "scene":
                                metrics.scene_count += 1
                            elif gen_type == "scene_with_characters":
                                metrics.scene_with_characters_count += 1
                                
                        except json.JSONDecodeError:
                            continue
            
            # 读取汇总数据
            if daily_summary_path.exists():
                with open(daily_summary_path, 'r', encoding='utf-8') as f:
                    summary = json.load(f)
                    metrics.average_duration = summary.get("average_duration", 0.0)
            
            logger.info(f"[reporting] 图片生成数据收集完成: {target_date}")
            return metrics
            
        except Exception as e:
            logger.error(f"[reporting] 收集图片生成数据失败: {e}")
            return metrics
    
    def _get_process_tracking_data(self, target_date: str) -> Dict:
        """获取过程追踪数据"""
        try:
            tracking_key = f"{self.process_tracking_key}:{target_date}"
            data_str = self.redis_client.get(tracking_key)
            if data_str:
                return json.loads(data_str)
            return {}
        except Exception as e:
            logger.warning(f"[reporting] 获取过程追踪数据失败: {e}")
            return {}
    
    def generate_enhancement_report(self, metrics: EnhancementMetrics, target_date: str) -> str:
        """生成增强功能效果报告（Markdown格式）"""
        report = f"""# 🚀 图片生成增强功能效果报告

**日期**: {target_date}  
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 📊 数据源使用情况

### 总体统计
- **总交互事件数**: {metrics.total_events}
- **增强数据使用**: {metrics.enhanced_data_used} 次
- **回退到原始数据**: {metrics.fallback_to_original} 次
- **数据源成功率**: {(metrics.enhanced_data_used / max(metrics.total_events, 1) * 100):.1f}%

### 使用分布
```
增强数据: {'█' * min(20, max(1, metrics.enhanced_data_used))}
原始数据: {'█' * min(20, max(1, metrics.fallback_to_original))}
```

---

## 🎯 角色检测准确性分析

### 检测方式对比
- **Companions数组检测**: {metrics.companions_detection} 次 ✨
- **字符串匹配检测**: {metrics.string_detection} 次 📦
- **新检测方式占比**: {(metrics.companions_detection / max(metrics.companions_detection + metrics.string_detection, 1) * 100):.1f}%

### 准确性提升
```
新方法(companions): {'█' * min(20, max(1, metrics.companions_detection))}
旧方法(字符串):     {'█' * min(20, max(1, metrics.string_detection))}
```

---

## ✨ 提示词增强效果

### 增强构建统计
- **增强成功**: {metrics.prompt_enhancement_success} 次 ✅
- **增强失败**: {metrics.prompt_enhancement_failed} 次 ⚠️
- **增强成功率**: {(metrics.prompt_enhancement_success / max(metrics.prompt_enhancement_success + metrics.prompt_enhancement_failed, 1) * 100):.1f}%

---

## 🔒 向后兼容性验证

### 兼容性状态
- **回退机制触发**: {metrics.fallback_to_original} 次
- **系统稳定性**: {'🟢 优秀' if metrics.fallback_to_original < metrics.total_events * 0.1 else '🟡 需关注' if metrics.fallback_to_original < metrics.total_events * 0.5 else '🔴 需检查'}
- **兼容性评分**: {max(0, min(100, 100 - (metrics.fallback_to_original / max(metrics.total_events, 1) * 100))):.0f}/100

---

## 💡 关键洞察

### 功能采用情况
{'🎉 增强功能运行良好！数据源主要使用增强版本。' if metrics.enhanced_data_used > metrics.fallback_to_original else '⚠️ 增强数据使用率较低，需要检查数据生成流程。'}

### 角色检测改进
{'✨ 新的角色检测方式工作正常！' if metrics.companions_detection > 0 else '📦 主要使用传统字符串匹配，增强检测可能未生效。'}

### 提示词增强状态  
{'🚀 提示词增强功能表现良好！' if metrics.prompt_enhancement_success > metrics.prompt_enhancement_failed else '🔧 提示词增强需要优化。'}

---

*报告由 Texas AI 增强监控系统自动生成*
"""
        return report
    
    def generate_generation_report(self, metrics: GenerationMetrics, target_date: str) -> str:
        """生成图片生成总体表现报告（Markdown格式）"""
        success_rate = (metrics.successful_generations / max(metrics.total_attempts, 1)) * 100
        
        report = f"""# 📸 图片生成总体表现报告

**日期**: {target_date}  
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 📈 总体性能指标

### 生成统计
- **总尝试次数**: {metrics.total_attempts}
- **成功生成**: {metrics.successful_generations}
- **失败次数**: {metrics.failed_generations}
- **成功率**: {success_rate:.1f}%
- **平均耗时**: {metrics.average_duration:.1f}秒

### 成功率趋势
```
成功: {'█' * min(20, max(1, int(success_rate/5)))}
失败: {'█' * min(20, max(1, int((100-success_rate)/5)))}
```

---

## 🎨 生成类型分布

### 类型统计
- **自拍图片**: {metrics.selfie_count} 张 📸
- **场景图片**: {metrics.scene_count} 张 🎨  
- **多角色场景**: {metrics.scene_with_characters_count} 张 👥

### 分布可视化
```
自拍:     {'█' * min(15, max(1, metrics.selfie_count))} ({metrics.selfie_count})
场景:     {'█' * min(15, max(1, metrics.scene_count))} ({metrics.scene_count})
多角色:   {'█' * min(15, max(1, metrics.scene_with_characters_count))} ({metrics.scene_with_characters_count})
```

---

## ❌ 错误类型分析

### 主要错误类型
"""
        
        if metrics.error_types:
            for error_type, count in sorted(metrics.error_types.items(), key=lambda x: x[1], reverse=True)[:5]:
                report += f"- **{error_type}**: {count} 次\n"
        else:
            report += "- 🎉 当日无错误记录\n"
            
        report += f"""
### 错误率分析
- **错误率**: {((metrics.failed_generations / max(metrics.total_attempts, 1)) * 100):.1f}%
- **系统健康度**: {'🟢 优秀' if success_rate >= 90 else '🟡 良好' if success_rate >= 70 else '🟠 需关注' if success_rate >= 50 else '🔴 需检查'}

---

## 📊 性能分析

### 平均耗时评估
- **当前耗时**: {metrics.average_duration:.1f}秒
- **性能等级**: {'🚀 极快' if metrics.average_duration < 30 else '⚡ 快速' if metrics.average_duration < 60 else '🔄 正常' if metrics.average_duration < 120 else '⏳ 较慢'}

### 生成效率
- **每小时产能**: {(3600 / max(metrics.average_duration, 1)):.0f} 张（理论值）
- **实际产能**: 取决于交互事件频率

---

## 💡 总结与建议

### 系统状态
{'🎉 系统运行状况良好！' if success_rate >= 80 else '⚠️ 系统需要关注和优化。'}

### 关键指标
- 成功率: {success_rate:.1f}%
- 平均耗时: {metrics.average_duration:.1f}s
- 错误类型: {len(metrics.error_types)} 种

---

*报告由 Texas AI 监控系统自动生成*
"""
        return report
    
    async def get_ai_analysis(self, report_content: str, report_type: str) -> str:
        """调用OpenRouter API进行AI分析"""
        config = self._get_config()
        if not config.openrouter_api_key:
            logger.warning("[reporting] OpenRouter API密钥未配置，跳过AI分析")
            return "⚠️ AI分析功能暂时不可用（API密钥未配置）"
            
        try:
            prompt = f"""你是一个专业的AI系统分析师，请分析以下图片生成系统的{report_type}报告，提供专业的见解和建议。

报告内容：
{report_content}

请从以下几个角度进行分析：
1. 系统性能表现评估
2. 潜在问题识别
3. 优化建议
4. 风险预警
5. 改进优先级

请用专业但易懂的语言回答，使用Markdown格式，给出具体可行的建议。"""

            headers = {
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://prts.kawaro.space",
                "X-Title": "Texas AI Reporting System"
            }
            
            payload = {
                "model": "deepseek/deepseek-chat-v3.1:free",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                
                result = response.json()
                ai_analysis = result["choices"][0]["message"]["content"]
                
                logger.info(f"[reporting] AI分析完成，长度: {len(ai_analysis)}")
                return ai_analysis
                
        except Exception as e:
            logger.error(f"[reporting] AI分析失败: {e}")
            return f"⚠️ AI分析暂时不可用: {str(e)[:100]}..."
    
    async def send_to_mattermost(self, content: str, config: ReportingConfig) -> bool:
        """发送报告到Mattermost"""
        try:
            url = f"{config.mattermost_url}/api/v4/posts"
            headers = {
                "Authorization": f"Bearer {config.mattermost_token}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "channel_id": config.target_channel,
                "message": content
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                
                logger.info("[reporting] 报告已成功发送到Mattermost")
                return True
                
        except Exception as e:
            logger.error(f"[reporting] 发送Mattermost消息失败: {e}")
            return False
    
    async def generate_and_send_reports(self, target_date: str = None) -> Dict[str, bool]:
        """生成并发送完整报告"""
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')
            
        config = self._get_config()
        if not config.enabled:
            logger.info("[reporting] 报告功能已禁用")
            return {"enabled": False}
        
        results = {}
        
        try:
            logger.info(f"[reporting] 开始生成 {target_date} 的报告...")
            
            # 1. 收集数据
            enhancement_metrics = await self.collect_enhancement_data(target_date)
            generation_metrics = await self.collect_generation_data(target_date)
            
            # 2. 生成增强功能报告
            enhancement_report = self.generate_enhancement_report(enhancement_metrics, target_date)
            
            # 3. AI分析增强功能报告
            if config.ai_analysis:
                enhancement_ai_analysis = await self.get_ai_analysis(enhancement_report, "增强功能")
                enhancement_full_report = f"{enhancement_report}\n\n---\n\n# 🤖 AI 智能分析\n\n{enhancement_ai_analysis}"
            else:
                enhancement_full_report = enhancement_report
            
            # 4. 发送增强功能报告
            results["enhancement_report"] = await self.send_to_mattermost(enhancement_full_report, config)
            
            # 5. 生成总体性能报告
            generation_report = self.generate_generation_report(generation_metrics, target_date)
            
            # 6. AI分析总体性能报告
            if config.ai_analysis:
                generation_ai_analysis = await self.get_ai_analysis(generation_report, "总体性能")
                generation_full_report = f"{generation_report}\n\n---\n\n# 🤖 AI 智能分析\n\n{generation_ai_analysis}"
            else:
                generation_full_report = generation_report
            
            # 7. 发送总体性能报告
            results["generation_report"] = await self.send_to_mattermost(generation_full_report, config)
            
            logger.info("[reporting] 报告生成和发送完成")
            return results
            
        except Exception as e:
            logger.error(f"[reporting] 报告生成失败: {e}")
            return {"error": str(e)}

# 全局实例
reporting_service = ImageGenerationReportingService()