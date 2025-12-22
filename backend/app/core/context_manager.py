"""
Context Manager - 上下文管理器 (Manus 风格)

基于 Manus 的上下文管理理念实现：
1. 压缩 (Compaction) - 可逆的，将信息转移到外部存储
2. 摘要 (Summarization) - 不可逆的，只在压缩不足时使用
3. 检索 (Retrieval) - 从归档文件按需加载

核心原则：
- 可逆性优先：压缩不丢失信息，只转移到外部
- 保留最新：始终保留最近 N 轮的完整细节
- 按需检索：支持从归档文件中恢复详细内容
"""

import logging
import json
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TurnData:
    """对话轮次数据"""
    turn_number: int
    user_query: str
    agent_response: Dict[str, Any]
    intent: str
    topic: Optional[str] = None
    artifact_id: Optional[str] = None
    artifact_type: Optional[str] = None
    timestamp: Optional[str] = None
    
    # 🆕 完整内容 vs 紧凑引用
    full_content: Optional[Dict[str, Any]] = None  # 完整内容（可能很大）
    compact_reference: Optional[str] = None  # 紧凑引用（文件路径或 artifact_id）
    is_compacted: bool = False  # 是否已压缩为紧凑格式


@dataclass
class ContextState:
    """上下文状态"""
    total_chars: int = 0
    total_tokens_estimated: int = 0  # 估算的 token 数
    turn_count: int = 0
    compacted_turns: int = 0  # 已压缩为紧凑格式的轮数
    summarized_turns: int = 0  # 已摘要的轮数
    archive_files: List[str] = field(default_factory=list)


