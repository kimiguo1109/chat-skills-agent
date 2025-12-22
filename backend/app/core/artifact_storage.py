"""
Artifact Storage - Context Offloading 核心模块

负责将 Plan Skill 的 step 结果持久化到文件系统，
实现真正的上下文卸载（而不是内存累积）。

设计原则：
- 独立模块，零侵入
- 完全可选，默认不使用
- 降级友好，文件操作失败时不影响主流程
"""

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ArtifactStorage:
    """
    Artifact 存储管理器
    
    职责：
    1. 保存 step 结果到文件系统
    2. 按需加载 artifact
    3. 创建轻量级引用（artifact_reference）
    4. 管理 artifact 生命周期
    
    使用场景：
    - Plan Skill 中的 step 结果持久化
    - 跨 step 的上下文传递（通过引用而不是完整内容）
    
    不影响：
    - Single Skill 执行（完全独立）
    - Intent Router（不涉及）
    - Memory System（不同存储目录）
    """
    
    def __init__(
        self, 
        base_dir: str = "artifacts",
        s3_manager: Optional[Any] = None
    ):
        """
        初始化 Artifact Storage
        
        Args:
            base_dir: artifact 存储根目录（相对于项目根目录）
            s3_manager: S3StorageManager 实例（可选）
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # 🆕 S3 支持
        self.s3_manager = s3_manager
        self.use_s3 = s3_manager is not None and s3_manager.is_available()
        
        logger.info(f"✅ ArtifactStorage initialized: local={self.base_dir.absolute()}, S3={self.use_s3}")
    
    def save_step_result(
        self,
        session_id: str,
        step_id: str,
        result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        保存 step 结果（只上传到 S3，不保存本地）
        
        注意：根据需求，step_artifact JSON 文件不需要本地保存，
        因为详细内容已经在 MD 文件中了。只上传到 S3 用于云端备份。
        
        Args:
            session_id: Plan 执行的唯一 session ID 或 user session ID
            step_id: Step 标识符（如 "explain", "notes", "quiz"）
            result: Step 执行结果（完整内容）
            metadata: 可选的元数据（如 skill_id, tokens_used）
        
        Returns:
            引用字符串：
            - S3: "s3://bucket/user_xxx/step_001.json"
            - 如果S3不可用: 返回空字符串（不保存本地）
            
        Raises:
            IOError: S3 上传失败且无法降级时
        """
        # 🎯 只上传到 S3，不保存本地
        if self.use_s3:
            try:
                # 提取 user_id
                user_id = self._extract_user_id(session_id)
                
                # 上传到 S3
                s3_uri = self.s3_manager.save_artifact(
                    user_id=user_id,
                    artifact_id=f"step_{step_id}",
                    content=result,
                    metadata=metadata
                )
                
                if s3_uri:
                    logger.debug(f"💾 Saved to S3: {s3_uri}")
                    return s3_uri
                else:
                    logger.warning("⚠️  S3 upload returned None, skipping local storage (as per requirement)")
                    # 返回空字符串，表示未保存（因为不需要本地保存）
                    return ""
            except Exception as e:
                logger.error(f"❌ S3 save error: {e}, skipping local storage (as per requirement)")
                # 返回空字符串，表示未保存
                return ""
        
        # S3 不可用时，也不保存本地（根据用户需求）
        logger.warning("⚠️  S3 not available, skipping step_artifact storage (content already in MD file)")
        return ""
    
    def _extract_user_id(self, session_id: str) -> str:
        """
        从 session_id 提取 user_id
        
        支持的格式：
        - user_{user_id}_{timestamp}: 提取 user_id
        - plan_{timestamp}_{uuid}: 返回 "anonymous"
        """
        if session_id.startswith("user_"):
            parts = session_id.split("_")
            # user_alice_123456 -> alice
            if len(parts) >= 2:
                return "_".join(parts[1:-1]) if len(parts) > 2 else parts[1]
        return "anonymous"
    
    def load_step_result(
        self,
        session_id: str,
        step_id: str
    ) -> Dict[str, Any]:
        """
        按需加载 step 结果（完整内容）
        
        Args:
            session_id: Plan 执行的 session ID
            step_id: Step 标识符
        
        Returns:
            Step 执行结果（result 字段）
            
        Raises:
            FileNotFoundError: artifact 不存在
            json.JSONDecodeError: JSON 解析失败
        """
        file_path = self.base_dir / session_id / f"step_{step_id}.json"
        
        if not file_path.exists():
            raise FileNotFoundError(
                f"Artifact not found: {file_path.relative_to(self.base_dir)}"
            )
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                artifact = json.load(f)
            
            logger.debug(
                f"🔍 Loaded artifact: {session_id}/step_{step_id}.json "
                f"({len(json.dumps(artifact['result'], ensure_ascii=False))} bytes)"
            )
            
            return artifact["result"]
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse artifact JSON: {e}")
            raise
    
    def load_artifact_by_reference(
        self,
        reference: str
    ) -> Dict[str, Any]:
        """
        按需加载 artifact（支持 S3 URI 或本地路径）
        
        Args:
            reference: "s3://..." 或 "user_xxx/step_001.json"
        
        Returns:
            Artifact 内容
            
        Raises:
            FileNotFoundError: artifact 不存在
            RuntimeError: S3 不可用但引用是 S3 URI
        """
        # S3 引用
        if reference.startswith("s3://"):
            if not self.use_s3:
                raise RuntimeError(f"S3 not available, cannot load: {reference}")
            
            content = self.s3_manager.load_artifact(reference)
            if content is None:
                raise FileNotFoundError(f"Artifact not found in S3: {reference}")
            return content
        
        # 本地文件引用
        file_path = self.base_dir / reference
        if not file_path.exists():
            raise FileNotFoundError(f"Artifact not found locally: {file_path}")
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                artifact = json.load(f)
            
            logger.debug(f"🔍 Loaded artifact from local: {reference}")
            return artifact.get("result", {})
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse artifact JSON from {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Failed to load from {file_path}: {e}")
            raise
    
    def create_reference(
        self,
        session_id: str,
        step_id: str,
        fields: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        创建轻量级 artifact 引用（而不是传递完整内容）
        
        这是 Context Offloading 的核心：
        - 不传递 2000+ tokens 的完整内容
        - 只传递 ~100 bytes 的引用
        - 按需加载（_format_prompt 时）
        
        Args:
            session_id: Plan 执行的 session ID
            step_id: Step 标识符
            fields: 可选的字段列表（只加载这些字段，进一步节省）
        
        Returns:
            Artifact 引用对象（type="artifact_reference"）
        """
        reference = {
            "type": "artifact_reference",
            "session_id": session_id,
            "step_id": step_id,
            "fields": fields,
            "file_path": f"{session_id}/step_{step_id}.json"
        }
        
        reference_size = len(json.dumps(reference, ensure_ascii=False))
        logger.debug(
            f"📝 Created reference: {step_id} "
            f"({reference_size} bytes, fields: {fields or 'all'})"
        )
        
        return reference
    
    def save_plan_metadata(
        self,
        session_id: str,
        plan_config: Dict[str, Any],
        user_input: Dict[str, Any]
    ) -> str:
        """
        保存 Plan 整体元数据
        
        用于追溯和恢复：
        - Plan 配置
        - 用户输入
        - 执行时间
        
        Args:
            session_id: Plan 执行的 session ID
            plan_config: Plan 配置（来自 YAML）
            user_input: 用户输入参数
        
        Returns:
            metadata 文件相对路径
        """
        try:
            session_dir = self.base_dir / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            
            file_path = session_dir / "plan_metadata.json"
            
            metadata = {
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "plan_config": {
                    "skill_id": plan_config.get("id"),
                    "display_name": plan_config.get("display_name"),
                    "steps": [
                        {
                            "step_id": step.get("step_id"),
                            "skill_id": step.get("skill_id"),
                            "name": step.get("name")
                        }
                        for step in plan_config.get("execution_plan", [])
                    ]
                },
                "user_input": user_input
            }
            
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            relative_path = file_path.relative_to(self.base_dir)
            logger.info(f"📋 Saved plan metadata: {relative_path}")
            
            return str(relative_path)
            
        except Exception as e:
            logger.error(f"❌ Failed to save plan metadata: {e}")
            raise
    
    def load_plan_metadata(self, session_id: str) -> Dict[str, Any]:
        """
        加载 Plan 元数据
        
        Args:
            session_id: Plan 执行的 session ID
        
        Returns:
            Plan 元数据
            
        Raises:
            FileNotFoundError: metadata 不存在
        """
        file_path = self.base_dir / session_id / "plan_metadata.json"
        
        if not file_path.exists():
            raise FileNotFoundError(f"Plan metadata not found: {session_id}")
        
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def cleanup_session(self, session_id: str) -> None:
        """
        清理 session 的所有 artifacts（可选）
        
        Args:
            session_id: Plan 执行的 session ID
        """
        session_dir = self.base_dir / session_id
        
        if not session_dir.exists():
            logger.warning(f"⚠️  Session dir not found: {session_id}")
            return
        
        try:
            import shutil
            shutil.rmtree(session_dir)
            logger.info(f"🗑️  Cleaned up session: {session_id}")
        except Exception as e:
            logger.error(f"❌ Failed to cleanup session {session_id}: {e}")
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        列出所有 session（用于调试和管理）
        
        Returns:
            Session 列表（包含 session_id, timestamp, step_count）
        """
        sessions = []
        
        for session_dir in self.base_dir.iterdir():
            if not session_dir.is_dir():
                continue
            
            session_id = session_dir.name
            
            try:
                # 读取 metadata
                metadata = self.load_plan_metadata(session_id)
                
                # 统计 step 数量
                step_files = list(session_dir.glob("step_*.json"))
                
                sessions.append({
                    "session_id": session_id,
                    "timestamp": metadata.get("timestamp"),
                    "step_count": len(step_files),
                    "plan_name": metadata.get("plan_config", {}).get("display_name")
                })
            except Exception as e:
                logger.warning(f"⚠️  Failed to load session {session_id}: {e}")
        
        return sessions


def generate_session_id() -> str:
    """
    生成唯一的 session ID
    
    格式: plan_{timestamp}_{uuid}
    
    Returns:
        Session ID 字符串
    """
    timestamp = int(time.time())
    unique_id = uuid.uuid4().hex[:8]
    return f"plan_{timestamp}_{unique_id}"

