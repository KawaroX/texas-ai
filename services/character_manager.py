"""
明日方舟角色管理器
用于管理和获取其他角色的基础图片
"""
import os
import hashlib
import logging
import httpx
import json
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class CharacterManager:
    """角色图片管理器"""
    
    def __init__(self):
        self.base_dir = "/app/character_images"
        self.images_dir = os.path.join(self.base_dir, "images")
        self.manifest_path = os.path.join(self.base_dir, "manifest.json")
        
        # 确保目录存在
        os.makedirs(self.images_dir, exist_ok=True)
        
        # 角色配置
        self.character_config = {
            "能天使": "https://patchwiki.biligame.com/images/arknights/5/51/mcykogoq3phi70qshmt51bajjf5fblq.png",
            "可颂": "https://patchwiki.biligame.com/images/arknights/e/e7/t5q4xgmeqag752f43jsfh0ipyv4ubh0.png", 
            "空": "https://media.prts.wiki/f/f0/%E7%AB%8B%E7%BB%98_%E7%A9%BA_1.png?image_process=format,webp/quality,Q_90",
            "拉普兰德": "https://patchwiki.biligame.com/images/arknights/e/ef/bki1qocy5xla53tf3l93dxhbky2glk0.png",
            "大帝": "https://bkimg.cdn.bcebos.com/pic/9922720e0cf3d7ca7bcbbbeb8549a9096b63f72403ad?x-bce-process=image/format,f_auto/watermark,image_d2F0ZXIvYmFpa2UyNzI,g_7,xp_5,yp_5,P_20/resize,m_lfit,limit_1,h_1080"
        }
    
    def _get_url_hash(self, url: str) -> str:
        """根据URL生成hash作为文件名"""
        return hashlib.md5(url.encode()).hexdigest()
    
    def _load_manifest(self) -> Dict:
        """加载本地清单文件"""
        if os.path.exists(self.manifest_path):
            try:
                with open(self.manifest_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"无法读取清单文件: {e}")
        return {"characters": {}}
    
    def _save_manifest(self, manifest: Dict):
        """保存清单文件"""
        try:
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            logger.info(f"📄 清单文件已保存: {self.manifest_path}")
        except Exception as e:
            logger.error(f"保存清单文件失败: {e}")
    
    async def download_character_image(self, character_name: str, url: str) -> Optional[str]:
        """下载角色图片到本地"""
        try:
            file_hash = self._get_url_hash(url)
            filename = f"{file_hash}.png"
            filepath = os.path.join(self.images_dir, filename)
            
            # 如果文件已存在，直接返回
            if os.path.exists(filepath):
                logger.info(f"角色图片已存在: {character_name} -> {filename}")
                return filepath
            
            # 下载图片
            async with httpx.AsyncClient() as client:
                response = await client.get(url, follow_redirects=True, timeout=30)
                response.raise_for_status()
                
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"✅ 角色图片下载成功: {character_name} -> {filename} ({len(response.content)} bytes)")
                return filepath
                
        except Exception as e:
            logger.error(f"❌ 下载角色图片失败 {character_name}: {e}")
            return None
    
    async def download_all_characters(self):
        """下载所有配置的角色图片"""
        logger.info("🖼️ 开始下载所有角色图片...")
        manifest = self._load_manifest()
        
        download_results = []
        for character_name, url in self.character_config.items():
            filepath = await self.download_character_image(character_name, url)
            if filepath:
                file_hash = self._get_url_hash(url)
                manifest["characters"][character_name] = {
                    "url": url,
                    "filename": f"{file_hash}.png",
                    "filepath": filepath,
                    "size": os.path.getsize(filepath)
                }
                download_results.append(f"✅ {character_name}")
            else:
                download_results.append(f"❌ {character_name}")
        
        self._save_manifest(manifest)
        
        success_count = len([r for r in download_results if r.startswith("✅")])
        total_count = len(self.character_config)
        
        logger.info(f"🎉 角色图片下载完成: {success_count}/{total_count} 成功")
        return download_results
    
    def detect_characters_in_text(self, text: str) -> List[str]:
        """检测文本中提到的角色"""
        detected = []
        for character_name in self.character_config.keys():
            if character_name in text:
                detected.append(character_name)
        return detected
    
    def get_character_image_path(self, character_name: str) -> Optional[str]:
        """获取角色的本地图片路径"""
        manifest = self._load_manifest()
        character_info = manifest.get("characters", {}).get(character_name)
        
        if character_info:
            filepath = character_info["filepath"]
            if os.path.exists(filepath):
                return filepath
            else:
                logger.warning(f"角色图片文件不存在: {filepath}")
        
        return None
    
    def get_characters_status(self) -> Dict:
        """获取所有角色的下载状态"""
        manifest = self._load_manifest()
        status = {
            "total_configured": len(self.character_config),
            "available": [],
            "missing": []
        }
        
        for character_name in self.character_config.keys():
            character_info = manifest.get("characters", {}).get(character_name)
            if character_info and os.path.exists(character_info["filepath"]):
                status["available"].append({
                    "name": character_name,
                    "filename": character_info["filename"],
                    "size": character_info["size"]
                })
            else:
                status["missing"].append(character_name)
        
        status["total_downloaded"] = len(status["available"])
        return status


# 全局实例
character_manager = CharacterManager()