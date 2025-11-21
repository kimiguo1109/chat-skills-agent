"""
S3 存储层 - 支持 Artifact 的云端持久化

负责将 artifacts 保存到 AWS S3，并支持按需加载。
包含数据验证、错误处理和降级机制。
"""
import json
import logging
from typing import Any, Dict, Optional

from ..config import settings

logger = logging.getLogger(__name__)


class S3StorageManager:
    """S3 存储管理器 - 处理 artifacts 的云端存储"""
    
    def __init__(self):
        """初始化 S3 客户端"""
        self.s3_client = None
        self.bucket = None
        self.artifact_folder = ""  # 🔥 移除 artifacts/ 前缀，直接使用 user_id/
        
        if settings.USE_S3_STORAGE:
            try:
                import boto3
                from botocore.exceptions import ClientError
                
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_REGION
                )
                self.bucket = settings.AWS_S3_BUCKET
                self.ClientError = ClientError
                
                logger.info(f"✅ S3 Storage initialized: {self.bucket}/ (user_id/artifact_id.json)")
            except ImportError:
                logger.warning("⚠️  boto3 not installed, S3 storage disabled")
                self.s3_client = None
            except Exception as e:
                logger.error(f"❌ Failed to initialize S3 client: {e}")
                self.s3_client = None
        else:
            logger.info("📂 S3 disabled (USE_S3_STORAGE=false), using local storage only")
    
    def is_available(self) -> bool:
        """检查 S3 是否可用"""
        return self.s3_client is not None
    
    def save(
        self,
        s3_key: str,
        content: str,
        content_type: str = "text/plain"
    ) -> Optional[str]:
        """
        保存任意内容到 S3（通用方法）
        
        Args:
            s3_key: S3 路径（如：user_kimi/session_xxx.md）
            content: 文件内容（字符串）
            content_type: MIME 类型
        
        Returns:
            S3 URI 或 None（失败时）
        """
        if not self.is_available():
            logger.debug("⚠️  S3 not available, skipping upload")
            return None
        
        try:
            # 上传到 S3
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=content.encode('utf-8'),
                ContentType=content_type
            )
            
            s3_uri = f"s3://{self.bucket}/{s3_key}"
            logger.debug(f"☁️  Uploaded to S3: {s3_uri}")
            
            return s3_uri
        
        except Exception as e:
            logger.error(f"❌ Failed to upload to S3: {e}")
            return None
    
    def save_artifact(
        self,
        user_id: str,
        artifact_id: str,
        content: Dict[str, Any],
        metadata: Optional[Dict] = None
    ) -> Optional[str]:
        """
        保存 artifact 到 S3。
        
        Args:
            user_id: 用户ID
            artifact_id: Artifact ID
            content: 完整内容
            metadata: 元数据（可选）
        
        Returns:
            S3 URI (s3://bucket/path) 或 None（失败时）
        """
        if not self.is_available():
            logger.debug("⚠️  S3 not available, skipping upload")
            return None
        
        try:
            # 🔧 数据验证
            if not self._validate_content(content):
                logger.error(f"❌ Invalid content for artifact {artifact_id}")
                return None
            
            # 构建 S3 key（直接使用 user_id，不包含 artifacts/ 前缀）
            s3_key = f"{user_id}/{artifact_id}.json"
            
            # 准备数据
            artifact_data = {
                "artifact_id": artifact_id,
                "user_id": user_id,
                "content": content,
                "metadata": metadata or {}
            }
            
            # 上传到 S3
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=json.dumps(artifact_data, ensure_ascii=False, indent=2),
                ContentType='application/json'
            )
            
            s3_uri = f"s3://{self.bucket}/{s3_key}"
            content_size = len(json.dumps(content, ensure_ascii=False))
            logger.info(f"💾 Artifact {artifact_id} saved to S3: {s3_uri} ({content_size} bytes)")
            
            return s3_uri
            
        except self.ClientError as e:
            logger.error(f"❌ S3 upload failed for {artifact_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error saving artifact {artifact_id}: {e}")
            return None
    
    def load_artifact(
        self,
        s3_uri: str
    ) -> Optional[Dict[str, Any]]:
        """
        从 S3 加载 artifact（按需加载）。
        
        Args:
            s3_uri: S3 URI (s3://bucket/path)
        
        Returns:
            Artifact 内容或 None
        """
        if not self.is_available():
            logger.warning("⚠️  S3 not available")
            return None
        
        try:
            # 解析 S3 URI
            if not s3_uri.startswith("s3://"):
                logger.error(f"❌ Invalid S3 URI: {s3_uri}")
                return None
            
            # s3://bucket/path -> bucket, path
            parts = s3_uri.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            
            # 从 S3 下载
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = response['Body'].read().decode('utf-8')
            artifact_data = json.loads(content)
            
            logger.debug(f"🔍 Loaded artifact from S3: {s3_uri}")
            return artifact_data.get("content")
            
        except self.ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning(f"⚠️  Artifact not found in S3: {s3_uri}")
            else:
                logger.error(f"❌ S3 download failed: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON from S3: {s3_uri} - {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error loading artifact: {e}")
            return None
    
    def _validate_content(self, content: Dict[str, Any]) -> bool:
        """
        验证 artifact 内容。
        
        验证规则：
        1. 必须是字典
        2. 必须可 JSON 序列化
        3. 大小不超过 10MB（防止滥用）
        """
        if not isinstance(content, dict):
            logger.error("❌ Content must be a dictionary")
            return False
        
        try:
            content_json = json.dumps(content, ensure_ascii=False)
            content_size = len(content_json)
            
            MAX_SIZE = 10 * 1024 * 1024  # 10MB
            if content_size > MAX_SIZE:
                logger.error(f"❌ Content too large: {content_size} bytes (max: {MAX_SIZE})")
                return False
            
            return True
        except (TypeError, ValueError) as e:
            logger.error(f"❌ Content not JSON serializable: {e}")
            return False

