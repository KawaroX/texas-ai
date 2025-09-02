import os
import json
import hashlib
import httpx
import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class SelfieBaseImageManager:
    """德克萨斯自拍底图本地化管理器"""
    
    def __init__(self, base_dir: str = "/app/selfie_base_images"):
        self.base_dir = Path(base_dir)
        self.manifest_file = self.base_dir / "manifest.json"
        self.images_dir = self.base_dir / "images"
        
        # 确保目录存在
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        
        # 底图URL列表
        self.base_urls = [
            "https://media.prts.wiki/6/65/%E7%AB%8B%E7%BB%98_%E7%BC%84%E9%BB%98%E5%BE%B7%E5%85%8B%E8%90%A8%E6%96%AF_1.png?image_process=format,webp/quality,Q_90",
            "https://media.prts.wiki/f/fc/%E7%AB%8B%E7%BB%98_%E5%BE%B7%E5%85%8B%E8%90%A8%E6%96%AF_1.png?image_process=format,webp/quality,Q_90",
            "https://media.prts.wiki/1/1f/%E7%AB%8B%E7%BB%98_%E5%BE%B7%E5%85%8B%E8%90%A8%E6%96%AF_skin1.png?image_process=format,webp/quality,Q_90",
            "https://media.prts.wiki/2/2b/%E7%AB%8B%E7%BB%98_%E5%BE%B7%E5%85%8B%E8%90%A8%E6%96%AF_skin2.png?image_process=format,webp/quality,Q_90"
        ]
    
    def _generate_filename(self, url: str) -> str:
        """根据URL生成唯一的文件名"""
        # 使用URL的hash作为文件名，避免特殊字符问题
        url_hash = hashlib.md5(url.encode()).hexdigest()
        # 从URL中提取可能的扩展名，默认为png
        if 'png' in url.lower():
            ext = 'png'
        elif 'jpg' in url.lower() or 'jpeg' in url.lower():
            ext = 'jpg'
        else:
            ext = 'png'
        return f"{url_hash}.{ext}"
    
    def load_manifest(self) -> Dict:
        """加载清单文件"""
        if self.manifest_file.exists():
            try:
                with open(self.manifest_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ 加载清单文件失败: {e}")
        
        # 返回默认清单结构
        return {
            "version": "1.0",
            "last_updated": None,
            "images": {}
        }
    
    def save_manifest(self, manifest: Dict):
        """保存清单文件"""
        try:
            with open(self.manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            logger.info(f"📄 清单文件已保存: {self.manifest_file}")
        except Exception as e:
            logger.error(f"❌ 保存清单文件失败: {e}")
    
    async def download_image(self, url: str, filename: str) -> bool:
        """下载单张图片"""
        filepath = self.images_dir / filename
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                
                # 保存图片
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"✅ 底图下载成功: {filename} ({len(response.content)} bytes)")
                return True
                
        except Exception as e:
            logger.error(f"❌ 下载底图失败 {url}: {e}")
            # 如果文件已创建但下载失败，删除不完整的文件
            if filepath.exists():
                filepath.unlink()
            return False
    
    async def download_all_images(self) -> Dict[str, bool]:
        """下载所有底图"""
        logger.info("🖼️ 开始下载所有德克萨斯底图...")
        
        manifest = self.load_manifest()
        results = {}
        
        for url in self.base_urls:
            filename = self._generate_filename(url)
            filepath = self.images_dir / filename
            
            # 检查是否已存在且完整
            if filepath.exists() and url in manifest["images"]:
                stored_info = manifest["images"][url]
                if stored_info.get("filename") == filename:
                    logger.info(f"⏭️ 底图已存在，跳过下载: {filename}")
                    results[url] = True
                    continue
            
            # 下载图片
            success = await self.download_image(url, filename)
            results[url] = success
            
            if success:
                # 更新清单
                manifest["images"][url] = {
                    "filename": filename,
                    "downloaded_at": datetime.now().isoformat(),
                    "file_size": (self.images_dir / filename).stat().st_size
                }
        
        # 更新清单
        manifest["last_updated"] = datetime.now().isoformat()
        self.save_manifest(manifest)
        
        # 统计结果
        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        logger.info(f"🎉 底图下载完成: {success_count}/{total_count} 成功")
        
        return results
    
    def get_local_image_paths(self) -> List[str]:
        """获取所有本地底图路径"""
        manifest = self.load_manifest()
        local_paths = []
        
        for url, info in manifest["images"].items():
            filename = info.get("filename")
            if filename:
                filepath = self.images_dir / filename
                if filepath.exists():
                    local_paths.append(str(filepath))
                else:
                    logger.warning(f"⚠️ 清单中的文件不存在: {filepath}")
        
        logger.info(f"📂 找到 {len(local_paths)} 张本地底图")
        return local_paths
    
    def get_random_local_image(self) -> Optional[str]:
        """随机获取一张本地底图路径"""
        local_paths = self.get_local_image_paths()
        if not local_paths:
            logger.error("❌ 没有可用的本地底图")
            return None
        
        import random
        selected_path = random.choice(local_paths)
        logger.info(f"🎲 随机选择底图: {Path(selected_path).name}")
        return selected_path
    
    def check_images_status(self) -> Dict:
        """检查底图状态"""
        manifest = self.load_manifest()
        status = {
            "total_configured": len(self.base_urls),
            "total_downloaded": 0,
            "missing": [],
            "available": []
        }
        
        for url in self.base_urls:
            if url in manifest["images"]:
                filename = manifest["images"][url]["filename"]
                filepath = self.images_dir / filename
                if filepath.exists():
                    status["available"].append({
                        "url": url,
                        "filename": filename,
                        "size": filepath.stat().st_size
                    })
                    status["total_downloaded"] += 1
                else:
                    status["missing"].append(url)
            else:
                status["missing"].append(url)
        
        return status

# 创建全局实例
selfie_manager = SelfieBaseImageManager()