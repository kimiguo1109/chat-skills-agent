"""
Memory Manager - 记忆管理器

负责管理用户的长期学习画像（UserLearningProfile）和短期会话上下文（SessionContext）。
支持内存和 S3 两种存储方式。
🆕 Phase 2.5: 支持 Artifact 自动卸载到 S3/本地文件系统。
"""
import os
import logging
import json
import asyncio
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
    
    # 🆕 服务启动 ID（类变量，整个进程共享）
    _server_start_id: str = None
    
    # 🆕 并发安全：用于保护 _conversation_sessions 字典的锁
    _session_lock: asyncio.Lock = None
    
    @classmethod
    def _get_session_lock(cls) -> asyncio.Lock:
        """获取或创建 session 锁（延迟初始化以兼容事件循环）"""
        if cls._session_lock is None:
            cls._session_lock = asyncio.Lock()
        return cls._session_lock
    
    @classmethod
    def get_server_start_id(cls) -> str:
        """获取或生成服务启动 ID（每次服务重启时生成新的）"""
        if cls._server_start_id is None:
            import uuid
            cls._server_start_id = str(uuid.uuid4())
            logger.info(f"🆕 Generated server_start_id: {cls._server_start_id[:8]}...")
        return cls._server_start_id
    
    def __init__(self, use_s3: Optional[bool] = None, local_storage_dir: Optional[str] = None):
        """
        初始化 Memory Manager
        
        Args:
            use_s3: 是否使用 S3 存储（None 时使用 settings 配置，False 强制内存，True 强制 S3）
            local_storage_dir: 本地存储目录（用于调试和查看memory内容）
        """
        # 确定是否使用 S3
        # 如果 use_s3=None，使用 settings 配置；否则使用传入的值
        use_s3_setting = use_s3 if use_s3 is not None else settings.USE_S3_STORAGE
        
        # 🆕 集成 S3StorageManager 和 ArtifactStorage
        # 如果配置启用 S3，始终创建 S3StorageManager（让它自己判断是否可用）
        # 这样 ConversationSessionManager 可以获得 s3_manager，即使 S3 暂时不可用
        if use_s3_setting:
            self.s3_manager = S3StorageManager()
            # 根据实际可用性更新 use_s3
            self.use_s3 = self.s3_manager.is_available()
            if not self.use_s3:
                logger.warning("⚠️  S3 configured but not available, falling back to local storage")
        else:
            self.s3_manager = None
            self.use_s3 = False
        
        # 内存存储
        self._user_profiles: Dict[str, UserLearningProfile] = {}
        self._session_contexts: Dict[str, SessionContext] = {}
        
        # 本地存储配置（用于调试）
        self.local_storage_dir = Path(local_storage_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "memory_storage"
        ))
        self.local_storage_dir.mkdir(parents=True, exist_ok=True)
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
    
    async def get_session_context(self, session_id: str, user_id: Optional[str] = None) -> SessionContext:
        """
        获取会话上下文
        
        Args:
            session_id: 会话 ID
            user_id: 用户 ID（可选，用于从 ConversationSessionManager 获取 inherited_topic）
        
        Returns:
            SessionContext: 会话上下文
        """
        if self.use_s3:
            return await self._get_session_context_from_s3(session_id, user_id)
        
        # 从内存获取，如果不存在则创建默认上下文
        if session_id not in self._session_contexts:
            logger.info(f"📝 Creating new session context for {session_id}")
            
            # 🆕 尝试从 ConversationSessionManager 获取 inherited_topic
            inherited_topic = None
            if user_id and user_id in self._conversation_sessions:
                conversation_mgr = self._conversation_sessions[user_id]
                inherited_topic = conversation_mgr.session_metadata.get("inherited_topic")
                if inherited_topic:
                    logger.info(f"📚 Using inherited_topic from conversation session: {inherited_topic}")
            
            self._session_contexts[session_id] = SessionContext(
                session_id=session_id,
                current_topic=inherited_topic,  # 🆕 使用继承的主题
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
    
    async def _get_session_context_from_s3(self, session_id: str, user_id: Optional[str] = None) -> SessionContext:
        """从 S3 获取会话上下文（占位符）"""
        # 占位符：使用内存存储
        if session_id not in self._session_contexts:
            # 🆕 尝试从 ConversationSessionManager 获取 inherited_topic
            inherited_topic = None
            if user_id and user_id in self._conversation_sessions:
                conversation_mgr = self._conversation_sessions[user_id]
                inherited_topic = conversation_mgr.session_metadata.get("inherited_topic")
                if inherited_topic:
                    logger.info(f"📚 Using inherited_topic from conversation session: {inherited_topic}")
            
            self._session_contexts[session_id] = SessionContext(
                session_id=session_id,
                current_topic=inherited_topic,  # 🆕 使用继承的主题
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
        
        # 🎚️ 存储策略：保存压缩的summary作为content，支持上下文卸载
        # 完整内容在MD文件中，这里只保存摘要用于LLM快速上下文加载
        summary_text = self._generate_summary(artifact, artifact_type)
        
        # 🔥 先使用 fallback 压缩作为 summary（用于 LLM 上下文）
        context_summary_placeholder = self._fallback_compression(artifact, artifact_type, topic)
        
        # 🆕 content 保存原始完整数据（用于引用解析），summary 保存压缩摘要（用于 LLM 上下文）
        record = ArtifactRecord(
            artifact_id=artifact_id,
            turn_number=self._get_turn_number(session_id),
            artifact_type=artifact_type,
            topic=topic,
            summary=context_summary_placeholder,  # 🆕 摘要放这里，用于 LLM 上下文
            content=artifact,  # 🆕 原始完整数据放这里，用于引用解析
            content_reference=None  # 不需要外部引用（完整内容在MD）
        )
        logger.info(f"📝 Artifact {artifact_id} recorded (full content: {content_size} chars, summary: {len(str(context_summary_placeholder))} chars)")
        
        # 添加到 session context
        session_context = await self.get_session_context(session_id)
        session_context.artifact_history.append(record)
        session_context.last_artifact_id = artifact_id
        await self.update_session_context(session_id, session_context)
        
        # 🆕 按需压缩策略（优化 token 消耗）
        # - 小 artifact (<1000 chars)：不压缩，直接使用 fallback summary
        # - 中等 artifact (1000-5000 chars)：使用 Gemini 压缩
        # - 大 artifact (>5000 chars)：必须压缩
        #
        # Token 成本分析 (Gemini 2.0 Flash Lite):
        # - Input: $0.075/M tokens → ~1900 tokens ≈ $0.00014
        # - Output: $0.30/M tokens → ~700 tokens ≈ $0.00021
        # - Total: ~$0.00035/次
        artifact_size = len(json.dumps(artifact, ensure_ascii=False))
        
        # 压缩阈值配置
        COMPRESSION_THRESHOLD = 1000  # 只对 >1000 chars 的 artifact 进行 LLM 压缩
        
        if artifact_size >= COMPRESSION_THRESHOLD:
            # 启动后台 Gemini 压缩
            logger.info(f"📊 Artifact size: {artifact_size} chars (>= {COMPRESSION_THRESHOLD}), triggering Gemini compression")
            task = asyncio.create_task(
                self._compress_artifact_async(artifact_id, artifact, artifact_type, topic, session_id, user_id)
            )
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            logger.debug(f"🔄 Started background Gemini compression for {artifact_id}")
        else:
            # 小 artifact：跳过 LLM 压缩，节省 token
            logger.info(f"📊 Artifact size: {artifact_size} chars (< {COMPRESSION_THRESHOLD}), skipping LLM compression (using rule-based summary)")
        
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
        """生成 artifact 摘要（用于显示）"""
        # 根据不同类型生成摘要
        if artifact_type == "explanation":
            concept = artifact.get("concept", "Unknown")
            return f"Explanation: {concept}"
        elif artifact_type == "quiz_set":
            num_questions = len(artifact.get("questions", []))
            return f"Quiz: {num_questions} questions"
        elif artifact_type == "flashcard_set":
            # 兼容新旧格式：cardList (新) 或 cards (旧)
            cards = artifact.get("cardList") or artifact.get("cards", [])
            num_cards = len(cards)
            return f"Flashcards: {num_cards} cards"
        elif artifact_type == "notes":
            title = artifact.get("structured_notes", {}).get("title", "Unknown")
            return f"Notes: {title}"
        else:
            return f"{artifact_type}"
    
    async def _compress_artifact_async(
        self,
        artifact_id: str,
        artifact: Dict[str, Any],
        artifact_type: str,
        topic: str,
        session_id: str,
        user_id: str = "unknown"  # 🆕 添加 user_id 参数
    ):
        """
        后台异步任务：使用 LLM 智能压缩 artifact
        
        执行流程：
        1. 调用 LLM 进行智能压缩
        2. 更新 session_context 中的 artifact record
        3. 不阻塞用户响应
        4. 🆕 记录 token 使用到 MemoryTokenTracker
        
        ⚠️ 注意：此方法会长时间运行 (~260s)，但不会阻塞用户
        """
        try:
            logger.info(f"🔄 Background compression started for {artifact_id}")
            logger.debug(f"   This will take ~260s but won't block user response")
            
            # 调用 LLM 进行智能压缩 (长时间运行)
            compressed_summary, token_usage = await self._create_context_summary(artifact, artifact_type, topic)
            
            # 🆕 记录 token 使用
            if token_usage and token_usage.get("total_tokens", 0) > 0:
                from app.services.memory_token_tracker import get_memory_token_tracker
                tracker = get_memory_token_tracker()
                tracker.record_compression(
                    user_id=user_id,
                    session_id=session_id,
                    artifact_id=artifact_id,
                    prompt_tokens=token_usage.get("prompt_tokens", 0),
                    completion_tokens=token_usage.get("completion_tokens", 0),
                    total_tokens=token_usage.get("total_tokens", 0),
                    model=token_usage.get("model", "gemini-2.5-flash")
                )
            
            # 更新 session context 中的 artifact record
            session_context = await self.get_session_context(session_id)
            
            for record in session_context.artifact_history:
                if record.artifact_id == artifact_id:
                    # 🆕 compressed_summary 现在始终是 string（在 _compress_artifact 中已转换）
                    record.summary = str(compressed_summary)
                    # 🔥 不覆盖 record.content，保留原始完整数据用于引用解析
                    logger.info(f"✅ Background compression complete for {artifact_id}, summary: {len(record.summary)} chars")
                    break
            
            # 保存更新后的 session context
            await self.update_session_context(session_id, session_context)
            logger.info(f"💾 Session context updated with compressed artifact")
            
        except Exception as e:
            logger.error(f"❌ Background compression failed for {artifact_id}: {e}")
            logger.exception(e)
            logger.debug(f"   Fallback summary will be used instead")
    
    async def _create_context_summary(self, artifact: Dict[str, Any], artifact_type: str, topic: str) -> Dict[str, Any]:
        """
        🆕 创建上下文友好的摘要（使用 LLM 智能压缩）
        
        策略：
        - 使用 summary_skill LLM 进行语义压缩
        - 目标压缩比 > 90% (e.g., 2000 tokens → < 200 tokens)
        - 保留逻辑关系，丢弃冗余描述
        
        Args:
            artifact: 原始 artifact 内容
            artifact_type: Artifact 类型
            topic: 主题
        
        Returns:
            压缩的 context summary（Dict）
        """
        try:
            import json
            from pathlib import Path
            
            # 加载 summary_skill prompt
            # __file__ = backend/app/core/memory_manager.py
            # parent = backend/app/core
            # parent.parent = backend/app
            # parent.parent.parent = backend
            summary_prompt_path = Path(__file__).parent.parent / "prompts" / "summary_skill.txt"
            
            if not summary_prompt_path.exists():
                logger.warning(f"⚠️ summary_skill.txt not found at {summary_prompt_path}, using fallback compression")
                return self._fallback_compression(artifact, artifact_type, topic)
            
            with open(summary_prompt_path, 'r', encoding='utf-8') as f:
                summary_prompt = f.read()
            
            # 构造压缩请求
            compression_input = {
                "interaction_type": self._map_artifact_type_to_interaction(artifact_type),
                "topic": topic,
                "ai_response": json.dumps(artifact, ensure_ascii=False),
                "artifact_type": artifact_type
            }
            
            # 添加参数 JSON
            params_json = json.dumps(compression_input, ensure_ascii=False, indent=2)
            full_prompt = f"{summary_prompt}\n\n## Input Parameters (JSON)\n\n```json\n{params_json}\n```"
            
            # 🔄 使用 Gemini 2.0 Flash Exp 进行快速压缩（不用 thinking 模型）
            from app.services.gemini import GeminiClient
            gemini = GeminiClient()
            
            response = await gemini.generate(
                prompt=full_prompt,
                response_format="json",
                temperature=0.3,  # 低温度，保证确定性输出
                thinking_budget=0,  # 🔧 禁用思考模式以确保完整输出
                return_thinking=False
            )
            
            # 🆕 提取 token 使用信息
            # 注意：Gemini 返回 input_tokens/output_tokens，需要映射到 prompt_tokens/completion_tokens
            token_usage = {}
            if isinstance(response, dict) and "usage" in response:
                usage = response["usage"]
                # Gemini 使用 input_tokens/output_tokens，但其他地方使用 prompt_tokens/completion_tokens
                input_t = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
                output_t = usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
                token_usage = {
                    "prompt_tokens": input_t,
                    "completion_tokens": output_t,
                    "total_tokens": usage.get("total_tokens", 0) or (input_t + output_t),
                    "model": "gemini-2.5-flash"
                }
                logger.info(f"📊 Compression token usage: input={input_t:,}, output={output_t:,}, total={token_usage['total_tokens']:,}")
            
            # 解析压缩结果
            if isinstance(response, dict) and "content" in response:
                content = response["content"]
                
                # content 可能是 str (JSON string) 或 dict (已解析的 JSON)
                if isinstance(content, str):
                    compressed = json.loads(content)
                elif isinstance(content, dict):
                    compressed = content
                else:
                    logger.warning(f"⚠️ Unexpected content type: {type(content)}, using fallback")
                    return self._fallback_compression(artifact, artifact_type, topic), {}
                
                original_size = len(json.dumps(artifact, ensure_ascii=False))
                
                # 🆕 将 Gemini 返回的 dict 转换为 string summary
                # ArtifactRecord.summary 必须是 string
                if isinstance(compressed, dict):
                    # 优先提取 context_summary 字段
                    if 'context_summary' in compressed:
                        summary_str = str(compressed['context_summary'])
                    # 否则尝试提取关键摘要字段
                    elif 'summary' in compressed:
                        summary_str = str(compressed['summary'])
                    elif 'mental_model' in compressed:
                        mental = compressed.get('mental_model', '')
                        key_concepts = compressed.get('key_concepts', [])
                        summary_str = f"[{artifact_type}] {topic}: {mental}. 关键概念: {', '.join(key_concepts[:3])}"
                    else:
                        # 将整个 dict 转为简洁的 JSON string
                        summary_str = json.dumps(compressed, ensure_ascii=False)[:300]
                else:
                    summary_str = str(compressed)
                
                compressed_size = len(summary_str)
                compression_ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
                
                logger.info(f"✅ LLM compressed {artifact_type}: {original_size} → {compressed_size} chars (-{compression_ratio:.1f}%)")
                return summary_str, token_usage  # 🆕 返回 tuple
            else:
                logger.warning("⚠️ LLM compression failed, using fallback")
                return self._fallback_compression(artifact, artifact_type, topic), {}
        
        except Exception as e:
            logger.error(f"❌ Error during LLM compression: {e}")
            return self._fallback_compression(artifact, artifact_type, topic), {}
    
    def _map_artifact_type_to_interaction(self, artifact_type: str) -> str:
        """将 artifact_type 映射到 interaction_type"""
        mapping = {
            "explanation": "explain",
            "quiz_set": "quiz",
            "flashcard_set": "flashcard"
        }
        return mapping.get(artifact_type, "chat")
    
    def _fallback_compression(self, artifact: Dict[str, Any], artifact_type: str, topic: str) -> str:
        """
        Fallback: 简单的基于规则的压缩（当 LLM 不可用时）
        
        🔧 重要：返回 string 而不是 dict，因为 ArtifactRecord.summary 期望 string
        """
        if artifact_type == "explanation":
            concept = artifact.get("concept", topic)
            intuition = artifact.get("intuition", "")[:100]
            examples = [ex.get("example", "")[:50] for ex in artifact.get("examples", [])[:2]]
            return f"[概念讲解] {concept}: {intuition}... 例子: {', '.join(examples)}"
        
        elif artifact_type == "quiz_set":
            questions = artifact.get("questions", [])
            q_summaries = [q.get("question_text", "")[:40] for q in questions[:3]]
            return f"[练习题] {topic}: {len(questions)}道题 - {'; '.join(q_summaries)}..."
        
        elif artifact_type == "flashcard_set":
            # 兼容新旧格式：cardList (新) 或 cards (旧)
            cards = artifact.get("cardList") or artifact.get("cards", [])
            card_fronts = [c.get("front", "")[:30] for c in cards[:3]]
            return f"[闪卡] {topic}: {len(cards)}张 - {'; '.join(card_fronts)}..."
        
        elif artifact_type == "mindmap":
            return f"[思维导图] {topic}: 结构化知识梳理"
        
        elif artifact_type == "notes":
            return f"[笔记] {topic}: 学习要点整理"
        
        else:
            return f"[{artifact_type}] {topic}: 学习内容"
    
    def get_conversation_session_manager(
        self,
        user_id: str
    ) -> ConversationSessionManager:
        """
        获取或创建用户的 ConversationSessionManager
        
        🔒 并发安全：使用双重检查锁定模式
        
        Args:
            user_id: 用户ID
        
        Returns:
            ConversationSessionManager 实例
        """
        # 🔒 第一次检查（无锁，快速路径）
        if user_id in self._conversation_sessions:
            return self._conversation_sessions[user_id]
        
        # 🔒 需要创建新的 session manager，使用同步锁保护
        import threading
        if not hasattr(self, '_sync_lock'):
            self._sync_lock = threading.Lock()
        
        with self._sync_lock:
            # 🔒 第二次检查（有锁，防止重复创建）
            if user_id not in self._conversation_sessions:
                # 创建新的 session manager
                storage_path = self.artifact_storage.base_dir / user_id
                storage_path.mkdir(parents=True, exist_ok=True)
                
                self._conversation_sessions[user_id] = ConversationSessionManager(
                    user_id=user_id,
                    storage_path=str(storage_path),
                    s3_manager=self.s3_manager,
                    server_start_id=self.get_server_start_id()  # 🆕 传递服务启动 ID
                )
                
                logger.info(f"✅ Created ConversationSessionManager for {user_id}")
        
        return self._conversation_sessions[user_id]

