"""
Conversation Session Manager - 对话 Session 管理器

核心功能：
1. 🆕 智能长度检测，自动分割 MD（替代时间 cooldown）
2. 🆕 上下文继承（summary + 主题 + artifacts）
3. 生成 Markdown 格式的对话记录
4. 嵌入 JSON 结构化数据
5. Session 互联（跨 session 引用）
6. S3 同步
7. 🆕 智能压缩（保留最近对话，压缩旧对话）
"""

import os
import json
import logging
import re
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ConversationSessionManager:
    """
    管理连续对话 session
    
    🆕 核心逻辑（智能长度分割）：
    - 检测 MD 文件长度（字符数 or token 估算）
    - 软限制（50K chars）：开始压缩旧对话
    - 硬限制（100K chars）：强制创建新 MD
    - 新 MD 继承上下文（summary + 主题 + artifacts）
    - 兜底：长时间不活动（1 小时）也新建 MD
    """
    
    # 🆕 长度阈值策略（用于触发压缩，不再强制分卷）
    SOFT_LIMIT_CHARS = 50_000   # 50KB: 开始压缩旧对话
    HARD_LIMIT_CHARS = 100_000  # 100KB: 强制压缩（不分卷）
    MAX_LINES = 2000            # 2000行: 备选阈值
    TOKEN_ESTIMATION_RATIO = 0.4  # 1 char ≈ 0.4 tokens（中英文混合）
    
    # 🆕 Turn 数量阈值（触发压缩，不分卷）
    COMPRESS_TRIGGER_TURNS = 30   # 30 turns: 触发压缩检查
    KEEP_RECENT_TURNS = 10        # 保留最近 10 轮完整对话，其余压缩为 summary
    
    # 🆕 分卷条件（仅当用户明确要求或特殊情况）
    # 不再基于 turn 数强制分卷
    
    # 兜底：时间 cooldown（长时间不活动才考虑新建）
    INACTIVITY_TIMEOUT = 3600  # 1 小时（秒）
    
    # 🆕 服务启动标志（全局，用于检测服务重启）
    _server_start_id: str = None
    
    def __init__(
        self,
        user_id: str,
        storage_path: str,
        s3_manager: Optional[Any] = None,
        server_start_id: Optional[str] = None
    ):
        """
        初始化 Session 管理器
        
        Args:
            user_id: 用户 ID
            storage_path: 本地存储路径（如：backend/artifacts/user_kimi/）
            s3_manager: S3 存储管理器（可选）
            server_start_id: 服务启动 ID（用于检测服务重启）
        """
        self.user_id = user_id
        self.storage_path = Path(storage_path)
        self.s3_manager = s3_manager
        
        # 🆕 记录当前服务启动 ID
        self._current_server_start_id = server_start_id
        
        # 🔒 并发安全：写入锁，防止同一用户的并发请求导致文件损坏
        self._write_lock = asyncio.Lock()
        
        # 确保存储目录存在
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # 当前 session 状态
        self.current_session_id: Optional[str] = None
        self.last_activity_time: Optional[datetime] = None
        self.current_session_file: Optional[Path] = None
        self.turn_counter: int = 0
        
        # Session 元数据
        self.session_metadata: Dict[str, Any] = {}
        
        # 🆕 尝试恢复最新 session（如果未超过阈值）
        self._try_restore_latest_session()
        
        logger.info(f"✅ ConversationSessionManager initialized for user: {user_id}")
    
    def _try_restore_latest_session(self):
        """
        🆕 尝试恢复最新的 session（如果未超过阈值）
        
        逻辑：
        1. 查找最新的 session MD 文件
        2. 检查文件大小/行数是否在阈值以内
        3. 如果在阈值以内，恢复该 session 状态
        4. 否则，保持 current_session_id = None（会在下次请求时新建）
        """
        try:
            # 查找最新的 session 文件
            session_files = sorted(
                self.storage_path.glob("session_*.md"),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )
            
            if not session_files:
                logger.info("📝 No existing sessions found, will create new one")
                return
            
            latest_file = session_files[0]
            
            # 检查文件大小
            file_size = latest_file.stat().st_size
            file_chars = len(latest_file.read_text(encoding='utf-8'))
            file_lines = sum(1 for _ in open(latest_file, 'r', encoding='utf-8'))
            
            logger.info(
                f"📊 Latest session: {latest_file.name} | "
                f"Size: {file_size/1024:.1f}KB | Chars: {file_chars:,} | Lines: {file_lines}"
            )
            
            # 检查是否超过阈值
            if file_chars >= self.HARD_LIMIT_CHARS:
                logger.info(f"📏 Latest session exceeds hard limit ({file_chars:,} >= {self.HARD_LIMIT_CHARS:,}), will create new")
                return
            
            if file_lines >= self.MAX_LINES:
                logger.info(f"📏 Latest session exceeds max lines ({file_lines} >= {self.MAX_LINES}), will create new")
                return
            
            # 🆕 检查服务启动 ID（如果 metadata 中记录了不同的 server_start_id，说明服务重启过）
            metadata_file = latest_file.with_suffix('.md').with_name(
                latest_file.stem + '_metadata.json'
            )
            if metadata_file.exists():
                import json
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    
                    old_server_id = metadata.get('server_start_id')
                    if old_server_id and self._current_server_start_id and old_server_id != self._current_server_start_id:
                        logger.info(f"🔄 Server restarted (old: {old_server_id[:8]}..., new: {self._current_server_start_id[:8]}...), will create new session")
                        return
                except Exception as e:
                    logger.warning(f"⚠️  Failed to read metadata: {e}")
            
            # ✅ 恢复 session
            session_id = latest_file.stem  # 如 "session_20251125_082222"
            self.current_session_id = session_id
            self.current_session_file = latest_file
            self.last_activity_time = datetime.fromtimestamp(latest_file.stat().st_mtime)
            
            # 从 metadata 恢复 turn counter
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    self.turn_counter = metadata.get('total_turns', 0)
                    self.session_metadata = metadata
                except Exception as e:
                    logger.warning(f"⚠️  Failed to restore metadata: {e}")
                    self.turn_counter = self._count_turns_from_file(latest_file)
            else:
                self.turn_counter = self._count_turns_from_file(latest_file)
            
            logger.info(
                f"♻️  Restored session: {session_id} | "
                f"Turns: {self.turn_counter} | Chars: {file_chars:,}/{self.HARD_LIMIT_CHARS:,}"
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to restore session: {e}")
            # 失败时保持 None，下次请求会新建
    
    def _count_turns_from_file(self, file_path: Path) -> int:
        """从 MD 文件统计 turn 数量"""
        try:
            content = file_path.read_text(encoding='utf-8')
            # 统计 "## Turn" 的数量
            return content.count("## Turn ")
        except Exception:
            return 0
    
    async def start_or_continue_session(
        self,
        user_message: str,
        timestamp: Optional[datetime] = None,
        session_id: Optional[str] = None
    ) -> str:
        """
        🆕 开始或继续 session（支持强制指定 session_id）
        
        逻辑：
        1. 如果传入 session_id，强制使用该 session（用于 API 调用）
        2. 否则自动判断是否需要新 session
        3. 压缩策略控制文件大小
        
        Args:
            user_message: 用户消息（用于检测关联和断点）
            timestamp: 当前时间戳（可选，默认为 now）
            session_id: 强制使用的 session_id（可选，来自 API 调用）
        
        Returns:
            session_id
        """
        now = timestamp or datetime.now()
        
        # 🆕 如果传入了明确的 session_id，强制使用该 session
        if session_id:
            await self._force_use_session(session_id, now)
            logger.info(f"📌 Forced to use session: {session_id}")
        # 检查是否需要新 session
        elif self._should_start_new_session(now, user_message):
            # 创建新 session（带上下文继承）
            await self._start_new_session(now, user_message)
            logger.info(f"🆕 Started new session: {self.current_session_id}")
        else:
            # 继续当前 session
            logger.info(f"♻️  Continuing session: {self.current_session_id}")
        
        # 更新最后活动时间
        self.last_activity_time = now
        
        return self.current_session_id
    
    async def _force_use_session(self, session_id: str, timestamp: datetime):
        """
        🆕 强制使用指定的 session（用于 API 传入的 session_id）
        
        逻辑：
        1. 如果 session 文件存在，检查 server_start_id
        2. 如果服务重启了，归档旧 session 并重新创建
        3. 否则加载并继续
        4. 如果不存在，创建新的（使用传入的 session_id）
        """
        session_file = self.storage_path / f"{session_id}.md"
        metadata_file = self.storage_path / f"{session_id}_metadata.json"
        
        if session_file.exists():
            # 🆕 检查 server_start_id（服务重启检测）
            should_archive = False
            old_server_id = None
            
            if metadata_file.exists():
                try:
                    import json
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        old_metadata = json.load(f)
                    old_server_id = old_metadata.get('server_start_id')
                    
                    # 🔧 检查服务是否重启
                    if old_server_id and self._current_server_start_id and old_server_id != self._current_server_start_id:
                        logger.info(f"🔄 Server restarted (old: {old_server_id[:8]}..., new: {self._current_server_start_id[:8]}...), archiving old session")
                        should_archive = True
                except Exception as e:
                    logger.warning(f"⚠️ Failed to check server_start_id: {e}")
            
            if should_archive:
                # 🆕 归档旧 session
                archive_timestamp = timestamp.strftime("%Y%m%d_%H%M%S")
                archive_file = self.storage_path / f"{session_id}_archived_{archive_timestamp}.md"
                
                try:
                    # 移动旧的 MD 文件到归档
                    import shutil
                    shutil.move(str(session_file), str(archive_file))
                    logger.info(f"📦 Archived old session to: {archive_file.name}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to archive old session: {e}")
                
                # 创建新的 session（重置 turn_counter）
                self.current_session_id = session_id
                self.current_session_file = session_file
                self.turn_counter = 0
                
                # 初始化新的 metadata
                self.session_metadata = {
                    "session_id": session_id,
                    "user_id": self.user_id,
                    "start_time": timestamp.isoformat(),
                    "last_updated": timestamp.isoformat(),
                    "status": "active",
                    "total_turns": 0,
                    "inherited_context": {},
                    "previous_session_id": None,
                    "topics": [],
                    "last_topic": None,
                    "skills_used": {},
                    "artifacts_generated": [],
                    "server_start_id": self._current_server_start_id
                }
                
                # 创建新的 MD 文件头
                await self._write_session_header_with_inheritance({})
                logger.info(f"📝 Created new session after server restart: {session_id}")
                return
            
            # 正常加载现有 session
            self.current_session_id = session_id
            self.current_session_file = session_file
            
            # 加载 metadata
            if metadata_file.exists():
                try:
                    import json
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        self.session_metadata = json.load(f)
                    
                    # 🔧 使用 MD 文件中实际的 turn 数（更可靠）
                    actual_turns = self._count_turns_from_file(session_file)
                    metadata_turns = self.session_metadata.get('total_turns', 0)
                    
                    # 如果不一致，以 MD 文件为准
                    if actual_turns != metadata_turns:
                        logger.warning(f"⚠️ Turn count mismatch: MD={actual_turns}, metadata={metadata_turns}, using MD count")
                        self.turn_counter = actual_turns
                        self.session_metadata['total_turns'] = actual_turns
                    else:
                        self.turn_counter = metadata_turns
                except Exception as e:
                    logger.warning(f"⚠️ Failed to load metadata for {session_id}: {e}")
                    self.turn_counter = self._count_turns_from_file(session_file)
            else:
                self.turn_counter = self._count_turns_from_file(session_file)
            
            logger.info(f"📂 Loaded existing session: {session_id} (turns: {self.turn_counter})")
        else:
            # 创建新 session（使用传入的 session_id）
            self.current_session_id = session_id
            self.current_session_file = session_file
            self.turn_counter = 0
            
            # 初始化 metadata
            self.session_metadata = {
                "session_id": session_id,
                "user_id": self.user_id,
                "start_time": timestamp.isoformat(),
                "last_updated": timestamp.isoformat(),
                "status": "active",
                "total_turns": 0,
                "inherited_context": {},
                "previous_session_id": None,
                "topics": [],
                "last_topic": None,
                "skills_used": {},
                "artifacts_generated": [],
                "server_start_id": self._current_server_start_id
            }
            
            # 创建 MD 文件头
            await self._write_session_header_with_inheritance({})
            
            logger.info(f"📝 Created new session with forced ID: {session_id}")
    
    def _should_start_new_session(self, now: datetime, user_message: str) -> bool:
        """
        🆕 判断是否需要新 session（保守策略 - 优先压缩而非分卷）
        
        优先级：
        1. 没有 session → 创建
        2. 用户明确要求新 session（"新对话", "重新开始"）→ 创建
        3. 长时间不活动（1 小时）→ 创建
        
        注意：不再基于文件大小/turn 数强制分卷，改为压缩策略
        
        Returns:
            True if should start new session
        """
        # 1. 如果没有 session，直接创建
        if not self.current_session_id:
            logger.debug("📝 No existing session, creating new one")
            return True
        
        # 2. 用户明确要求新 session
        if self._user_requests_new_session(user_message):
            logger.info("🆕 User explicitly requested new session")
            return True
        
        # 3. 兜底：长时间不活动（1 小时）
        if self.last_activity_time:
            time_diff = (now - self.last_activity_time).total_seconds()
            if time_diff > self.INACTIVITY_TIMEOUT:
                logger.info(
                    f"⏰ Long inactivity: {time_diff:.1f}s > {self.INACTIVITY_TIMEOUT}s"
                )
                return True
        
        # 🆕 其他情况继续当前 session，通过压缩控制大小
        return False
    
    def _user_requests_new_session(self, user_message: str) -> bool:
        """检测用户是否明确要求新建 session"""
        new_session_keywords = [
            "新对话", "新会话", "重新开始", "清除记忆", "忘掉之前",
            "new session", "new conversation", "start fresh", "forget everything",
            "重置", "从头开始"
        ]
        message_lower = user_message.lower()
        return any(kw in message_lower for kw in new_session_keywords)
    
    def _get_file_size_chars(self) -> int:
        """计算 MD 文件大小（字符数）"""
        if not self.current_session_file or not self.current_session_file.exists():
            return 0
        try:
            content = self.current_session_file.read_text(encoding='utf-8')
            return len(content)
        except Exception as e:
            logger.error(f"❌ Failed to read MD file size: {e}")
            return 0
    
    def _estimate_tokens_from_chars(self, char_count: int) -> int:
        """
        估算 token 数量
        
        规则：1 char ≈ 0.4 tokens（中英文混合平均值）
        - 纯英文：1 char ≈ 0.25 tokens
        - 纯中文：1 char ≈ 0.6 tokens
        - 混合：1 char ≈ 0.4 tokens
        """
        return int(char_count * self.TOKEN_ESTIMATION_RATIO)
    
    def _is_natural_breakpoint(self, user_message: str) -> bool:
        """
        检测是否是自然断点（新主题或总结请求）
        
        触发条件：
        - 用户明确切换主题（"我想学习 XXX", "换个话题"）
        - 用户请求 summary（"总结一下", "回顾一下"）
        - 用户明确结束当前话题（"理解了", "懂了", "谢谢"）
        
        Returns:
            True if this is a natural breakpoint
        """
        breakpoint_keywords = [
            # 切换主题
            "换个话题", "学习新的", "开始新的", "切换到", "讲讲其他",
            "new topic", "switch to", "let's talk about",
            # 总结请求
            "总结一下", "回顾一下", "梳理一下", "归纳一下",
            "summarize", "recap", "review",
            # 结束当前话题
            "理解了", "懂了", "明白了", "清楚了", "谢谢",
            "got it", "understand", "thank you",
            # 明确的新学习请求
            "我想学", "教我", "给我讲讲", "介绍一下",
            "teach me", "explain", "tell me about"
        ]
        
        message_lower = user_message.lower()
        return any(kw in message_lower for kw in breakpoint_keywords)
    
    async def _start_new_session(self, timestamp: datetime, user_message: str):
        """
        🆕 创建新 session（带上下文继承）
        
        Args:
            timestamp: 创建时间
            user_message: 首条消息（用于检测关联）
        """
        # 🆕 从旧 session 创建继承上下文
        inherited_context = await self._create_inherited_context()
        
        # 生成新 session ID
        self.current_session_id = self._generate_session_id(timestamp)
        
        # 创建 MD 文件路径
        self.current_session_file = self.storage_path / f"{self.current_session_id}.md"
        
        # 重置 turn 计数器
        self.turn_counter = 0
        
        # 初始化 session 元数据（包含继承信息）
        previous_session_id = self.session_metadata.get("session_id") if self.session_metadata else None
        
        self.session_metadata = {
            "session_id": self.current_session_id,
            "user_id": self.user_id,
            "start_time": timestamp.isoformat(),
            "last_updated": timestamp.isoformat(),
            "status": "active",
            "total_turns": 0,
            "inherited_context": inherited_context,  # 🆕 继承的完整上下文
            "previous_session_id": previous_session_id,  # 🆕 父 session ID
            "topics": inherited_context.get("key_topics", []),  # 🆕 继承主题
            "last_topic": inherited_context.get("key_topics", [None])[-1] if inherited_context.get("key_topics") else None,
            "skills_used": {},
            "artifacts_generated": inherited_context.get("last_artifacts", []),  # 🆕 继承最后的 artifacts
            "server_start_id": self._current_server_start_id  # 🆕 服务启动 ID（用于检测重启）
        }
        
        # 🔗 检查是否与旧 sessions 相关（语义搜索）
        related_sessions = await self._find_related_sessions(user_message)
        if related_sessions:
            self.session_metadata["related_sessions"] = related_sessions
            logger.info(f"🔗 Found {len(related_sessions)} related sessions")
        
        # 创建 MD 文件头部（包含继承信息）
        await self._write_session_header_with_inheritance(inherited_context)
    
    def _generate_session_id(self, timestamp: datetime) -> str:
        """生成 session ID"""
        return f"session_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    
    async def _create_inherited_context(self) -> Dict[str, Any]:
        """
        🆕 创建继承上下文（给新 session 使用）
        
        策略：
        1. 生成当前 session 的 summary（压缩版）
        2. 提取关键主题
        3. 收集最后生成的 artifacts（引用）
        4. 生成延续提示（给 LLM 的上下文）
        
        Returns:
            {
                "previous_session_id": "session_xxx",
                "summary": "...",
                "key_topics": [...],
                "last_artifacts": [...],
                "continuation_prompt": "..."
            }
        """
        if not self.session_metadata or not self.current_session_id:
            return {}
        
        try:
            # 1. 生成 session summary（简化版，避免调用 LLM）
            summary = await self._generate_session_summary()
            
            # 2. 提取关键主题
            key_topics = self.session_metadata.get("topics", [])
            if not key_topics and self.session_metadata.get("last_topic"):
                key_topics = [self.session_metadata["last_topic"]]
            
            # 3. 收集最后的 artifacts
            last_artifacts = self.session_metadata.get("artifacts_generated", [])[-3:]  # 最后 3 个
            
            # 4. 生成延续提示
            continuation_prompt = self._generate_continuation_prompt(
                key_topics, 
                last_artifacts,
                self.turn_counter
            )
            
            inherited_context = {
                "previous_session_id": self.current_session_id,
                "summary": summary,
                "key_topics": key_topics,
                "last_artifacts": last_artifacts,
                "continuation_prompt": continuation_prompt,
                "total_turns": self.turn_counter
            }
            
            logger.info(
                f"📚 Created inherited context from {self.current_session_id}: "
                f"{len(key_topics)} topics, {len(last_artifacts)} artifacts, "
                f"{self.turn_counter} turns"
            )
            
            return inherited_context
        
        except Exception as e:
            logger.error(f"❌ Failed to create inherited context: {e}")
            return {}
    
    async def _generate_session_summary(self) -> str:
        """
        生成当前 session 的 summary（简化版）
        
        策略（不调用 LLM，使用规则提取）：
        1. 统计 turns 数量
        2. 提取主题列表
        3. 提取使用的 skills
        4. 提取 artifacts 类型
        
        TODO: 后续可以调用 LLM 生成更高质量的 summary
        """
        if not self.current_session_file or not self.current_session_file.exists():
            return ""
        
        try:
            # 简单规则提取
            topics = self.session_metadata.get("topics", [])
            skills_used = self.session_metadata.get("skills_used", {})
            artifacts_count = len(self.session_metadata.get("artifacts_generated", []))
            
            summary_parts = []
            
            # 基本信息
            summary_parts.append(
                f"在之前的学习中，用户进行了 {self.turn_counter} 轮对话。"
            )
            
            # 主题
            if topics:
                topics_str = "、".join(topics[:5])  # 最多列举 5 个
                summary_parts.append(f"学习的主题包括：{topics_str}。")
            
            # Skills
            if skills_used:
                skills_list = list(skills_used.keys())[:3]  # 最多列举 3 个
                skills_str = "、".join(skills_list)
                summary_parts.append(f"使用了以下技能：{skills_str}。")
            
            # Artifacts
            if artifacts_count > 0:
                summary_parts.append(f"生成了 {artifacts_count} 个学习产物（quiz、notes、mindmap 等）。")
            
            return " ".join(summary_parts)
        
        except Exception as e:
            logger.error(f"❌ Failed to generate session summary: {e}")
            return ""
    
    def _generate_continuation_prompt(
        self, 
        key_topics: List[str], 
        last_artifacts: List[Dict[str, Any]],
        total_turns: int
    ) -> str:
        """
        生成延续提示（给 LLM 的上下文）
        
        这个 prompt 会被添加到新 session 的 system message 中
        """
        prompt_parts = []
        
        # 基本信息
        prompt_parts.append(
            f"这是用户的延续学习 session（共 {total_turns} 轮对话）。"
        )
        
        # 主题上下文
        if key_topics:
            topics_str = "、".join(key_topics[:3])
            prompt_parts.append(f"用户正在学习：{topics_str}。")
        
        # Artifacts 上下文
        if last_artifacts:
            artifacts_types = [a.get("type", "artifact") for a in last_artifacts]
            artifacts_str = "、".join(artifacts_types)
            prompt_parts.append(f"已生成的学习产物：{artifacts_str}。")
        
        prompt_parts.append("请保持学习的连贯性，自然衔接之前的内容。")
        
        return " ".join(prompt_parts)
    
    async def _find_related_sessions(
        self,
        user_message: str,
        max_results: int = 3
    ) -> List[Dict[str, Any]]:
        """
        查找相关的旧 sessions（语义搜索）
        
        策略：
        1. 提取用户消息中的关键词/主题
        2. 在旧 sessions 中搜索相关主题
        3. 计算相关度评分
        
        Args:
            user_message: 用户消息
            max_results: 最多返回几个相关 session
        
        Returns:
            相关 sessions 列表
        """
        # 🔍 简单实现：基于主题匹配
        # 高级实现可以使用 embedding 语义搜索
        
        related = []
        
        try:
            # 列出所有 session MD 文件
            session_files = list(self.storage_path.glob("session_*.md"))
            
            # 提取用户消息中的关键词（简单分词）
            keywords = self._extract_keywords(user_message)
            
            for session_file in session_files:
                # 跳过当前 session
                if self.current_session_id and session_file.stem == self.current_session_id:
                    continue
                
                # 读取 session metadata（从文件头部或单独的 JSON）
                metadata = await self._load_session_metadata(session_file)
                
                if not metadata:
                    continue
                
                # 计算相关度
                relevance = self._calculate_relevance(keywords, metadata)
                
                if relevance > 0.5:  # 阈值：50%
                    related.append({
                        "session_id": session_file.stem,
                        "relevance_score": relevance,
                        "topics": metadata.get("topics", []),
                        "start_time": metadata.get("start_time", "")
                    })
            
            # 按相关度排序
            related.sort(key=lambda x: x["relevance_score"], reverse=True)
            
            return related[:max_results]
        
        except Exception as e:
            logger.error(f"❌ Failed to find related sessions: {e}")
            return []
    
    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（简单实现）"""
        # 移除常见停用词
        stopwords = {'的', '了', '吗', '呢', '啊', '吧', '给我', '帮我', '我要', '什么是', '是什么'}
        
        # 简单分词（基于空格和标点）
        import re
        words = re.findall(r'[\w]+', text)
        
        # 过滤停用词，保留长度 >= 2 的词
        keywords = [w for w in words if w not in stopwords and len(w) >= 2]
        
        return keywords[:10]  # 最多 10 个关键词
    
    async def _load_session_metadata(self, session_file: Path) -> Optional[Dict[str, Any]]:
        """
        加载 session 元数据
        
        策略：
        1. 优先从单独的 JSON 文件加载（session_xxx_metadata.json）
        2. 否则从 MD 文件末尾的 JSON 代码块解析
        """
        # 方案 1：单独的 metadata JSON 文件
        metadata_file = session_file.parent / f"{session_file.stem}_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ Failed to load metadata from {metadata_file}: {e}")
        
        # 方案 2：从 MD 文件解析（暂不实现，避免读取大文件）
        # TODO: 实现从 MD 末尾提取 JSON
        
        return None
    
    def _calculate_relevance(
        self,
        keywords: List[str],
        metadata: Dict[str, Any]
    ) -> float:
        """
        计算相关度
        
        策略：
        - keywords 与 metadata.topics 的重叠度
        
        Returns:
            相关度 (0.0 - 1.0)
        """
        if not keywords or not metadata.get("topics"):
            return 0.0
        
        topics = metadata.get("topics", [])
        
        # 计算关键词在 topics 中出现的比例
        matches = 0
        for keyword in keywords:
            for topic in topics:
                if keyword in topic or topic in keyword:
                    matches += 1
                    break
        
        relevance = matches / len(keywords) if keywords else 0.0
        
        return min(relevance, 1.0)
    
    async def _write_session_header(self):
        """写入 MD 文件头部（旧版，保持兼容性）"""
        header = self._format_session_header()
        
        # 🔧 确保目录存在（防止目录被外部删除后写入失败）
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        with open(self.current_session_file, 'w', encoding='utf-8') as f:
            f.write(header)
        
        logger.info(f"📝 Created session file: {self.current_session_file}")
    
    async def _write_session_header_with_inheritance(self, inherited_context: Dict[str, Any]):
        """
        🆕 写入 MD 文件头部（带继承信息）
        
        Args:
            inherited_context: 从旧 session 继承的上下文
        """
        header = self._format_session_header_with_inheritance(inherited_context)
        
        # 🔧 确保目录存在（防止目录被外部删除后写入失败）
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        with open(self.current_session_file, 'w', encoding='utf-8') as f:
            f.write(header)
        
        logger.info(f"📝 Created session file with inherited context: {self.current_session_file}")
    
    def _format_session_header(self) -> str:
        """格式化 session 头部（旧版）"""
        metadata = self.session_metadata
        timestamp = datetime.fromisoformat(metadata["start_time"])
        
        header = f"""# Learning Session - {timestamp.strftime('%Y-%m-%d %H:%M:%S')}

**User**: {self.user_id}  
**Session ID**: {metadata['session_id']}  
**Started**: {metadata['start_time']}  
**Last Updated**: {metadata['last_updated']}  
**Status**: {metadata['status']}

"""
        
        # 添加相关 sessions 引用
        if metadata.get("related_sessions"):
            header += "**Related Sessions**:\n"
            for related in metadata["related_sessions"]:
                header += f"- 📎 [{related['session_id']}]({related['session_id']}.md) - {', '.join(related['topics'])} (相关度: {related['relevance_score']:.0%})\n"
            header += "\n"
        
        header += "---\n\n"
        
        return header
    
    def _format_session_header_with_inheritance(self, inherited_context: Dict[str, Any]) -> str:
        """
        🆕 格式化 session 头部（带继承信息）
        
        添加：
        1. 父 session 链接
        2. 继承的 summary
        3. 关键主题
        4. 最后的 artifacts 引用
        """
        metadata = self.session_metadata
        timestamp = datetime.fromisoformat(metadata["start_time"])
        
        # 基本信息
        is_continuation = bool(inherited_context.get("previous_session_id"))
        title = f"Learning Session - {timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        if is_continuation:
            title += " (Continued)"
        
        header = f"""# {title}

**User**: {self.user_id}  
**Session ID**: {metadata['session_id']}  
**Started**: {metadata['start_time']}  
**Last Updated**: {metadata['last_updated']}  
**Status**: {metadata['status']}
"""
        
        # 🆕 继承信息
        if is_continuation:
            prev_session_id = inherited_context["previous_session_id"]
            header += f"**Previous Session**: 🔗 [{prev_session_id}](./{prev_session_id}.md)\n"
        
        header += "\n"
        
        # 🆕 继承的上下文摘要
        if inherited_context.get("summary"):
            header += "---\n\n## 📚 Inherited Context\n\n"
            header += f"> **Summary of Previous Session:**\n"
            header += f"> {inherited_context['summary']}\n\n"
            
            # 关键主题
            if inherited_context.get("key_topics"):
                topics_str = ", ".join(inherited_context["key_topics"])
                header += f"**Key Topics**: {topics_str}\n\n"
            
            # 最后的 artifacts
            if inherited_context.get("last_artifacts"):
                header += "**Last Artifacts**:\n"
                for artifact in inherited_context["last_artifacts"]:
                    artifact_type = artifact.get("type", "artifact")
                    artifact_ref = artifact.get("content_reference", "N/A")
                    header += f"- {artifact_type}: `{artifact_ref}`\n"
                header += "\n"
            
            header += "---\n\n"
        
        # 相关 sessions 引用
        if metadata.get("related_sessions"):
            header += "**Related Sessions**:\n"
            for related in metadata["related_sessions"]:
                session_id = related['session_id']
                topics = ', '.join(related.get('topics', []))
                relevance = related['relevance_score']
                header += f"- 📎 [{session_id}](./{session_id}.md) - {topics} (相关度: {relevance:.0%})\n"
            header += "\n---\n\n"
        
        return header
    
    async def append_turn(
        self,
        turn_data: Dict[str, Any]
    ) -> bool:
        """
        追加一个对话轮次到 MD 文件
        
        🔒 并发安全：使用 async lock 保护文件写入
        
        Args:
            turn_data: {
                "user_query": str,
                "agent_response": Dict[str, Any],
                "response_type": str,  # explanation, quiz_set, flashcard_set, etc.
                "timestamp": datetime,
                "intent": Dict[str, Any],
                "metadata": Dict[str, Any]  # thinking_tokens, output_tokens, duration, model
            }
        
        Returns:
            成功返回 True
        """
        # 🔒 获取写入锁，防止并发写入导致文件损坏
        async with self._write_lock:
            try:
                # 增加 turn 计数
                self.turn_counter += 1
                turn_data["turn_number"] = self.turn_counter
                
                # 格式化 Turn
                from .markdown_formatter import MarkdownFormatter
                formatter = MarkdownFormatter()
                
                turn_md = formatter.format_turn(turn_data)
                
                # 🔧 确保目录存在（防止目录被外部删除后写入失败）
                self.storage_path.mkdir(parents=True, exist_ok=True)
                
                # 追加到文件
                with open(self.current_session_file, 'a', encoding='utf-8') as f:
                    f.write(turn_md)
                    f.write("\n---\n\n")
                
                # 更新 session 元数据
                await self._update_session_metadata(turn_data)
                
                # 上传到 S3
                if self.s3_manager:
                    if self.s3_manager.is_available():
                        await self._upload_to_s3()
                    else:
                        logger.warning(f"⚠️  S3 not available (is_available=False), skipping upload")
                else:
                    logger.warning(f"⚠️  S3 manager not set, skipping upload")
                
                logger.info(f"✅ Appended Turn {self.turn_counter} to {self.current_session_file.name}")
                
                # 🆕 检查是否需要压缩旧对话
                if self._should_compress_old_turns():
                    await self._compress_old_turns()
                
                return True
            
            except Exception as e:
                logger.error(f"❌ Failed to append turn: {e}")
                return False
    
    def _should_compress_old_turns(self) -> bool:
        """
        🆕 检查是否需要压缩旧对话
        
        触发条件：
        1. Turn 数超过 COMPRESS_TRIGGER_TURNS（30）
        2. 且有足够多的旧对话可压缩（超过 KEEP_RECENT_TURNS）
        """
        if self.turn_counter < self.COMPRESS_TRIGGER_TURNS:
            return False
        
        # 检查是否已经压缩过（避免重复压缩）
        if self.session_metadata.get("compressed_history"):
            # 已有压缩历史，检查是否需要再次压缩
            last_compression_turn = self.session_metadata.get("last_compression_turn", 0)
            turns_since_compression = self.turn_counter - last_compression_turn
            # 每 20 轮压缩一次
            if turns_since_compression < 20:
                return False
        
        return True
    
    async def _compress_old_turns(self):
        """
        🆕 压缩旧对话为 summary，保留最近 N 轮完整对话
        
        策略（改进版 - 保留归档）：
        1. 读取 MD 文件内容
        2. 分离出：Header、压缩历史区、最近 N 轮完整对话
        3. 🆕 将旧对话完整保存到归档文件（session_xxx_archive_001.md）
        4. 在主文件中只保留摘要 + 归档文件引用
        5. 重写 MD 文件：Header + 压缩历史（含归档引用）+ 最近 N 轮
        """
        if not self.current_session_file or not self.current_session_file.exists():
            return
        
        try:
            logger.info(f"🗜️ Starting compression for {self.current_session_file.name}...")
            
            # 读取当前 MD 内容
            content = self.current_session_file.read_text(encoding='utf-8')
            
            # 分割成各个部分
            parts = self._parse_md_structure(content)
            
            header = parts.get("header", "")
            existing_compressed = parts.get("compressed_history", "")
            turns = parts.get("turns", [])
            
            total_turns = len(turns)
            
            if total_turns <= self.KEEP_RECENT_TURNS:
                logger.info(f"📝 Not enough turns to compress ({total_turns} <= {self.KEEP_RECENT_TURNS})")
                return
            
            # 分离：要压缩的旧对话 vs 保留的最近对话
            turns_to_compress = turns[:-self.KEEP_RECENT_TURNS]
            turns_to_keep = turns[-self.KEEP_RECENT_TURNS:]
            
            # 🆕 创建归档文件保留完整的旧对话
            archive_file = await self._archive_old_turns(turns_to_compress)
            archive_filename = archive_file.name if archive_file else None
            
            # 生成压缩 summary（包含归档引用）
            new_summary = self._generate_compression_summary_with_archive(
                turns_to_compress, 
                archive_filename
            )
            
            # 合并到现有压缩历史
            if existing_compressed:
                combined_compressed = f"{existing_compressed}\n\n{new_summary}"
            else:
                combined_compressed = new_summary
            
            # 重写 MD 文件
            await self._rewrite_md_with_compression(
                header=header,
                compressed_history=combined_compressed,
                recent_turns=turns_to_keep
            )
            
            # 更新元数据
            self.session_metadata["compressed_history"] = True
            self.session_metadata["last_compression_turn"] = self.turn_counter
            self.session_metadata["compression_count"] = self.session_metadata.get("compression_count", 0) + 1
            self.session_metadata["compressed_turns_total"] = self.session_metadata.get("compressed_turns_total", 0) + len(turns_to_compress)
            
            # 🆕 记录归档文件
            if archive_filename:
                if "archive_files" not in self.session_metadata:
                    self.session_metadata["archive_files"] = []
                self.session_metadata["archive_files"].append({
                    "filename": archive_filename,
                    "turns_range": self._extract_turns_range(turns_to_compress),
                    "created_at": datetime.now().isoformat()
                })
            
            await self._save_session_metadata()
            
            logger.info(
                f"✅ Compressed {len(turns_to_compress)} turns → archived to {archive_filename}, kept {len(turns_to_keep)} recent turns"
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to compress old turns: {e}", exc_info=True)
    
    async def _archive_old_turns(self, turns: List[str]) -> Optional[Path]:
        """
        🆕 将旧对话归档到独立文件
        
        Args:
            turns: 要归档的 Turn 内容列表
            
        Returns:
            归档文件 Path（如 session_xxx_archive_001.md）
        """
        if not turns:
            return None
        
        try:
            # 确定归档文件名
            compression_count = self.session_metadata.get("compression_count", 0) + 1
            archive_filename = f"{self.current_session_id}_archive_{compression_count:03d}.md"
            archive_path = self.storage_path / archive_filename
            
            # 提取 turn 范围
            turns_range = self._extract_turns_range(turns)
            
            # 构建归档文件内容
            archive_content_parts = []
            
            # 归档文件头部
            archive_header = f"""# 📦 对话归档 - {self.current_session_id}

**归档时间**: {datetime.now().isoformat()}  
**原 Session**: [{self.current_session_id}](./{self.current_session_id}.md)  
**轮次范围**: Turn {turns_range['start']} - {turns_range['end']}（共 {len(turns)} 轮）  
**归档编号**: #{compression_count}

---

> ⚠️ 此文件包含已压缩对话的完整原始记录。
> 主 Session 文件中保留了这些对话的摘要。
> 智能检索功能可自动从此归档中检索详细内容。

---

"""
            archive_content_parts.append(archive_header)
            
            # 添加所有归档的对话
            for turn in turns:
                archive_content_parts.append(turn)
                archive_content_parts.append("\n---\n\n")
            
            # 写入归档文件
            archive_content = "".join(archive_content_parts)
            archive_path.write_text(archive_content, encoding='utf-8')
            
            logger.info(f"📦 Archived {len(turns)} turns to {archive_filename}")
            
            return archive_path
            
        except Exception as e:
            logger.error(f"❌ Failed to create archive: {e}")
            return None
    
    def _extract_turns_range(self, turns: List[str]) -> Dict[str, int]:
        """提取 turn 范围"""
        start = end = 0
        
        for t in turns:
            match = re.search(r'## Turn (\d+)', t)
            if match:
                num = int(match.group(1))
                if start == 0 or num < start:
                    start = num
                if num > end:
                    end = num
        
        return {"start": start, "end": end}
    
    def _generate_compression_summary_with_archive(
        self, 
        turns: List[str], 
        archive_filename: Optional[str]
    ) -> str:
        """
        🆕 生成压缩摘要（包含归档文件引用）
        
        Args:
            turns: 要压缩的 Turn 内容列表
            archive_filename: 归档文件名
        
        Returns:
            压缩后的摘要文本（包含归档引用）
        """
        # 使用原有逻辑生成摘要内容
        base_summary = self._generate_compression_summary(turns)
        
        # 添加归档引用
        if archive_filename:
            archive_note = f"\n> 📦 **完整对话归档**: [{archive_filename}](./{archive_filename}) - 如需查看详细内容请参考此文件"
            return f"{base_summary}\n{archive_note}"
        
        return base_summary
    
    def _parse_md_structure(self, content: str) -> Dict[str, Any]:
        """
        解析 MD 文件结构
        
        Returns:
            {
                "header": str,           # Session Header
                "compressed_history": str,  # 压缩的历史摘要
                "turns": List[str]       # 各个 Turn 的完整内容
            }
        """
        result = {
            "header": "",
            "compressed_history": "",
            "turns": []
        }
        
        # 分割 Header 和 内容
        # Header 通常以 "## Turn" 开始前的部分
        header_pattern = r'^(# Learning Session.*?)(?=## Turn|\Z)'
        header_match = re.search(header_pattern, content, re.DOTALL)
        
        if header_match:
            result["header"] = header_match.group(1).strip()
        
        # 检查是否有压缩历史区（用特殊标记识别）
        compressed_pattern = r'## 📚 历史摘要\n(.*?)(?=## Turn|\Z)'
        compressed_match = re.search(compressed_pattern, content, re.DOTALL)
        
        if compressed_match:
            result["compressed_history"] = compressed_match.group(1).strip()
        
        # 提取所有 Turns
        turn_pattern = r'(## Turn \d+.*?)(?=## Turn \d+|---\s*$|\Z)'
        turns = re.findall(turn_pattern, content, re.DOTALL)
        
        # 清理每个 turn
        result["turns"] = [t.strip() for t in turns if t.strip()]
        
        return result
    
    def _generate_compression_summary(self, turns: List[str]) -> str:
        """
        生成压缩摘要（不调用 LLM，使用规则提取）
        
        Args:
            turns: 要压缩的 Turn 内容列表
        
        Returns:
            压缩后的摘要文本
        """
        if not turns:
            return ""
        
        # 提取关键信息
        topics_mentioned = set()
        skills_used = {}
        key_queries = []
        
        for turn_content in turns:
            # 提取用户问题
            query_match = re.search(r'### 👤 User Query\n(.+?)(?=\n###|\Z)', turn_content, re.DOTALL)
            if query_match:
                query = query_match.group(1).strip()[:100]  # 限制长度
                key_queries.append(query)
            
            # 提取 topic
            topic_match = re.search(r'\*\*Topic\*\*:\s*([^\n|]+)', turn_content)
            if topic_match:
                topics_mentioned.add(topic_match.group(1).strip())
            
            # 提取 response type
            type_match = re.search(r'\*\*Type\*\*:\s*(\w+)', turn_content)
            if type_match:
                skill = type_match.group(1)
                skills_used[skill] = skills_used.get(skill, 0) + 1
        
        # 构建摘要
        summary_parts = []
        
        # 时间范围
        turn_numbers = []
        for t in turns:
            num_match = re.search(r'## Turn (\d+)', t)
            if num_match:
                turn_numbers.append(int(num_match.group(1)))
        
        if turn_numbers:
            summary_parts.append(f"**轮次 {min(turn_numbers)}-{max(turn_numbers)}**（共 {len(turns)} 轮）")
        
        # 主题
        if topics_mentioned:
            topics_str = "、".join(list(topics_mentioned)[:5])
            summary_parts.append(f"- 📖 **学习主题**: {topics_str}")
        
        # 技能使用
        if skills_used:
            skills_str = ", ".join([f"{k}×{v}" for k, v in list(skills_used.items())[:4]])
            summary_parts.append(f"- 🛠️ **使用技能**: {skills_str}")
        
        # 关键问题（取前 3 个）
        if key_queries:
            summary_parts.append("- 💬 **关键问题**:")
            for q in key_queries[:3]:
                summary_parts.append(f"  - {q[:60]}{'...' if len(q) > 60 else ''}")
        
        return "\n".join(summary_parts)
    
    async def _rewrite_md_with_compression(
        self,
        header: str,
        compressed_history: str,
        recent_turns: List[str]
    ):
        """
        重写 MD 文件，包含压缩历史
        """
        new_content_parts = []
        
        # 1. Header
        new_content_parts.append(header)
        new_content_parts.append("")
        
        # 2. 压缩历史区
        if compressed_history:
            new_content_parts.append("## 📚 历史摘要")
            new_content_parts.append("")
            new_content_parts.append("> *以下是早期对话的压缩摘要。完整的原始对话已保存到归档文件中。*")
            new_content_parts.append("> *智能检索功能可自动从归档中检索详细内容。*")
            new_content_parts.append("")
            new_content_parts.append(compressed_history)
            new_content_parts.append("")
            new_content_parts.append("---")
            new_content_parts.append("")
        
        # 3. 最近的完整对话
        for turn in recent_turns:
            new_content_parts.append(turn)
            new_content_parts.append("")
            new_content_parts.append("---")
            new_content_parts.append("")
        
        # 写入文件
        new_content = "\n".join(new_content_parts)
        self.current_session_file.write_text(new_content, encoding='utf-8')
        
        logger.info(f"📝 Rewrote {self.current_session_file.name} with compressed history")
    
    async def _update_session_metadata(self, turn_data: Dict[str, Any]):
        """更新 session 元数据"""
        metadata = self.session_metadata
        
        # 更新 last_updated
        if isinstance(turn_data["timestamp"], datetime):
            metadata["last_updated"] = turn_data["timestamp"].isoformat()
        else:
            metadata["last_updated"] = turn_data["timestamp"]
        
        # 更新 total_turns
        metadata["total_turns"] = self.turn_counter
        
        # 更新 topics
        if "topic" in turn_data.get("intent", {}):
            topic = turn_data["intent"]["topic"]
            if topic:
                if topic not in metadata["topics"]:
                    metadata["topics"].append(topic)
                # 🆕 更新 last_topic（用于跨 session 继承）
                metadata["last_topic"] = topic
                logger.debug(f"📚 Updated last_topic: {topic}")
        
        # 更新 skills_used
        response_type = turn_data.get("response_type", "unknown")
        metadata["skills_used"][response_type] = metadata["skills_used"].get(response_type, 0) + 1
        
        # 记录 artifacts
        if "artifact_id" in turn_data.get("agent_response", {}):
            metadata["artifacts_generated"].append({
                "turn": self.turn_counter,
                "type": response_type,
                "artifact_id": turn_data["agent_response"]["artifact_id"],
                "topic": turn_data.get("intent", {}).get("topic", "")
            })
        
        # 保存元数据到单独的 JSON 文件
        await self._save_session_metadata()
    
    async def _save_session_metadata(self):
        """保存 session 元数据到单独的 JSON 文件"""
        metadata_file = self.storage_path / f"{self.current_session_id}_metadata.json"
        
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.session_metadata, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"💾 Saved session metadata: {metadata_file.name}")
        
        except Exception as e:
            logger.error(f"❌ Failed to save session metadata: {e}")
    
    async def _upload_to_s3(self):
        """上传 MD 文件和 metadata JSON 文件到 S3"""
        if not self.s3_manager:
            logger.warning("⚠️  S3 manager not initialized, skipping upload")
            return
        
        if not self.s3_manager.is_available():
            logger.warning("⚠️  S3 not available, skipping upload")
            return
        
        logger.info("🔄 Starting S3 upload...")
        
        try:
            # 上传 MD 文件
            if self.current_session_file and self.current_session_file.exists():
                s3_key_md = f"{self.user_id}/{self.current_session_file.name}"
                result = self.s3_manager.save(
                    s3_key_md,
                    self.current_session_file.read_text(encoding='utf-8'),
                    content_type="text/markdown"
                )
                if result:
                    logger.info(f"☁️  Uploaded MD to S3: s3://{self.s3_manager.bucket}/{s3_key_md}")
                else:
                    logger.warning(f"⚠️  Failed to upload MD to S3: {s3_key_md}")
            else:
                logger.warning(f"⚠️  MD file not found: {self.current_session_file}")
            
            # 上传 metadata JSON 文件
            if self.current_session_id:
                metadata_file = self.storage_path / f"{self.current_session_id}_metadata.json"
                if metadata_file.exists():
                    s3_key_metadata = f"{self.user_id}/{metadata_file.name}"
                    result = self.s3_manager.save(
                        s3_key_metadata,
                        metadata_file.read_text(encoding='utf-8'),
                        content_type="application/json"
                    )
                    if result:
                        logger.info(f"☁️  Uploaded metadata to S3: s3://{self.s3_manager.bucket}/{s3_key_metadata}")
                    else:
                        logger.warning(f"⚠️  Failed to upload metadata to S3: {s3_key_metadata}")
                else:
                    logger.warning(f"⚠️  Metadata file not found: {metadata_file}")
        
        except Exception as e:
            logger.error(f"❌ Failed to upload to S3: {e}")
    
    async def get_recent_turns(self, num_turns: int = 5) -> str:
        """
        🆕 获取最近 N 轮对话内容（用于构建 LLM context）
        
        Args:
            num_turns: 要获取的轮次数量
        
        Returns:
            最近 N 轮对话的 Markdown 文本
        """
        if not self.current_session_file or not self.current_session_file.exists():
            return ""
        
        try:
            content = self.current_session_file.read_text(encoding='utf-8')
            
            # 解析 turns（匹配 "## Turn X"）
            turn_pattern = re.compile(r'^## Turn \d+', re.MULTILINE)
            turn_positions = [m.start() for m in turn_pattern.finditer(content)]
            
            if not turn_positions:
                return ""
            
            # 获取最后 N 个 turn 的起始位置
            recent_turn_positions = turn_positions[-num_turns:]
            
            # 提取内容（从第一个 recent turn 到文件末尾）
            if recent_turn_positions:
                recent_content = content[recent_turn_positions[0]:]
                return recent_content
            
            return ""
        
        except Exception as e:
            logger.error(f"❌ Failed to get recent turns: {e}")
            return ""
    
    async def get_session_context_for_llm(
        self,
        include_recent_turns: int = 5,
        include_inherited: bool = True
    ) -> str:
        """
        🆕 为 LLM 构建完整的 session context（智能加载）
        
        包含：
        1. 继承的 summary（如果有）
        2. 最近 N 轮对话
        
        Args:
            include_recent_turns: 包含最近几轮对话
            include_inherited: 是否包含继承的上下文
        
        Returns:
            LLM context string
        """
        context_parts = []
        
        # 1. 继承的上下文
        if include_inherited and self.session_metadata.get("inherited_context"):
            inherited = self.session_metadata["inherited_context"]
            if inherited.get("continuation_prompt"):
                context_parts.append(f"### Context from Previous Session\n{inherited['continuation_prompt']}")
        
        # 2. 最近的对话
        recent_turns = await self.get_recent_turns(num_turns=include_recent_turns)
        if recent_turns:
            context_parts.append(f"### Recent Conversation\n{recent_turns}")
        
        return "\n\n---\n\n".join(context_parts) if context_parts else ""
    
    async def finalize_session(self):
        """
        结束 session，添加摘要
        """
        if not self.current_session_id or not self.current_session_file:
            return
        
        try:
            # 生成 session 摘要
            summary = await self._generate_session_summary()
            
            # 追加到文件末尾
            with open(self.current_session_file, 'a', encoding='utf-8') as f:
                f.write(f"\n\n---\n\n## 📊 Session Summary\n\n{summary}\n")
            
            # 更新状态
            self.session_metadata["status"] = "completed"
            await self._save_session_metadata()
            
            # 最后一次上传到 S3
            if self.s3_manager and self.s3_manager.is_available():
                await self._upload_to_s3()
            
            logger.info(f"✅ Finalized session: {self.current_session_id}")
        
        except Exception as e:
            logger.error(f"❌ Failed to finalize session: {e}")
    
    def _generate_session_summary(self) -> str:
        """生成 session 摘要"""
        metadata = self.session_metadata
        
        start_time = datetime.fromisoformat(metadata["start_time"])
        end_time = datetime.fromisoformat(metadata["last_updated"])
        duration = (end_time - start_time).total_seconds() / 60  # 分钟
        
        summary = f"""## 📊 Session Summary

**Duration**: {duration:.1f} minutes ({start_time.strftime('%H:%M:%S')} - {end_time.strftime('%H:%M:%S')})  
**Total Turns**: {metadata['total_turns']}  
**Topics Discussed**: {', '.join(metadata['topics']) if metadata['topics'] else 'N/A'}  
**Skills Used**: 
"""
        
        for skill, count in metadata.get("skills_used", {}).items():
            summary += f"- {skill} ({count} time{'s' if count > 1 else ''})\n"
        
        summary += f"""
**Learning Progress**:
- ✅ Generated {len(metadata.get('artifacts_generated', []))} artifacts

**Next Session Suggestions**:
- 可以继续学习相关主题
- 或者切换新主题

<details>
<summary>📦 <b>Session 元数据（JSON）</b> - 点击展开</summary>

```json
{json.dumps(metadata, ensure_ascii=False, indent=2)}
```

</details>

---

*Last saved: {end_time.strftime('%Y-%m-%d %H:%M:%S')}*  
*Storage: {self.current_session_file}*  
"""
        
        if self.s3_manager and self.s3_manager.is_available():
            summary += f"*S3: s3://{self.s3_manager.bucket}/{self.user_id}/{self.current_session_file.name}*  \n"
        
        return summary
    
    async def load_recent_context(
        self,
        max_sessions: int = 1,
        max_turns_per_session: int = 10
    ) -> str:
        """
        加载最近的对话上下文（用于 LLM）
        
        Args:
            max_sessions: 加载最近几个 session
            max_turns_per_session: 每个 session 最多加载几个 turn
        
        Returns:
            完整的 Markdown 文本
        """
        try:
            # 列出所有 session MD 文件
            session_files = sorted(
                self.storage_path.glob("session_*.md"),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )
            
            # 取最近的 N 个
            recent_sessions = session_files[:max_sessions]
            
            context = ""
            for session_file in recent_sessions:
                content = session_file.read_text(encoding='utf-8')
                
                # TODO: 如果需要，可以截断每个 session 只取最后 N 个 turns
                # 当前直接返回完整内容
                
                context += content + "\n\n---\n\n"
            
            logger.info(f"📚 Loaded context from {len(recent_sessions)} sessions")
            
            return context
        
        except Exception as e:
            logger.error(f"❌ Failed to load recent context: {e}")
            return ""

