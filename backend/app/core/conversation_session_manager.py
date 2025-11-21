"""
Conversation Session Manager - 对话 Session 管理器

核心功能：
1. 检测 5 分钟 cooldown，自动创建/继续 session
2. 生成 Markdown 格式的对话记录
3. 嵌入 JSON 结构化数据
4. Session 互联（跨 session 引用）
5. S3 同步
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ConversationSessionManager:
    """
    管理连续对话 session
    
    核心逻辑：
    - 不是实时计时 5 分钟（浪费资源）
    - 下次对话开始时检查距离上次的时间差
    - 如果 > 5 分钟 → 新 MD
    - 如果 ≤ 5 分钟 → 追加到当前 MD
    - MD 之间可以互联（跨 session 引用）
    """
    
    SESSION_TIMEOUT = 300  # 5 分钟（秒）
    
    def __init__(
        self,
        user_id: str,
        storage_path: str,
        s3_manager: Optional[Any] = None
    ):
        """
        初始化 Session 管理器
        
        Args:
            user_id: 用户 ID
            storage_path: 本地存储路径（如：backend/artifacts/user_kimi/）
            s3_manager: S3 存储管理器（可选）
        """
        self.user_id = user_id
        self.storage_path = Path(storage_path)
        self.s3_manager = s3_manager
        
        # 确保存储目录存在
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # 当前 session 状态
        self.current_session_id: Optional[str] = None
        self.last_activity_time: Optional[datetime] = None
        self.current_session_file: Optional[Path] = None
        self.turn_counter: int = 0
        
        # Session 元数据
        self.session_metadata: Dict[str, Any] = {}
        
        logger.info(f"✅ ConversationSessionManager initialized for user: {user_id}")
    
    async def start_or_continue_session(
        self,
        user_message: str,
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        开始或继续 session（核心方法）
        
        逻辑：
        1. 检查距离上次对话的时间差
        2. 如果 > 5 分钟 → 创建新 session
        3. 如果 ≤ 5 分钟 → 继续当前 session
        
        Args:
            user_message: 用户消息（用于检测关联）
            timestamp: 当前时间戳（可选，默认为 now）
        
        Returns:
            session_id
        """
        now = timestamp or datetime.now()
        
        # 检查是否需要新 session
        if self._should_start_new_session(now):
            # 创建新 session
            await self._start_new_session(now, user_message)
            logger.info(f"🆕 Started new session: {self.current_session_id}")
        else:
            # 继续当前 session
            logger.info(f"♻️  Continuing session: {self.current_session_id}")
        
        # 更新最后活动时间
        self.last_activity_time = now
        
        return self.current_session_id
    
    def _should_start_new_session(self, now: datetime) -> bool:
        """
        判断是否需要新 session
        
        条件：
        1. 当前没有 session
        2. 距离上次活动 > 5 分钟
        """
        if not self.current_session_id:
            return True
        
        if not self.last_activity_time:
            return True
        
        time_diff = (now - self.last_activity_time).total_seconds()
        
        if time_diff > self.SESSION_TIMEOUT:
            logger.info(f"⏰ Session timeout: {time_diff:.1f}s > {self.SESSION_TIMEOUT}s")
            return True
        
        return False
    
    async def _start_new_session(self, timestamp: datetime, user_message: str):
        """
        创建新 session
        
        Args:
            timestamp: 创建时间
            user_message: 首条消息（用于检测关联）
        """
        # 生成 session ID
        self.current_session_id = self._generate_session_id(timestamp)
        
        # 创建 MD 文件路径
        self.current_session_file = self.storage_path / f"{self.current_session_id}.md"
        
        # 重置 turn 计数器
        self.turn_counter = 0
        
        # 初始化 session 元数据
        self.session_metadata = {
            "session_id": self.current_session_id,
            "user_id": self.user_id,
            "start_time": timestamp.isoformat(),
            "last_updated": timestamp.isoformat(),
            "status": "active",
            "total_turns": 0,
            "topics": [],
            "skills_used": {},
            "artifacts_generated": []
        }
        
        # 🔗 检查是否与旧 session 相关
        related_sessions = await self._find_related_sessions(user_message)
        if related_sessions:
            self.session_metadata["related_sessions"] = related_sessions
            logger.info(f"🔗 Found {len(related_sessions)} related sessions")
        
        # 创建 MD 文件头部
        await self._write_session_header()
    
    def _generate_session_id(self, timestamp: datetime) -> str:
        """生成 session ID"""
        return f"session_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    
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
        """写入 MD 文件头部"""
        header = self._format_session_header()
        
        with open(self.current_session_file, 'w', encoding='utf-8') as f:
            f.write(header)
        
        logger.info(f"📝 Created session file: {self.current_session_file}")
    
    def _format_session_header(self) -> str:
        """格式化 session 头部"""
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
    
    async def append_turn(
        self,
        turn_data: Dict[str, Any]
    ) -> bool:
        """
        追加一个对话轮次到 MD 文件
        
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
        try:
            # 增加 turn 计数
            self.turn_counter += 1
            turn_data["turn_number"] = self.turn_counter
            
            # 格式化 Turn
            from .markdown_formatter import MarkdownFormatter
            formatter = MarkdownFormatter()
            
            turn_md = formatter.format_turn(turn_data)
            
            # 追加到文件
            with open(self.current_session_file, 'a', encoding='utf-8') as f:
                f.write(turn_md)
                f.write("\n---\n\n")
            
            # 更新 session 元数据
            await self._update_session_metadata(turn_data)
            
            # 上传到 S3
            if self.s3_manager and self.s3_manager.s3_client:
                await self._upload_to_s3()
            
            logger.info(f"✅ Appended Turn {self.turn_counter} to {self.current_session_file.name}")
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Failed to append turn: {e}")
            return False
    
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
            if topic and topic not in metadata["topics"]:
                metadata["topics"].append(topic)
        
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
        """上传 MD 文件到 S3"""
        if not self.s3_manager or not self.s3_manager.s3_client:
            return
        
        try:
            # S3 路径：user_kimi/session_xxx.md
            s3_key = f"{self.user_id}/{self.current_session_file.name}"
            
            await self.s3_manager.save(
                s3_key,
                self.current_session_file.read_text(encoding='utf-8')
            )
            
            logger.debug(f"☁️  Uploaded to S3: {s3_key}")
        
        except Exception as e:
            logger.error(f"❌ Failed to upload to S3: {e}")
    
    async def finalize_session(self):
        """
        结束 session，添加摘要
        """
        if not self.current_session_id or not self.current_session_file:
            return
        
        try:
            # 生成 session 摘要
            summary = self._generate_session_summary()
            
            # 追加到文件末尾
            with open(self.current_session_file, 'a', encoding='utf-8') as f:
                f.write(summary)
            
            # 更新状态
            self.session_metadata["status"] = "completed"
            await self._save_session_metadata()
            
            # 最后一次上传到 S3
            if self.s3_manager and self.s3_manager.s3_client:
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
        
        if self.s3_manager and self.s3_manager.s3_client:
            summary += f"*S3: s3://skill-agent-demo/{self.user_id}/{self.current_session_file.name}*  \n"
        
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

