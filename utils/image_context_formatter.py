"""
图片上下文格式管理器

专门处理图片描述在上下文中的格式化和解析，
使用AI不易模仿的特殊标记格式，避免AI生成无对应图片的描述文本。
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ImageContextFormatter:
    """图片上下文格式管理器"""
    
    # 使用特殊的、AI不易模仿的格式
    IMG_CONTEXT_PREFIX = "<IMG_CONTEXT:description>"
    IMG_CONTEXT_SUFFIX = "</IMG_CONTEXT>"
    
    # 旧格式的正则表达式，用于清理AI可能模仿的格式
    OLD_FORMAT_PATTERN = r'\[图片:\s*[^\]]+\]'
    NEW_FORMAT_PATTERN = r'<IMG_CONTEXT:description>.*?</IMG_CONTEXT>'
    
    @classmethod
    def format_image_description(cls, description: str) -> str:
        """
        将图片描述格式化为上下文专用格式
        
        Args:
            description: 图片描述内容
            
        Returns:
            格式化后的图片描述字符串
        """
        if not description or not description.strip():
            return f"{cls.IMG_CONTEXT_PREFIX}图片已发送{cls.IMG_CONTEXT_SUFFIX}"
        
        # 清理描述内容，避免包含特殊字符导致解析问题
        clean_description = description.strip().replace('<', '&lt;').replace('>', '&gt;')
        
        formatted = f"{cls.IMG_CONTEXT_PREFIX}{clean_description}{cls.IMG_CONTEXT_SUFFIX}"
        
        logger.debug(f"[img_formatter] 格式化图片描述: {description[:30]}... -> {formatted[:50]}...")
        
        return formatted
    
    @classmethod
    def extract_image_descriptions(cls, text: str) -> list:
        """
        从文本中提取所有图片描述
        
        Args:
            text: 包含图片描述的文本
            
        Returns:
            图片描述列表
        """
        pattern = re.compile(cls.NEW_FORMAT_PATTERN, re.DOTALL)
        matches = pattern.findall(text)
        
        descriptions = []
        for match in matches:
            # 提取描述内容（去除前后缀）
            desc_start = match.find(cls.IMG_CONTEXT_PREFIX) + len(cls.IMG_CONTEXT_PREFIX)
            desc_end = match.find(cls.IMG_CONTEXT_SUFFIX)
            if desc_end > desc_start:
                description = match[desc_start:desc_end].strip()
                # 恢复转义的字符
                description = description.replace('&lt;', '<').replace('&gt;', '>')
                descriptions.append(description)
        
        return descriptions
    
    @classmethod
    def clean_ai_generated_image_tags(cls, text: str) -> str:
        """
        清理AI可能生成的图片标签，避免无图片对应的描述
        
        Args:
            text: 待清理的文本
            
        Returns:
            清理后的文本
        """
        if not text:
            return text
            
        original_text = text
        
        # 1. 清理旧格式的图片标签 [图片: ...]
        text = re.sub(cls.OLD_FORMAT_PATTERN, '', text)
        
        # 2. 清理AI可能模仿的新格式（这种情况应该很少，但防万一）
        # 注意：只清理明显是AI模仿的，不清理系统生成的
        # 系统生成的通常出现在消息存储时，AI模仿的会出现在回复生成时
        suspicious_new_format = re.sub(cls.NEW_FORMAT_PATTERN, '', text, flags=re.DOTALL)
        if suspicious_new_format != text:
            logger.warning(f"[img_formatter] 检测到可疑的图片格式标记，已清理")
            text = suspicious_new_format
        
        # 清理多余的空白字符
        text = re.sub(r'\n\s*\n', '\n\n', text).strip()
        
        if original_text != text:
            logger.debug(f"[img_formatter] 清理AI生成的图片标签: 原长度={len(original_text)}, 清理后长度={len(text)}")
        
        return text
    
    @classmethod
    def is_valid_image_context(cls, text: str) -> bool:
        """
        检查文本是否包含有效的图片上下文格式
        
        Args:
            text: 待检查的文本
            
        Returns:
            是否包含有效的图片上下文
        """
        return bool(re.search(cls.NEW_FORMAT_PATTERN, text, re.DOTALL))
    
    @classmethod
    def replace_old_format_with_new(cls, text: str, default_description: str = "图片已发送") -> str:
        """
        将文本中的旧格式图片标签替换为新格式
        
        Args:
            text: 包含旧格式的文本
            default_description: 当无法提取描述时使用的默认描述
            
        Returns:
            替换后的文本
        """
        if not text:
            return text
            
        def replace_match(match):
            old_tag = match.group(0)
            # 尝试提取旧格式中的描述
            desc_match = re.search(r'\[图片:\s*([^\]]+)\]', old_tag)
            if desc_match:
                description = desc_match.group(1).strip()
            else:
                description = default_description
            
            return cls.format_image_description(description)
        
        new_text = re.sub(cls.OLD_FORMAT_PATTERN, replace_match, text)
        
        if new_text != text:
            logger.info(f"[img_formatter] 已将旧格式转换为新格式")
        
        return new_text


# 便捷函数
def format_image_description(description: str) -> str:
    """格式化图片描述的便捷函数"""
    return ImageContextFormatter.format_image_description(description)


def clean_ai_image_tags(text: str) -> str:
    """清理AI生成图片标签的便捷函数"""
    return ImageContextFormatter.clean_ai_generated_image_tags(text)


def extract_image_descriptions(text: str) -> list:
    """提取图片描述的便捷函数"""
    return ImageContextFormatter.extract_image_descriptions(text)