class ContextManager:
    """
    Manus 风格的上下文管理器
    
    实现三层上下文管理：
    1. 完整格式 (Full Format) - 保留所有细节
    2. 紧凑格式 (Compact Format) - 只保留引用，可逆
    3. 摘要格式 (Summary Format) - 压缩为摘要，不可逆
    """
    
    # ============= 阈值配置 =============
    # Token 估算：1 char ≈ 0.4 tokens（中英文混合）
    TOKEN_ESTIMATION_RATIO = 0.4
    
    # 🆕 "腐烂前"阈值 - 基于 Manus 的经验值
    # 大多数模型在 200k tokens 左右开始性能下降
    SOFT_LIMIT_TOKENS = 50_000   # 50K tokens: 开始紧凑压缩
    HARD_LIMIT_TOKENS = 128_000  # 128K tokens: 触发摘要
    
    # 保留的完整轮数
    KEEP_FULL_TURNS = 6  # 保留最近 6 轮完整细节
    KEEP_COMPACT_TURNS = 20  # 保留最近 20 轮紧凑格式
    
    # 紧凑压缩百分比
    COMPACT_OLDEST_PERCENT = 0.5  # 压缩最旧的 50%
    
    def __init__(
        self,
        user_id: str,
        session_id: str,
        storage_path: Path
    ):
        """
        初始化上下文管理器
        
        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            storage_path: 存储路径
        """
        self.user_id = user_id
        self.session_id = session_id
        self.storage_path = storage_path
        
        # 确保存储目录存在
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # 上下文状态
        self.state = ContextState()
        
        # 对话历史（内存中）
        self.turns: List[TurnData] = []
        
        # 归档文件引用
        self.archives: Dict[str, Path] = {}  # archive_id -> file_path
        
        logger.info(f"✅ ContextManager initialized for {user_id}/{session_id}")
    
    # ============= 核心方法 =============
    
    def add_turn(self, turn_data: Dict[str, Any]) -> TurnData:
        """
        添加一轮对话
        
        Args:
            turn_data: 对话数据
            
        Returns:
            TurnData 对象
        """
        turn = TurnData(
            turn_number=len(self.turns) + 1,
            user_query=turn_data.get("user_query", ""),
            agent_response=turn_data.get("agent_response", {}),
            intent=turn_data.get("intent", {}).get("intent", "other"),
            topic=turn_data.get("intent", {}).get("topic"),
            artifact_id=turn_data.get("agent_response", {}).get("artifact_id"),
            artifact_type=turn_data.get("response_type"),
            timestamp=datetime.now().isoformat(),
            full_content=turn_data.get("agent_response", {}).get("content"),
            is_compacted=False
        )
        
        self.turns.append(turn)
        self._update_state()
        
        # 检查是否需要压缩
        self._check_and_compress()
        
        logger.info(f"📝 Added turn {turn.turn_number}: {turn.intent}, topic={turn.topic}")
        return turn
    
    def get_context_for_llm(
        self,
        max_tokens: int = 50000,
        include_artifacts: bool = True
    ) -> Tuple[str, Dict[str, Any]]:
        """
        获取用于 LLM 的上下文
        
        返回格式化的上下文字符串，并附带元数据
        
        Args:
            max_tokens: 最大 token 数
            include_artifacts: 是否包含 artifact 内容
            
        Returns:
            (context_string, metadata)
        """
        context_parts = []
        metadata = {
            "total_turns": len(self.turns),
            "loaded_turns": 0,
            "compacted_turns": 0,
            "retrieved_from_archive": 0,
            "estimated_tokens": 0
        }
        
        # 🆕 分层加载上下文
        # 1. 最近的完整轮次（最重要）
        # 2. 较早的紧凑轮次
        # 3. 摘要（如果有）
        
        current_tokens = 0
        
        # Step 1: 加载最近的完整轮次
        recent_turns = self.turns[-self.KEEP_FULL_TURNS:] if len(self.turns) > self.KEEP_FULL_TURNS else self.turns
        
        for turn in reversed(recent_turns):  # 从最新到最旧
            turn_text = self._format_turn_for_context(turn, full=True)
            turn_tokens = self._estimate_tokens(turn_text)
            
            if current_tokens + turn_tokens > max_tokens:
                break
                
            context_parts.insert(0, turn_text)  # 插入到开头保持顺序
            current_tokens += turn_tokens
            metadata["loaded_turns"] += 1
        
        # Step 2: 如果还有空间，加载紧凑格式的较早轮次
        if current_tokens < max_tokens * 0.8:  # 留 20% 余量
            older_turns = self.turns[:-self.KEEP_FULL_TURNS] if len(self.turns) > self.KEEP_FULL_TURNS else []
            
            for turn in reversed(older_turns[-self.KEEP_COMPACT_TURNS:]):
                turn_text = self._format_turn_for_context(turn, full=False)
                turn_tokens = self._estimate_tokens(turn_text)
                
                if current_tokens + turn_tokens > max_tokens * 0.9:
                    break
                    
                context_parts.insert(0, turn_text)
                current_tokens += turn_tokens
                metadata["compacted_turns"] += 1
        
        # Step 3: 添加摘要头部（如果有归档）
        if self.archives:
            summary_header = self._generate_archive_summary()
            context_parts.insert(0, summary_header)
            current_tokens += self._estimate_tokens(summary_header)
        
        metadata["estimated_tokens"] = current_tokens
        
        context_string = "\n\n---\n\n".join(context_parts)
        
        logger.info(
            f"📊 Context loaded: {metadata['loaded_turns']} full + "
            f"{metadata['compacted_turns']} compact turns, "
            f"~{current_tokens} tokens"
        )
        
        return context_string, metadata
    
    # ============= 压缩方法 =============
    
    def _check_and_compress(self):
        """检查是否需要压缩，并执行相应操作"""
        current_tokens = self.state.total_tokens_estimated
        
        # 🆕 分层压缩策略（参考 Manus）
        if current_tokens >= self.HARD_LIMIT_TOKENS:
            # 触发摘要（不可逆）
            logger.warning(f"⚠️ Context exceeds hard limit ({current_tokens} >= {self.HARD_LIMIT_TOKENS}), triggering summarization")
            self._summarize_old_turns()
        elif current_tokens >= self.SOFT_LIMIT_TOKENS:
            # 触发紧凑压缩（可逆）
            logger.info(f"📦 Context exceeds soft limit ({current_tokens} >= {self.SOFT_LIMIT_TOKENS}), triggering compaction")
            self._compact_old_turns()
    
    def _compact_old_turns(self):
        """
        🆕 紧凑压缩：将旧轮次转换为紧凑格式（可逆）
        
        策略：压缩最旧的 50%，保留最新的 50% 完整细节
        """
        if len(self.turns) <= self.KEEP_FULL_TURNS:
            return
        
        # 确定要压缩的轮次数
        compactable_turns = len(self.turns) - self.KEEP_FULL_TURNS
        turns_to_compact = int(compactable_turns * self.COMPACT_OLDEST_PERCENT)
        
        if turns_to_compact == 0:
            return
        
        compacted_count = 0
        for i in range(turns_to_compact):
            turn = self.turns[i]
            if not turn.is_compacted:
                self._compact_turn(turn)
                compacted_count += 1
        
        self._update_state()
        logger.info(f"📦 Compacted {compacted_count} turns (reversible)")
    
    def _compact_turn(self, turn: TurnData):
        """
        将单个轮次转换为紧凑格式
        
        紧凑格式只保留：
        - 用户问题摘要（前50字）
        - artifact 引用（ID + 类型）
        - intent 和 topic
        
        完整内容被卸载到外部文件
        """
        if turn.is_compacted:
            return
        
        # 卸载完整内容到文件
        if turn.full_content:
            offload_path = self._offload_turn_content(turn)
            turn.compact_reference = str(offload_path)
        
        # 清空内存中的完整内容
        turn.full_content = None
        turn.is_compacted = True
        
        logger.debug(f"📦 Compacted turn {turn.turn_number} → {turn.compact_reference}")
    
    def _offload_turn_content(self, turn: TurnData) -> Path:
        """
        将轮次内容卸载到文件
        
        Returns:
            卸载文件的路径
        """
        offload_dir = self.storage_path / "offloaded"
        offload_dir.mkdir(exist_ok=True)
        
        filename = f"{self.session_id}_turn_{turn.turn_number:03d}.json"
        filepath = offload_dir / filename
        
        offload_data = {
            "turn_number": turn.turn_number,
            "user_query": turn.user_query,
            "agent_response": turn.agent_response,
            "full_content": turn.full_content,
            "intent": turn.intent,
            "topic": turn.topic,
            "timestamp": turn.timestamp,
            "offloaded_at": datetime.now().isoformat()
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(offload_data, f, ensure_ascii=False, indent=2)
        
        return filepath
    
    def _summarize_old_turns(self):
        """
        🆕 摘要压缩：将紧凑格式的旧轮次转换为摘要（不可逆）
        
        策略：
        1. 先将要摘要的轮次完整归档到文件
        2. 生成摘要
        3. 删除内存中的轮次（但保留归档引用）
        """
        if len(self.turns) <= self.KEEP_COMPACT_TURNS:
            return
        
        # 确定要摘要的轮次
        turns_to_summarize = self.turns[:-self.KEEP_COMPACT_TURNS]
        
        if not turns_to_summarize:
            return
        
        # 🆕 关键：先归档完整内容（确保可恢复）
        archive_path = self._archive_turns(turns_to_summarize)
        
        # 生成摘要
        summary = self._generate_turns_summary(turns_to_summarize)
        
        # 记录归档
        archive_id = f"archive_{len(self.archives) + 1:03d}"
        self.archives[archive_id] = archive_path
        
        # 从内存中移除（但摘要保留）
        self.turns = self.turns[-self.KEEP_COMPACT_TURNS:]
        
        # 更新状态
        self.state.summarized_turns += len(turns_to_summarize)
        self._update_state()
        
        logger.info(
            f"📝 Summarized {len(turns_to_summarize)} turns → archived to {archive_path}"
        )
    
    def _archive_turns(self, turns: List[TurnData]) -> Path:
        """
        将轮次归档到文件（用于摘要前保存完整数据）
        
        Returns:
            归档文件路径
        """
        archive_dir = self.storage_path / "archives"
        archive_dir.mkdir(exist_ok=True)
        
        archive_num = len(self.archives) + 1
        filename = f"{self.session_id}_archive_{archive_num:03d}.json"
        filepath = archive_dir / filename
        
        # 恢复紧凑格式的完整内容
        archive_data = {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "archived_at": datetime.now().isoformat(),
            "turns_range": {
                "start": turns[0].turn_number if turns else 0,
                "end": turns[-1].turn_number if turns else 0
            },
            "turns": []
        }
        
        for turn in turns:
            turn_data = {
                "turn_number": turn.turn_number,
                "user_query": turn.user_query,
                "intent": turn.intent,
                "topic": turn.topic,
                "artifact_id": turn.artifact_id,
                "artifact_type": turn.artifact_type,
                "timestamp": turn.timestamp
            }
            
            # 🆕 如果是紧凑格式，从卸载文件中恢复完整内容
            if turn.is_compacted and turn.compact_reference:
                full_content = self._recover_turn_content(turn.compact_reference)
                if full_content:
                    turn_data["full_content"] = full_content
            else:
                turn_data["full_content"] = turn.full_content
            
            archive_data["turns"].append(turn_data)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"📦 Archived {len(turns)} turns to {filepath}")
        return filepath
    
    def _recover_turn_content(self, reference_path: str) -> Optional[Dict[str, Any]]:
        """
        从卸载文件中恢复轮次内容（实现可逆性）
        
        Args:
            reference_path: 卸载文件路径
            
        Returns:
            完整内容，如果无法恢复则返回 None
        """
        try:
            filepath = Path(reference_path)
            if not filepath.exists():
                logger.warning(f"⚠️ Offload file not found: {reference_path}")
                return None
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return data.get("full_content")
        except Exception as e:
            logger.error(f"❌ Failed to recover content from {reference_path}: {e}")
            return None
    
    # ============= 检索方法 =============
    
    def retrieve_from_archive(
        self,
        query: str,
        archive_id: Optional[str] = None,
        max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        🆕 从归档中检索相关内容
        
        支持：
        - 关键词搜索
        - 轮次范围检索
        - 主题检索
        
        Args:
            query: 搜索查询
            archive_id: 指定归档文件（可选）
            max_results: 最大返回数量
            
        Returns:
            匹配的轮次列表
        """
        results = []
        
        # 确定要搜索的归档文件
        archives_to_search = []
        if archive_id and archive_id in self.archives:
            archives_to_search = [self.archives[archive_id]]
        else:
            archives_to_search = list(self.archives.values())
        
        for archive_path in archives_to_search:
            try:
                with open(archive_path, 'r', encoding='utf-8') as f:
                    archive_data = json.load(f)
                
                for turn_data in archive_data.get("turns", []):
                    # 简单的关键词匹配
                    if self._match_query(turn_data, query):
                        results.append({
                            "source": str(archive_path),
                            "turn_number": turn_data.get("turn_number"),
                            "user_query": turn_data.get("user_query"),
                            "topic": turn_data.get("topic"),
                            "intent": turn_data.get("intent"),
                            "full_content": turn_data.get("full_content")
                        })
                        
                        if len(results) >= max_results:
                            break
                            
            except Exception as e:
                logger.error(f"❌ Failed to search archive {archive_path}: {e}")
        
        logger.info(f"🔍 Retrieved {len(results)} results from archives for query: {query[:50]}...")
        return results
    
    def _match_query(self, turn_data: Dict[str, Any], query: str) -> bool:
        """简单的关键词匹配"""
        query_lower = query.lower()
        
        # 搜索用户问题
        if query_lower in turn_data.get("user_query", "").lower():
            return True
        
        # 搜索主题
        if turn_data.get("topic") and query_lower in turn_data["topic"].lower():
            return True
        
        # 搜索内容
        content = turn_data.get("full_content")
        if content:
            content_str = json.dumps(content, ensure_ascii=False)
            if query_lower in content_str.lower():
                return True
        
        return False
    
    # ============= 辅助方法 =============
    
    def _update_state(self):
        """更新上下文状态"""
        total_chars = 0
        compacted = 0
        
        for turn in self.turns:
            if turn.is_compacted:
                # 紧凑格式的估算大小（只有引用）
                total_chars += len(turn.user_query[:50]) + 100  # 摘要 + 元数据
                compacted += 1
            else:
                # 完整格式的大小
                total_chars += len(turn.user_query)
                if turn.full_content:
                    total_chars += len(json.dumps(turn.full_content, ensure_ascii=False))
        
        self.state.total_chars = total_chars
        self.state.total_tokens_estimated = int(total_chars * self.TOKEN_ESTIMATION_RATIO)
        self.state.turn_count = len(self.turns)
        self.state.compacted_turns = compacted
    
    def _estimate_tokens(self, text: str) -> int:
        """估算文本的 token 数"""
        return int(len(text) * self.TOKEN_ESTIMATION_RATIO)
    
    def _format_turn_for_context(self, turn: TurnData, full: bool = True) -> str:
        """
        格式化轮次用于 LLM 上下文
        
        Args:
            turn: 轮次数据
            full: 是否使用完整格式
        """
        if full and not turn.is_compacted:
            # 完整格式
            content_preview = ""
            if turn.full_content:
                content_str = json.dumps(turn.full_content, ensure_ascii=False)
                content_preview = content_str[:500] + "..." if len(content_str) > 500 else content_str
            
            return f"""**Turn {turn.turn_number}** ({turn.intent}, topic: {turn.topic or 'N/A'})
用户: {turn.user_query}
助手: {content_preview}"""
        else:
            # 紧凑格式
            return f"""**Turn {turn.turn_number}** [紧凑] ({turn.intent}, topic: {turn.topic or 'N/A'})
用户: {turn.user_query[:100]}{'...' if len(turn.user_query) > 100 else ''}
助手: [{turn.artifact_type or 'text'}] 内容已归档 → {turn.compact_reference or 'N/A'}"""
    
    def _generate_archive_summary(self) -> str:
        """生成归档摘要头部"""
        if not self.archives:
            return ""
        
        summary = "## 📚 历史对话摘要\n\n"
        summary += f"> 本会话共有 {self.state.summarized_turns} 轮旧对话已归档。\n"
        summary += "> 如需查看详细内容，可使用检索功能从归档中恢复。\n\n"
        
        for archive_id, archive_path in self.archives.items():
            try:
                with open(archive_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                turns_range = data.get("turns_range", {})
                summary += f"- 📦 {archive_id}: Turn {turns_range.get('start', '?')}-{turns_range.get('end', '?')}\n"
            except:
                summary += f"- 📦 {archive_id}: (无法读取)\n"
        
        return summary
    
    def _generate_turns_summary(self, turns: List[TurnData]) -> str:
        """生成轮次摘要"""
        if not turns:
            return ""
        
        topics = set()
        intents = {}
        
        for turn in turns:
            if turn.topic:
                topics.add(turn.topic)
            intents[turn.intent] = intents.get(turn.intent, 0) + 1
        
        summary = f"**轮次 {turns[0].turn_number}-{turns[-1].turn_number}**（共 {len(turns)} 轮）\n"
        
        if topics:
            summary += f"- 📖 **学习主题**: {', '.join(list(topics)[:5])}\n"
        
        if intents:
            intents_str = ", ".join([f"{k}×{v}" for k, v in list(intents.items())[:4]])
            summary += f"- 🛠️ **意图分布**: {intents_str}\n"
        
        return summary
    
    def get_stats(self) -> Dict[str, Any]:
        """获取上下文统计信息"""
        return {
            "session_id": self.session_id,
            "total_turns": self.state.turn_count,
            "compacted_turns": self.state.compacted_turns,
            "summarized_turns": self.state.summarized_turns,
            "total_chars": self.state.total_chars,
            "estimated_tokens": self.state.total_tokens_estimated,
            "archive_count": len(self.archives),
            "soft_limit": self.SOFT_LIMIT_TOKENS,
            "hard_limit": self.HARD_LIMIT_TOKENS
        }

