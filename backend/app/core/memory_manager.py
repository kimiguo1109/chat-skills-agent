"""
Memory Manager - 记忆管理器

负责管理用户的长期学习画像（UserLearningProfile）和短期会话上下文（SessionContext）。
支持内存和 S3 两种存储方式。
🆕 Phase 2.5: 支持 Artifact 自动卸载到 S3/本地文件系统。
"""
import os
import logging
import json
from typing import Optional, Dict, Union, Any
from datetime import datetime
from pathlib import Path

from ..models.memory import UserLearningProfile, SessionContext, ArtifactRecord
from ..models.intent import MemorySummary
from ..config import settings
from .s3_storage import S3StorageManager
from .artifact_storage import ArtifactStorage
from .conversation_session_manager import ConversationSessionManager

logger = logging.getLogger(__name__)


class MemoryManager:
    """记忆管理器 - 管理用户学习画像和会话上下文"""
    
    def __init__(self, use_s3: Optional[bool] = None, local_storage_dir: Optional[str] = None):
        """
        初始化 Memory Manager
        
        Args:
            use_s3: 是否使用 S3 存储（None 时使用 settings 配置，False 强制内存，True 强制 S3）
            local_storage_dir: 本地存储目录（用于调试和查看memory内容）
        """
        self.use_s3 = use_s3 if use_s3 is not None else settings.USE_S3_STORAGE
        
        # 内存存储
        self._user_profiles: Dict[str, UserLearningProfile] = {}
        self._session_contexts: Dict[str, SessionContext] = {}
        
        # 本地存储配置（用于调试）
        self.local_storage_dir = Path(local_storage_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "memory_storage"
        ))
        self.local_storage_dir.mkdir(parents=True, exist_ok=True)
        
        # 🆕 集成 S3StorageManager 和 ArtifactStorage
        self.s3_manager = S3StorageManager() if self.use_s3 else None
        self.artifact_storage = ArtifactStorage(
            base_dir="artifacts",
            s3_manager=self.s3_manager
        )
        
        # 🆕 Conversation Session Managers (每个用户一个)
        self._conversation_sessions: Dict[str, ConversationSessionManager] = {}
        
        logger.info(
            f"✅ MemoryManager initialized "
            f"(S3: {self.use_s3}, Local: {self.local_storage_dir}, "
            f"Artifact Storage: S3={self.artifact_storage.use_s3})"
        )
        
        # 🆕 从本地文件加载现有数据（用于开发调试）
        if not self.use_s3:
            self._load_from_local_files()
    
    # ============= User Learning Profile =============
    
    async def get_user_profile(self, user_id: str) -> UserLearningProfile:
        """
        获取用户学习画像
        
        Args:
            user_id: 用户 ID
        
        Returns:
            UserLearningProfile: 用户学习画像
        """
        if self.use_s3:
            return await self._get_user_profile_from_s3(user_id)
        
        # 从内存获取，如果不存在则创建默认画像
        if user_id not in self._user_profiles:
            logger.info(f"📝 Creating new user profile for {user_id}")
            self._user_profiles[user_id] = UserLearningProfile(
                user_id=user_id,
                mastery={},
                preferences={},
                history={
                    "quiz_sessions": 0,
                    "homework_help_count": 0,
                    "topics_visited": []
                }
            )
        
        return self._user_profiles[user_id]
    
    async def update_user_profile(
        self,
        user_id: str,
        profile: UserLearningProfile
    ) -> UserLearningProfile:
        """
        更新用户学习画像
        
        Args:
            user_id: 用户 ID
            profile: 更新后的画像
        
        Returns:
            UserLearningProfile: 更新后的画像
        """
        profile.updated_at = datetime.now()
        
        if self.use_s3:
            return await self._update_user_profile_to_s3(user_id, profile)
        
        self._user_profiles[user_id] = profile
        logger.info(f"✅ Updated user profile for {user_id}")
        
        # 保存到本地文件（用于调试）
        await self._save_to_local_file(user_id, profile, "profile")
        
        return profile
    
    # ============= Session Context =============
    
    async def get_session_context(self, session_id: str) -> SessionContext:
        """
        获取会话上下文
        
        Args:
            session_id: 会话 ID
        
        Returns:
            SessionContext: 会话上下文
        """
        if self.use_s3:
            return await self._get_session_context_from_s3(session_id)
        
        # 从内存获取，如果不存在则创建默认上下文
        if session_id not in self._session_contexts:
            logger.info(f"📝 Creating new session context for {session_id}")
            self._session_contexts[session_id] = SessionContext(
                session_id=session_id,
                current_topic=None,
                recent_intents=[],
                last_artifact=None,
                last_user_message=""
            )
        
        return self._session_contexts[session_id]
    
    async def update_session_context(
        self,
        session_id: str,
        context: SessionContext
    ) -> SessionContext:
        """
        更新会话上下文
        
        Args:
            session_id: 会话 ID
            context: 更新后的上下文
        
        Returns:
            SessionContext: 更新后的上下文
        """
        context.updated_at = datetime.now()
        
        if self.use_s3:
            return await self._update_session_context_to_s3(session_id, context)
        
        self._session_contexts[session_id] = context
        logger.info(f"✅ Updated session context for {session_id}")
        
        # 保存到本地文件（用于调试）
        await self._save_to_local_file(session_id, context, "session")
        
        return context
    
    # ============= Memory Summary =============
    
    async def generate_memory_summary(
        self,
        user_id: str,
        session_id: str
    ) -> MemorySummary:
        """
        生成记忆摘要，用于 Intent Router
        包含学习偏好分析！
        
        Args:
            user_id: 用户 ID
            session_id: 会话 ID
        
        Returns:
            MemorySummary: 记忆摘要
        """
        # 获取用户画像和会话上下文
        user_profile = await self.get_user_profile(user_id)
        session_context = await self.get_session_context(session_id)
        
        # 分析用户的Skill使用偏好
        skill_preference_hint = self._analyze_skill_preference(session_context.recent_intents)
        
        # 生成 topic_hint
        topic_hint = session_context.current_topic
        
        # 生成 user_mastery_hint（如果有当前主题）
        user_mastery_hint = None
        if topic_hint and topic_hint in user_profile.mastery:
            user_mastery_hint = user_profile.mastery[topic_hint]
        
        # 生成 recent_behavior 描述（包含偏好提示）
        recent_behavior = self._generate_behavior_description(
            user_profile,
            session_context,
            skill_preference_hint
        )
        
        summary = MemorySummary(
            topic_hint=topic_hint,
            user_mastery_hint=user_mastery_hint,
            recent_behavior=recent_behavior
        )
        
        # 使用 INFO 级别日志，便于查看偏好是否生效
        logger.info(f"📊 Generated memory summary: recent_behavior='{recent_behavior}'")
        if skill_preference_hint:
            logger.info(f"✨ User preference detected: {skill_preference_hint}")
        
        return summary
    
    def _generate_behavior_description(
        self,
        profile: UserLearningProfile,
        context: SessionContext,
        skill_preference_hint: str = ""
    ) -> str:
        """
        生成用户行为描述
        
        Args:
            profile: 用户画像
            context: 会话上下文
            skill_preference_hint: 学习偏好提示
        
        Returns:
            str: 行为描述
        """
        behaviors = []
        
        # 添加学习偏好提示（如果有）
        if skill_preference_hint:
            behaviors.append(skill_preference_hint)
        
        # 最近的意图
        if context.recent_intents:
            last_intent = context.recent_intents[-1] if context.recent_intents else None
            if last_intent == "quiz_request":
                behaviors.append("刚做过练习题")
            elif last_intent == "explain_request":
                behaviors.append("刚看过概念讲解")
            elif last_intent == "flashcard_request":
                behaviors.append("刚学过闪卡")
        
        # 偏好
        if profile.preferences.get("preferred_artifact"):
            pref = profile.preferences["preferred_artifact"]
            if pref == "quiz":
                behaviors.append("偏好做练习")
            elif pref == "explanation":
                behaviors.append("偏好看讲解")
        
        # 历史统计
        quiz_count = profile.history.get("quiz_sessions", 0)
        if quiz_count > 0:
            behaviors.append(f"已做过{quiz_count}次练习")
        
        return "；".join(behaviors) if behaviors else "新用户"
    
    def _analyze_skill_preference(self, recent_intents: list) -> str:
        """
        分析用户的Skill使用偏好
        
        Args:
            recent_intents: 最近的意图列表
        
        Returns:
            str: 偏好提示（如果有明显偏好）
        """
        if not recent_intents or len(recent_intents) < 2:  # 降低阈值：从3改为2
            return ""
        
        # 统计各个意图的出现次数
        intent_counts = {}
        for intent in recent_intents[-10:]:  # 只看最近10次
            intent_counts[intent] = intent_counts.get(intent, 0) + 1
        
        total = len(recent_intents[-10:])
        
        # 降低偏好触发阈值：从 >=60% 改为 >=50%
        for intent, count in intent_counts.items():
            preference_ratio = count / total
            if preference_ratio >= 0.5:
                intent_name_map = {
                    "flashcard_request": "flashcards",
                    "quiz_request": "quiz practice",
                    "explain_request": "concept explanations",
                    "learning_bundle": "complete learning packages"
                }
                intent_display = intent_name_map.get(intent, intent)
                
                # 增强偏好强度表达
                if preference_ratio >= 0.75:
                    strength = "Very strongly"
                elif preference_ratio >= 0.60:
                    strength = "Strongly"
                else:
                    strength = "Prefers"
                
                return f"[User Preference: {strength} prefers {intent_display} for learning ({int(preference_ratio*100)}% of recent activities)]"
        
        return ""
    
    # ============= S3 操作（占位符，实际使用时需要 boto3）=============
    
    async def _get_user_profile_from_s3(self, user_id: str) -> UserLearningProfile:
        """从 S3 获取用户画像（占位符）"""
        # 占位符：使用内存存储
        if user_id not in self._user_profiles:
            self._user_profiles[user_id] = UserLearningProfile(
                user_id=user_id,
                mastery={},
                preferences={},
                history={
                    "quiz_sessions": 0,
                    "homework_help_count": 0,
                    "topics_visited": []
                }
            )
        return self._user_profiles[user_id]
    
    async def _update_user_profile_to_s3(
        self,
        user_id: str,
        profile: UserLearningProfile
    ) -> UserLearningProfile:
        """更新用户画像到 S3（占位符）"""
        # 占位符：使用内存存储
        self._user_profiles[user_id] = profile
        return profile
    
    async def _get_session_context_from_s3(self, session_id: str) -> SessionContext:
        """从 S3 获取会话上下文（占位符）"""
        # 占位符：使用内存存储
        if session_id not in self._session_contexts:
            self._session_contexts[session_id] = SessionContext(
                session_id=session_id,
                current_topic=None,
                recent_intents=[],
                last_artifact=None,
                last_user_message=""
            )
        return self._session_contexts[session_id]
    
    async def _update_session_context_to_s3(
        self,
        session_id: str,
        context: SessionContext
    ) -> SessionContext:
        """更新会话上下文到 S3（占位符）"""
        # 占位符：使用内存存储
        self._session_contexts[session_id] = context
        return context
    
    # ============= 本地文件存储（用于调试） =============
    
    async def _save_to_local_file(
        self,
        id_str: str,
        data: Union[UserLearningProfile, SessionContext],
        data_type: str
    ):
        """
        保存数据到本地文件（用于调试和查看memory内容）
        
        Args:
            id_str: 用户ID或会话ID
            data: UserLearningProfile 或 SessionContext
            data_type: "profile" 或 "session"
        """
        try:
            import json
            from datetime import datetime
            
            # 构建文件路径
            filename = f"{data_type}_{id_str}.json"
            filepath = os.path.join(self.local_storage_dir, filename)
            
            # 转换为字典并添加时间戳
            if isinstance(data, (UserLearningProfile, SessionContext)):
                data_dict = data.model_dump()
            else:
                data_dict = dict(data)
            
            # 🆕 转换所有datetime对象为ISO格式字符串
            def convert_datetime(obj):
                """递归转换datetime对象"""
                if isinstance(obj, datetime):
                    return obj.isoformat()
                elif isinstance(obj, dict):
                    return {k: convert_datetime(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_datetime(item) for item in obj]
                else:
                    return obj
            
            data_dict = convert_datetime(data_dict)
            data_dict["_last_updated"] = datetime.now().isoformat()
            
            # 写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data_dict, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"💾 Saved {data_type} to {filepath}")
            
        except Exception as e:
            logger.warning(f"⚠️  Failed to save {data_type} to local file: {e}")
    
    # ============= Artifact Search =============
    
    async def find_artifact_by_id(self, artifact_id: str):
        """
        从所有 sessions 中查找指定 ID 的 artifact
        
        Args:
            artifact_id: Artifact ID
        
        Returns:
            ArtifactRecord 或 None
        """
        # 遍历所有 session contexts
        for session_id, session_context in self._session_contexts.items():
            if session_context.artifact_history:
                for artifact in session_context.artifact_history:
                    if artifact.artifact_id == artifact_id:
                        logger.info(f"✅ Found artifact {artifact_id} in session {session_id}")
                        return artifact
        
        logger.warning(f"⚠️  Artifact {artifact_id} not found in any session")
        return None
    
    # ============= Local File Loading =============
    
    def _load_from_local_files(self):
        """从本地文件加载已存储的 session contexts（用于开发调试）"""
        try:
            # 扫描 memory_storage 目录中的 session 文件
            import glob
            session_files = glob.glob(os.path.join(self.local_storage_dir, "*-session.json"))
            
            loaded_count = 0
            for filepath in session_files:
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # 提取 session_id
                    session_id = data.get("session_id")
                    if not session_id:
                        continue
                    
                    # 转换 artifact_history 中的 datetime 字符串
                    if "artifact_history" in data and data["artifact_history"]:
                        for artifact in data["artifact_history"]:
                            if "timestamp" in artifact and isinstance(artifact["timestamp"], str):
                                artifact["timestamp"] = datetime.fromisoformat(artifact["timestamp"])
                    
                    # 转换 updated_at
                    if "updated_at" in data and isinstance(data["updated_at"], str):
                        data["updated_at"] = datetime.fromisoformat(data["updated_at"])
                    
                    # 创建 SessionContext 对象
                    session_context = SessionContext(**data)
                    self._session_contexts[session_id] = session_context
                    loaded_count += 1
                    
                    logger.info(f"📂 Loaded session {session_id} with {len(session_context.artifact_history)} artifacts")
                    
                except Exception as e:
                    logger.warning(f"⚠️  Failed to load {filepath}: {e}")
            
            if loaded_count > 0:
                logger.info(f"✅ Loaded {loaded_count} session(s) from local files")
            
        except Exception as e:
            logger.warning(f"⚠️  Failed to load from local files: {e}")
    
    # ============= Artifact Management (Phase 2.5) =============
    
    async def save_artifact(
        self,
        session_id: str,
        artifact: Dict[str, Any],
        artifact_type: str,
        topic: str,
        user_id: str
    ) -> ArtifactRecord:
        """
        保存 artifact（自动卸载到 S3/本地）
        
        决策逻辑：
        - 小内容 (< 500 bytes): inline 存储（直接存储在 ArtifactRecord.content）
        - 大内容 (>= 500 bytes): 卸载到 S3/文件系统（存储引用）
        
        Args:
            session_id: 会话ID
            artifact: Artifact 内容
            artifact_type: 类型（explanation, quiz_set, flashcard_set等）
            topic: 主题
            user_id: 用户ID
        
        Returns:
            ArtifactRecord 实例
        
        Raises:
            ValueError: 内容验证失败
            IOError: 存储失败
        """
        artifact_id = self._generate_artifact_id(artifact_type, topic)
        
        # 🔧 数据验证
        if not self._validate_artifact_content(artifact):
            logger.error(f"❌ Invalid artifact content for {artifact_id}")
            # 存到隔离区
            self._quarantine_invalid_artifact(artifact_id, artifact, "validation_failed")
            raise ValueError(f"Invalid artifact content: {artifact_id}")
        
        # 估算大小
        try:
            content_json = json.dumps(artifact, ensure_ascii=False)
            content_size = len(content_json)
        except Exception as e:
            logger.error(f"❌ Failed to serialize artifact {artifact_id}: {e}")
            self._quarantine_invalid_artifact(artifact_id, artifact, "serialization_failed")
            raise ValueError(f"Cannot serialize artifact: {e}") from e
        
        # 🎚️ 存储策略判断
        # 设计理念：所有 artifacts 都存储到 S3，构建完整的用户画像
        # 用户画像对于意图识别、个性化学习内容生成至关重要
        OFFLOAD_THRESHOLD = 0  # bytes - 所有内容都上传 S3
        
        if content_size >= OFFLOAD_THRESHOLD:  # 现在始终为 True
            # 卸载到 S3/文件系统
            try:
                # 🔥 修复：user_id 已经包含 "user_" 前缀，不需要再加
                storage_session_id = user_id if user_id.startswith("user_") else f"user_{user_id}"
                
                reference = self.artifact_storage.save_step_result(
                    session_id=storage_session_id,
                    step_id=artifact_id,
                    result=artifact,
                    metadata={
                        "artifact_type": artifact_type,
                        "topic": topic,
                        "size_bytes": content_size
                    }
                )
                
                # 创建引用记录
                record = ArtifactRecord(
                    artifact_id=artifact_id,
                    turn_number=self._get_turn_number(session_id),
                    artifact_type=artifact_type,
                    topic=topic,
                    summary=self._generate_summary(artifact, artifact_type),
                    content_reference=reference,  # S3 URI 或本地路径
                    content=None  # 不存内容
                )
                logger.info(f"💾 Artifact {artifact_id} offloaded: {reference} ({content_size} bytes)")
            except Exception as e:
                logger.error(f"❌ Failed to offload artifact {artifact_id}: {e}")
                # 降级：inline 存储
                record = ArtifactRecord(
                    artifact_id=artifact_id,
                    turn_number=self._get_turn_number(session_id),
                    artifact_type=artifact_type,
                    topic=topic,
                    summary=self._generate_summary(artifact, artifact_type),
                    content=artifact,  # 降级到 inline
                    content_reference=None
                )
                logger.warning(f"⚠️  Fallback to inline storage for {artifact_id}")
        else:
            # 小内容：inline 存储
            record = ArtifactRecord(
                artifact_id=artifact_id,
                turn_number=self._get_turn_number(session_id),
                artifact_type=artifact_type,
                topic=topic,
                summary=self._generate_summary(artifact, artifact_type),
                content=artifact,
                content_reference=None
            )
            logger.info(f"📄 Artifact {artifact_id} stored inline ({content_size} bytes)")
        
        # 添加到 session context
        session_context = await self.get_session_context(session_id)
        session_context.artifact_history.append(record)
        session_context.last_artifact_id = artifact_id
        await self.update_session_context(session_id, session_context)
        
        return record
    
    async def get_artifact(
        self,
        artifact_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        获取 artifact 内容（按需加载）
        
        - 如果是 inline 存储：直接返回 content
        - 如果是外部存储：从 S3/文件加载
        
        Args:
            artifact_id: Artifact ID
        
        Returns:
            Artifact 内容或 None
        """
        # 查找 artifact record
        record = self._find_artifact_record(artifact_id)
        if not record:
            logger.warning(f"⚠️  Artifact {artifact_id} not found")
            return None
        
        # inline 存储
        if record.content is not None:
            logger.debug(f"📄 Loading inline artifact {artifact_id}")
            return record.content
        
        # 外部存储（S3/本地）
        if record.content_reference:
            try:
                content = self.artifact_storage.load_artifact_by_reference(record.content_reference)
                logger.debug(f"💾 Loaded artifact {artifact_id} from {record.storage_type}")
                return content
            except Exception as e:
                logger.error(f"❌ Failed to load artifact {artifact_id}: {e}")
                return None
        
        logger.warning(f"⚠️  Artifact {artifact_id} has no content or reference")
        return None
    
    def _find_artifact_record(self, artifact_id: str) -> Optional[ArtifactRecord]:
        """在所有 session contexts 中查找 artifact record"""
        for session_context in self._session_contexts.values():
            for artifact in session_context.artifact_history:
                if artifact.artifact_id == artifact_id:
                    return artifact
        return None
    
    def _validate_artifact_content(self, content: Dict[str, Any]) -> bool:
        """
        验证 artifact 内容
        
        规则：
        1. 必须是字典
        2. 必须可 JSON 序列化
        3. 大小 < 10MB
        """
        if not isinstance(content, dict):
            return False
        
        try:
            content_json = json.dumps(content, ensure_ascii=False)
            MAX_SIZE = 10 * 1024 * 1024  # 10MB
            return len(content_json) <= MAX_SIZE
        except:
            return False
    
    def _quarantine_invalid_artifact(
        self,
        artifact_id: str,
        content: Any,
        reason: str
    ):
        """
        将无效 artifact 存到隔离区（用于后续分析）
        """
        quarantine_dir = Path("quarantine")
        quarantine_dir.mkdir(exist_ok=True)
        
        quarantine_file = quarantine_dir / f"{artifact_id}_{reason}.json"
        try:
            with open(quarantine_file, "w", encoding="utf-8") as f:
                json.dump({
                    "artifact_id": artifact_id,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat(),
                    "content": str(content)  # 强制转字符串
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"🔒 Quarantined invalid artifact: {quarantine_file}")
        except Exception as e:
            logger.error(f"❌ Failed to quarantine artifact: {e}")
    
    def _generate_artifact_id(self, artifact_type: str, topic: str) -> str:
        """生成唯一的 artifact ID"""
        import uuid
        short_id = uuid.uuid4().hex[:8]
        timestamp = int(datetime.now().timestamp())
        # artifact_explanation_physics_12345678_1699999999
        safe_topic = topic.replace(" ", "_").replace("/", "_")[:20]
        return f"artifact_{artifact_type}_{safe_topic}_{short_id}_{timestamp}"
    
    def _get_turn_number(self, session_id: str) -> int:
        """获取当前会话的 turn number"""
        session_context = self._session_contexts.get(session_id)
        if session_context:
            return len(session_context.artifact_history) + 1
        return 1
    
    def _generate_summary(self, artifact: Dict[str, Any], artifact_type: str) -> str:
        """生成 artifact 摘要"""
        # 根据不同类型生成摘要
        if artifact_type == "explanation":
            concept = artifact.get("concept", "Unknown")
            return f"Explanation: {concept}"
        elif artifact_type == "quiz_set":
            num_questions = len(artifact.get("questions", []))
            return f"Quiz: {num_questions} questions"
        elif artifact_type == "flashcard_set":
            num_cards = len(artifact.get("cards", []))
            return f"Flashcards: {num_cards} cards"
        elif artifact_type == "notes":
            title = artifact.get("structured_notes", {}).get("title", "Unknown")
            return f"Notes: {title}"
        else:
            return f"{artifact_type}"
    
    def get_conversation_session_manager(
        self,
        user_id: str
    ) -> ConversationSessionManager:
        """
        获取或创建用户的 ConversationSessionManager
        
        Args:
            user_id: 用户ID
        
        Returns:
            ConversationSessionManager 实例
        """
        if user_id not in self._conversation_sessions:
            # 创建新的 session manager
            storage_path = self.artifact_storage.base_dir / user_id
            storage_path.mkdir(parents=True, exist_ok=True)
            
            self._conversation_sessions[user_id] = ConversationSessionManager(
                user_id=user_id,
                storage_path=str(storage_path),
                s3_manager=self.s3_manager
            )
            
            logger.info(f"✅ Created ConversationSessionManager for {user_id}")
        
        return self._conversation_sessions[user_id]

