"""
Context Engineering - Artifact Manager
智能卸载和索引管理器

核心理念:
1. Offloading: 大型内容自动保存到文件系统，只返回引用
2. Indexing: 维护轻量级索引，Agent 按需检索
3. Token-Aware: 基于 token 估算自动决定是否卸载
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class ContextArtifactManager:
    """
    上下文感知的 Artifact 管理器
    
    职责:
    1. 智能判断内容是否需要卸载（基于 token 估算）
    2. 维护轻量级索引（artifact catalog）
    3. 提供按需检索接口
    """
    
    # Token 阈值: 超过此值自动卸载
    OFFLOAD_THRESHOLD_TOKENS = 500
    
    # 估算因子: 平均每个字符对应多少 token (中文约 1.5, 英文约 0.25)
    TOKEN_ESTIMATE_FACTOR = 0.8
    
    def __init__(
        self,
        storage_path: Path,
        s3_manager: Optional[Any] = None
    ):
        """
        初始化 Artifact Manager
        
        Args:
            storage_path: 本地存储路径
            s3_manager: S3 管理器（可选）
        """
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.s3_manager = s3_manager
        
        # 索引文件路径
        self.index_path = self.storage_path / "artifact_index.json"
        self._load_index()
        
        logger.info(f"✅ ContextArtifactManager initialized: {storage_path}")
    
    def _load_index(self):
        """加载 artifact 索引"""
        if self.index_path.exists():
            with open(self.index_path, 'r', encoding='utf-8') as f:
                self.index = json.load(f)
        else:
            self.index = {"artifacts": [], "metadata": {"last_updated": None}}
    
    def _save_index(self):
        """保存 artifact 索引"""
        self.index["metadata"]["last_updated"] = datetime.utcnow().isoformat()
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)
    
    def _estimate_tokens(self, content: Any) -> int:
        """
        估算内容的 token 数量
        
        Args:
            content: 内容（可以是字符串、字典、列表等）
        
        Returns:
            估算的 token 数
        """
        if isinstance(content, str):
            text = content
        elif isinstance(content, (dict, list)):
            text = json.dumps(content, ensure_ascii=False)
        else:
            text = str(content)
        
        return int(len(text) * self.TOKEN_ESTIMATE_FACTOR)
    
    def save_with_offload(
        self,
        artifact_id: str,
        content: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        智能保存: 根据大小决定是否卸载
        
        Args:
            artifact_id: Artifact ID
            content: Artifact 内容
            metadata: 元数据 (topic, type, user_id, session_id)
        
        Returns:
            (is_offloaded, file_path, lightweight_ref)
            - is_offloaded: 是否被卸载
            - file_path: 文件路径（如果卸载）
            - lightweight_ref: 轻量级引用（用于加载到 context）
        """
        # 1. 估算 token
        estimated_tokens = self._estimate_tokens(content)
        
        # 2. 决定是否卸载
        should_offload = estimated_tokens > self.OFFLOAD_THRESHOLD_TOKENS
        
        if should_offload:
            # 3. 卸载到文件
            file_path = self._save_to_file(artifact_id, content, metadata)
            
            # 4. 创建轻量级引用
            lightweight_ref = self._create_lightweight_ref(
                artifact_id, metadata, estimated_tokens, file_path
            )
            
            # 5. 更新索引
            self._update_index(artifact_id, metadata, estimated_tokens, file_path)
            
            logger.info(f"📤 Offloaded artifact {artifact_id}: {estimated_tokens} tokens → {file_path}")
            return True, file_path, lightweight_ref
        
        else:
            # 不卸载，直接返回内容
            logger.info(f"📝 Kept artifact {artifact_id} in memory: {estimated_tokens} tokens (< threshold)")
            
            # 仍然更新索引（但标记为 in-memory）
            self._update_index(artifact_id, metadata, estimated_tokens, file_path=None)
            
            return False, None, content
    
    def _save_to_file(self, artifact_id: str, content: Dict[str, Any], metadata: Dict[str, Any]) -> str:
        """保存 artifact 到文件"""
        # 创建用户目录
        user_id = metadata.get("user_id", "default")
        user_dir = self.storage_path / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存文件
        file_path = user_dir / f"{artifact_id}.json"
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({
                "artifact_id": artifact_id,
                "metadata": metadata,
                "content": content,
                "created_at": datetime.utcnow().isoformat()
            }, f, ensure_ascii=False, indent=2)
        
        # 可选: 上传到 S3
        if self.s3_manager and hasattr(self.s3_manager, 'upload_file'):
            try:
                s3_key = f"{user_id}/{artifact_id}.json"
                self.s3_manager.upload_file(str(file_path), s3_key)
                logger.info(f"☁️  Uploaded to S3: {s3_key}")
            except Exception as e:
                logger.warning(f"⚠️  S3 upload failed: {e}")
        
        return str(file_path.relative_to(self.storage_path))
    
    def _create_lightweight_ref(
        self,
        artifact_id: str,
        metadata: Dict[str, Any],
        estimated_tokens: int,
        file_path: str
    ) -> Dict[str, Any]:
        """创建轻量级引用（用于加载到 LLM context）"""
        return {
            "artifact_id": artifact_id,
            "type": metadata.get("type", "unknown"),
            "topic": metadata.get("topic", ""),
            "size_tokens": estimated_tokens,
            "file_path": file_path,
            "summary": metadata.get("summary", ""),
            "_note": "Use read_artifact tool to load full content"
        }
    
    def _update_index(
        self,
        artifact_id: str,
        metadata: Dict[str, Any],
        estimated_tokens: int,
        file_path: Optional[str]
    ):
        """更新索引"""
        # 移除旧的同 ID 条目
        self.index["artifacts"] = [
            a for a in self.index["artifacts"] if a["artifact_id"] != artifact_id
        ]
        
        # 添加新条目
        self.index["artifacts"].append({
            "artifact_id": artifact_id,
            "type": metadata.get("type", "unknown"),
            "topic": metadata.get("topic", ""),
            "session_id": metadata.get("session_id", ""),
            "size_tokens": estimated_tokens,
            "is_offloaded": file_path is not None,
            "file_path": file_path,
            "created_at": datetime.utcnow().isoformat()
        })
        
        self._save_index()
    
    def get_artifact_index(
        self,
        session_id: Optional[str] = None,
        topic: Optional[str] = None,
        artifact_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        获取 artifact 索引（轻量级，用于 Agent context）
        
        Args:
            session_id: 按会话过滤
            topic: 按主题过滤
            artifact_type: 按类型过滤
        
        Returns:
            Artifact 索引列表
        """
        artifacts = self.index["artifacts"]
        
        # 过滤
        if session_id:
            artifacts = [a for a in artifacts if a.get("session_id") == session_id]
        if topic:
            artifacts = [a for a in artifacts if topic.lower() in a.get("topic", "").lower()]
        if artifact_type:
            artifacts = [a for a in artifacts if a.get("type") == artifact_type]
        
        # 只返回轻量级字段
        return [
            {
                "artifact_id": a["artifact_id"],
                "type": a["type"],
                "topic": a["topic"],
                "size_tokens": a["size_tokens"],
                "is_offloaded": a["is_offloaded"]
            }
            for a in artifacts
        ]
    
    def read_artifact(
        self,
        artifact_id: str,
        lines: Optional[Tuple[int, int]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        读取 artifact 内容（按需检索）
        
        Args:
            artifact_id: Artifact ID
            lines: 可选的行范围 (start, end)
        
        Returns:
            Artifact 内容
        """
        # 从索引查找
        artifact_entry = next(
            (a for a in self.index["artifacts"] if a["artifact_id"] == artifact_id),
            None
        )
        
        if not artifact_entry:
            logger.warning(f"⚠️  Artifact {artifact_id} not found in index")
            return None
        
        # 读取文件
        if artifact_entry["is_offloaded"]:
            file_path = self.storage_path / artifact_entry["file_path"]
            if not file_path.exists():
                logger.error(f"❌ Artifact file not found: {file_path}")
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            content = data["content"]
            
            # 可选: 部分加载（如果支持）
            if lines and isinstance(content, str):
                content_lines = content.split('\n')
                start, end = lines
                content = '\n'.join(content_lines[start:end])
            
            logger.info(f"📥 Loaded artifact {artifact_id} from {file_path}")
            return content
        
        else:
            # In-memory artifacts (需要从其他地方加载)
            logger.warning(f"⚠️  In-memory artifact {artifact_id} not implemented")
            return None

