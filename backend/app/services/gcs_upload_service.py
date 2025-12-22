"""
GCS Upload Service - 文件上传到 Google Cloud Storage

上传文件到 gs://kimi-dev/ bucket
"""
import os
import logging
import uuid
from datetime import datetime
from typing import Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# GCS Configuration
GCS_BUCKET = "kimi-dev"
GCS_PROJECT = "studyx-ai"  # 根据实际项目调整


class GCSUploadService:
    """Google Cloud Storage 文件上传服务"""
    
    def __init__(self):
        """初始化 GCS 客户端"""
        self.bucket_name = GCS_BUCKET
        self.client = None
        self.bucket = None
        self._initialized = False
        
        try:
            from google.cloud import storage
            
            # 尝试初始化客户端（使用默认凭证或环境变量）
            self.client = storage.Client()
            self.bucket = self.client.bucket(self.bucket_name)
            self._initialized = True
            logger.info(f"✅ GCS Upload Service initialized: gs://{self.bucket_name}/")
            
        except ImportError:
            logger.warning("⚠️ google-cloud-storage not installed. Run: pip install google-cloud-storage")
        except Exception as e:
            logger.warning(f"⚠️ GCS initialization failed: {e}")
            logger.info("💡 Make sure GOOGLE_APPLICATION_CREDENTIALS is set or running on GCP")
    
    @property
    def is_available(self) -> bool:
        """检查 GCS 是否可用"""
        return self._initialized and self.client is not None
    
    async def upload_file(
        self,
        file_content: bytes,
        original_filename: str,
        user_id: str,
        content_type: Optional[str] = None
    ) -> Tuple[bool, str, str]:
        """
        上传文件到 GCS
        
        Args:
            file_content: 文件内容（bytes）
            original_filename: 原始文件名
            user_id: 用户 ID（用于组织目录）
            content_type: MIME 类型
        
        Returns:
            Tuple[success, gcs_uri, error_message]
            - success: 是否成功
            - gcs_uri: gs://kimi-dev/path/to/file 格式的 URI
            - error_message: 错误信息（如果失败）
        """
        if not self.is_available:
            return False, "", "GCS service not available"
        
        try:
            # 生成唯一文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_ext = Path(original_filename).suffix
            unique_id = str(uuid.uuid4())[:8]
            
            # 构建 GCS 路径: user_id/timestamp_uniqueid_filename
            safe_filename = self._sanitize_filename(original_filename)
            gcs_path = f"{user_id}/{timestamp}_{unique_id}_{safe_filename}"
            
            # 上传到 GCS
            blob = self.bucket.blob(gcs_path)
            
            if content_type:
                blob.content_type = content_type
            
            blob.upload_from_string(file_content)
            
            # 构建 gs:// URI
            gcs_uri = f"gs://{self.bucket_name}/{gcs_path}"
            
            logger.info(f"✅ File uploaded to GCS: {gcs_uri}")
            logger.info(f"   • Original: {original_filename}")
            logger.info(f"   • Size: {len(file_content)} bytes")
            logger.info(f"   • Type: {content_type or 'auto'}")
            
            return True, gcs_uri, ""
            
        except Exception as e:
            error_msg = f"GCS upload failed: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, "", error_msg
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除特殊字符"""
        # 保留文件扩展名
        name = Path(filename).stem
        ext = Path(filename).suffix
        
        # 只保留字母、数字、中文、下划线、连字符
        import re
        safe_name = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', name)
        
        # 限制长度
        if len(safe_name) > 50:
            safe_name = safe_name[:50]
        
        return f"{safe_name}{ext}"
    
    async def delete_file(self, gcs_uri: str) -> bool:
        """删除 GCS 文件"""
        if not self.is_available:
            return False
        
        try:
            # 从 gs://bucket/path 提取 path
            if gcs_uri.startswith(f"gs://{self.bucket_name}/"):
                path = gcs_uri[len(f"gs://{self.bucket_name}/"):]
                blob = self.bucket.blob(path)
                blob.delete()
                logger.info(f"✅ File deleted from GCS: {gcs_uri}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ GCS delete failed: {e}")
            return False


# 单例
_gcs_service: Optional[GCSUploadService] = None


def get_gcs_upload_service() -> GCSUploadService:
    """获取 GCS 上传服务单例"""
    global _gcs_service
    if _gcs_service is None:
        _gcs_service = GCSUploadService()
    return _gcs_service


