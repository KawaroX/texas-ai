"""
图片生成监控报告定时任务

提供定时和手动的报告生成功能，完全独立运行，失败不影响主业务流程。
支持Redis动态配置控制，可以随时启用/禁用报告功能。
"""
import logging
import asyncio
from datetime import datetime, date, timedelta
from celery import shared_task

logger = logging.getLogger(__name__)

@shared_task
def generate_daily_image_generation_reports():
    """
    Celery定时任务：生成每日图片生成监控报告
    
    该任务完全独立运行，失败不会影响图片生成主业务流程。
    通过Redis配置动态控制，支持随时启用/禁用。
    """
    logger.info("[reporting] 🚀 启动每日图片生成监控报告任务")
    
    try:
        # 使用异步事件循环运行报告生成
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(_async_generate_daily_reports())
            logger.info(f"[reporting] ✅ 每日报告任务完成: {result}")
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"[reporting] ❌ 每日报告任务失败: {e}")
        return {"status": "error", "error": str(e)}

@shared_task  
def generate_manual_image_generation_reports(target_date: str = None, report_types: list = None):
    """
    Celery手动任务：生成指定日期的图片生成监控报告
    
    Args:
        target_date: 目标日期（YYYY-MM-DD格式），默认为昨天
        report_types: 报告类型列表 ["enhancement", "generation", "both"]，默认为both
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
    if report_types is None:
        report_types = ["both"]
        
    logger.info(f"[reporting] 🎯 启动手动图片生成报告任务: {target_date}, 类型: {report_types}")
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(_async_generate_manual_reports(target_date, report_types))
            logger.info(f"[reporting] ✅ 手动报告任务完成: {result}")
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"[reporting] ❌ 手动报告任务失败: {e}")
        return {"status": "error", "error": str(e)}

@shared_task
def test_reporting_system():
    """
    Celery测试任务：测试报告系统各组件功能
    
    用于验证报告系统的各个组件是否正常工作。
    """
    logger.info("[reporting] 🧪 启动报告系统测试任务")
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(_async_test_reporting_system())
            logger.info(f"[reporting] ✅ 系统测试完成: {result}")
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"[reporting] ❌ 系统测试失败: {e}")
        return {"status": "error", "error": str(e)}

async def _async_generate_daily_reports():
    """异步生成每日报告"""
    try:
        from services.reporting_service import reporting_service
        
        # 生成昨天的报告（今天生成昨天的数据）
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        logger.info(f"[reporting] 生成每日报告: {target_date}")
        result = await reporting_service.generate_and_send_reports(target_date)
        
        return {
            "status": "success",
            "target_date": target_date,
            "results": result,
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[reporting] 异步每日报告生成失败: {e}")
        raise

async def _async_generate_manual_reports(target_date: str, report_types: list):
    """异步生成手动报告"""
    try:
        from services.reporting_service import reporting_service
        
        logger.info(f"[reporting] 生成手动报告: {target_date}, 类型: {report_types}")
        
        if "both" in report_types or len(report_types) > 1:
            # 生成完整报告
            result = await reporting_service.generate_and_send_reports(target_date)
        elif "enhancement" in report_types:
            # 仅生成增强功能报告
            result = await _generate_enhancement_report_only(reporting_service, target_date)
        elif "generation" in report_types:
            # 仅生成总体性能报告
            result = await _generate_generation_report_only(reporting_service, target_date)
        else:
            result = {"status": "error", "error": "Unknown report type"}
        
        return {
            "status": "success",
            "target_date": target_date,
            "report_types": report_types,
            "results": result,
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[reporting] 异步手动报告生成失败: {e}")
        raise

async def _generate_enhancement_report_only(reporting_service, target_date: str):
    """仅生成增强功能报告"""
    config = reporting_service._get_config()
    if not config.enabled:
        return {"enabled": False}
    
    # 收集数据并生成增强功能报告
    enhancement_metrics = await reporting_service.collect_enhancement_data(target_date)
    enhancement_report = reporting_service.generate_enhancement_report(enhancement_metrics, target_date)
    
    # AI分析
    if config.ai_analysis:
        enhancement_ai_analysis = await reporting_service.get_ai_analysis(enhancement_report, "增强功能")
        enhancement_full_report = f"{enhancement_report}\n\n---\n\n# 🤖 AI 智能分析\n\n{enhancement_ai_analysis}"
    else:
        enhancement_full_report = enhancement_report
    
    # 发送报告
    result = await reporting_service.send_to_mattermost(enhancement_full_report, config)
    return {"enhancement_report": result}

async def _generate_generation_report_only(reporting_service, target_date: str):
    """仅生成总体性能报告"""
    config = reporting_service._get_config()
    if not config.enabled:
        return {"enabled": False}
    
    # 收集数据并生成总体性能报告
    generation_metrics = await reporting_service.collect_generation_data(target_date)
    generation_report = reporting_service.generate_generation_report(generation_metrics, target_date)
    
    # AI分析
    if config.ai_analysis:
        generation_ai_analysis = await reporting_service.get_ai_analysis(generation_report, "总体性能")
        generation_full_report = f"{generation_report}\n\n---\n\n# 🤖 AI 智能分析\n\n{generation_ai_analysis}"
    else:
        generation_full_report = generation_report
    
    # 发送报告
    result = await reporting_service.send_to_mattermost(generation_full_report, config)
    return {"generation_report": result}

async def _async_test_reporting_system():
    """异步测试报告系统"""
    try:
        from services.reporting_service import reporting_service
        
        test_results = {
            "config_access": False,
            "data_collection": False,
            "report_generation": False,
            "ai_analysis": False,
            "mattermost_connection": False
        }
        
        # 1. 测试配置访问
        try:
            config = reporting_service._get_config()
            test_results["config_access"] = True
            logger.info("[reporting] ✅ 配置访问测试通过")
        except Exception as e:
            logger.error(f"[reporting] ❌ 配置访问测试失败: {e}")
        
        # 2. 测试数据收集
        try:
            test_date = datetime.now().strftime('%Y-%m-%d')
            enhancement_metrics = await reporting_service.collect_enhancement_data(test_date)
            generation_metrics = await reporting_service.collect_generation_data(test_date)
            test_results["data_collection"] = True
            logger.info("[reporting] ✅ 数据收集测试通过")
        except Exception as e:
            logger.error(f"[reporting] ❌ 数据收集测试失败: {e}")
        
        # 3. 测试报告生成
        try:
            test_report = reporting_service.generate_enhancement_report(enhancement_metrics, test_date)
            test_results["report_generation"] = len(test_report) > 100
            logger.info("[reporting] ✅ 报告生成测试通过")
        except Exception as e:
            logger.error(f"[reporting] ❌ 报告生成测试失败: {e}")
        
        # 4. 测试AI分析（如果启用）
        try:
            config = reporting_service._get_config()
            if config.openrouter_api_key:
                ai_result = await reporting_service.get_ai_analysis("测试报告内容", "测试")
                test_results["ai_analysis"] = len(ai_result) > 20
                logger.info("[reporting] ✅ AI分析测试通过")
            else:
                test_results["ai_analysis"] = "skipped"
                logger.info("[reporting] ⏭️ AI分析测试跳过（未配置API密钥）")
        except Exception as e:
            logger.error(f"[reporting] ❌ AI分析测试失败: {e}")
        
        # 5. 测试Mattermost连接（不实际发送消息）
        try:
            config = reporting_service._get_config()
            if config.mattermost_token:
                test_results["mattermost_connection"] = True
                logger.info("[reporting] ✅ Mattermost连接配置测试通过")
            else:
                test_results["mattermost_connection"] = "not_configured"
                logger.info("[reporting] ⏭️ Mattermost连接测试跳过（未配置）")
        except Exception as e:
            logger.error(f"[reporting] ❌ Mattermost连接测试失败: {e}")
        
        # 计算总体测试结果
        passed_tests = sum(1 for result in test_results.values() if result is True)
        total_tests = len([k for k, v in test_results.items() if v != "skipped" and v != "not_configured"])
        
        return {
            "status": "success",
            "overall_health": f"{passed_tests}/{total_tests} tests passed",
            "test_results": test_results,
            "tested_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[reporting] 系统测试异常: {e}")
        raise

# 便捷函数：配置管理
@shared_task
def update_reporting_config(enabled: bool = None, frequency: str = None, ai_analysis: bool = None):
    """
    更新报告系统配置
    
    Args:
        enabled: 是否启用报告系统
        frequency: 报告频率 ("daily", "weekly", "manual")
        ai_analysis: 是否启用AI分析
    """
    try:
        from services.reporting_service import reporting_service
        
        # 获取当前配置
        config = reporting_service._get_config()
        
        # 更新指定字段（只允许更新动态配置项）
        if enabled is not None:
            config.enabled = enabled
        if frequency is not None:
            config.frequency = frequency
        if ai_analysis is not None:
            config.ai_analysis = ai_analysis
        
        # 保存配置
        reporting_service._save_config(config)
        
        logger.info(f"[reporting] 配置已更新: enabled={config.enabled}, frequency={config.frequency}")
        
        return {
            "status": "success", 
            "config": {
                "enabled": config.enabled,
                "frequency": config.frequency,
                "ai_analysis": config.ai_analysis
            },
            "updated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[reporting] 配置更新失败: {e}")
        return {"status": "error", "error": str(e)}