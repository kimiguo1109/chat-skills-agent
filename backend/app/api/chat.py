"""
纯 Chat API - 第一期简化版
专注于: Chat + 上下文管理（卸载/压缩/关联/存储）

功能:
1. 多模态输入: 文本、图片、文档、语音(转文本)
2. 纯文本输出: 不走 skill 框架，直接 LLM 回复
3. 上下文管理: 复用现有 MD session 存储逻辑
4. Token 统计: 详细记录每个环节的消耗

后期扩展: 可通过 skill_hint 参数切换到 skill 框架
"""
import logging
import os
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.gemini import GeminiClient
from app.core.memory_manager import MemoryManager
from app.core.conversation_session_manager import ConversationSessionManager
from app.services.token_stats_service import TokenStatsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["Pure Chat"])


# ============= 请求/响应模型 =============

class ChatRequest(BaseModel):
    """Chat 请求"""
    message: str  # 用户消息（文本）
    user_id: str  # 用户 ID
    session_id: Optional[str] = None  # 会话 ID（不提供则创建新会话）
    file_uris: Optional[List[str]] = None  # 文件 URI 列表（图片、文档等）
    voice_text: Optional[str] = None  # 语音转文本内容（由前端完成 ASR）


class TokenUsageDetail(BaseModel):
    """Token 使用详情"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    source: str = ""  # gemini, compression, etc.
    model: str = ""


class ContextStats(BaseModel):
    """上下文管理统计"""
    session_turns: int = 0  # 当前会话轮数
    total_context_chars: int = 0  # 总上下文字符数
    compressed_turns: int = 0  # 已压缩的轮数
    compression_ratio: float = 0.0  # 压缩比
    artifacts_count: int = 0  # artifact 数量


class ChatResponse(BaseModel):
    """Chat 响应"""
    code: int = 0
    msg: str = "success"
    data: Dict[str, Any] = {}


# ============= 核心服务 =============

class PureChatService:
    """
    纯 Chat 服务
    
    职责:
    1. 处理多模态输入
    2. 管理对话上下文
    3. 调用 LLM 生成回复
    4. 统计 Token 消耗
    """
    
    def __init__(self):
        self.gemini = GeminiClient()
        self.memory_manager = MemoryManager()
        self.token_stats = TokenStatsService()
    
    async def chat(
        self,
        message: str,
        user_id: str,
        session_id: Optional[str] = None,
        file_uris: Optional[List[str]] = None,
        voice_text: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        处理 Chat 请求
        
        Args:
            message: 用户文本消息
            user_id: 用户 ID
            session_id: 会话 ID
            file_uris: 文件 URI 列表
            voice_text: 语音转文本
        
        Returns:
            包含回复和统计信息的字典
        """
        start_time = time.time()
        
        # Token 统计
        token_usage = {
            "context_loading": {"input": 0, "output": 0, "total": 0},
            "llm_generation": {"input": 0, "output": 0, "total": 0},
            "context_compression": {"input": 0, "output": 0, "total": 0},
            "total": {"input": 0, "output": 0, "total": 0}
        }
        
        # 1. 合并输入（文本 + 语音）
        full_message = message
        if voice_text:
            full_message = f"{message}\n[语音输入]: {voice_text}" if message else voice_text
        
        logger.info(f"📥 Chat request: user={user_id}, session={session_id}, files={len(file_uris) if file_uris else 0}")
        
        # 2. 加载/创建会话上下文
        session_mgr = await self._get_or_create_session(user_id, session_id, full_message)
        session_id = session_mgr.current_session_id
        
        # 3. 加载历史上下文（支持智能检索早期内容）
        context_result = await self._load_context(
            session_mgr, session_id, token_usage, 
            user_message=full_message  # 🆕 传入用户消息用于智能检索
        )
        history_context = context_result["context"]
        context_stats = context_result["stats"]
        
        # 4. 构建 prompt
        prompt = self._build_prompt(full_message, history_context, file_uris)
        
        # 5. 调用 LLM 生成回复
        llm_result = await self._generate_response(prompt, file_uris, token_usage)
        response_text = llm_result["text"]
        
        # 6. 保存到会话（复用现有 MD session 逻辑）
        await self._save_turn(
            session_mgr=session_mgr,
            user_message=full_message,
            assistant_response=response_text,
            file_uris=file_uris,
            token_usage=token_usage
        )
        
        # 7. 检查是否需要压缩（异步）
        compression_triggered = await self._check_and_compress(session_mgr, token_usage)
        
        # 8. 计算总 token
        token_usage["total"]["input"] = (
            token_usage["context_loading"]["input"] +
            token_usage["llm_generation"]["input"] +
            token_usage["context_compression"]["input"]
        )
        token_usage["total"]["output"] = (
            token_usage["context_loading"]["output"] +
            token_usage["llm_generation"]["output"] +
            token_usage["context_compression"]["output"]
        )
        token_usage["total"]["total"] = token_usage["total"]["input"] + token_usage["total"]["output"]
        
        elapsed = time.time() - start_time
        
        # 9. 记录统计（复用现有 TokenStatsService）
        await self._record_stats(
            user_id=user_id,
            session_id=session_id,
            message=full_message,
            token_usage=token_usage,
            file_uris=file_uris
        )
        
        logger.info(f"✅ Chat completed in {elapsed:.2f}s | Tokens: {token_usage['total']['total']}")
        
        return {
            "response": response_text,
            "session_id": session_id,
            "token_usage": token_usage,
            "context_stats": {
                "session_turns": context_stats["turns"] + 1,
                "loaded_turns": context_stats["loaded_turns"],
                "retrieved_turns": context_stats.get("retrieved_turns", 0),  # 🆕 智能检索到的早期轮数
                "total_context_chars": context_stats["chars"],
                "compressed_turns": context_stats["compressed"],
                "compression_triggered": compression_triggered
            },
            "generation_time": round(elapsed, 2)
        }
    
    async def _get_or_create_session(
        self,
        user_id: str,
        session_id: Optional[str],
        user_message: str = ""
    ) -> ConversationSessionManager:
        """获取或创建会话管理器"""
        session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
        
        # 开始或继续会话
        await session_mgr.start_or_continue_session(
            user_message=user_message or "chat",
            session_id=session_id
        )
        
        return session_mgr
    
    def _detect_history_reference(self, message: str) -> Dict[str, Any]:
        """
        智能检测用户是否在引用早期内容
        
        Returns:
            {
                "has_reference": bool,
                "reference_type": "time" | "index" | "keyword" | None,
                "keywords": List[str],  # 检测到的关键词
                "index": int | None     # 索引引用时的具体索引
            }
        """
        import re
        
        result = {
            "has_reference": False,
            "reference_type": None,
            "keywords": [],
            "index": None
        }
        
        # 1. 时间引用检测
        time_patterns = [
            r'最开始|一开始|开头|最初|之前|早些时候|刚开始',
            r'回到.*(开始|最初|之前)',
            r'前面.*(说|讲|提到)',
        ]
        for pattern in time_patterns:
            if re.search(pattern, message):
                result["has_reference"] = True
                result["reference_type"] = "time"
                logger.info(f"🔍 检测到时间引用: {message[:30]}...")
                break
        
        # 2. 索引引用检测
        index_patterns = [
            (r'第([一二三四五六七八九十\d]+)[道个张轮]', 'cn'),
            (r'第(\d+)', 'num'),
        ]
        for pattern, ptype in index_patterns:
            match = re.search(pattern, message)
            if match:
                result["has_reference"] = True
                result["reference_type"] = "index"
                # 转换中文数字
                cn_map = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
                idx_str = match.group(1)
                if ptype == 'cn' and idx_str in cn_map:
                    result["index"] = cn_map[idx_str]
                elif idx_str.isdigit():
                    result["index"] = int(idx_str)
                logger.info(f"🔍 检测到索引引用: 第{result['index']}个")
                break
        
        # 3. 关键词引用检测 (学科/主题)
        keyword_patterns = [
            r'(牛顿|物理|定律|惯性|作用力|F=ma)',
            r'(化学|化学键|共价键|离子键)',
            r'(历史|二战|凡尔赛|条约)',
            r'(数学|几何|函数|方程)',
            r'(生物|细胞|光合作用)',
        ]
        for pattern in keyword_patterns:
            matches = re.findall(pattern, message)
            if matches:
                result["keywords"].extend(matches)
        
        if result["keywords"] and not result["has_reference"]:
            # 只有关键词但没有明确引用，标记为可能的关键词引用
            result["has_reference"] = True
            result["reference_type"] = "keyword"
            logger.info(f"🔍 检测到关键词引用: {result['keywords']}")
        
        return result
    
    def _retrieve_from_history(
        self, 
        md_content: str, 
        reference: Dict[str, Any],
        all_turns: List[Dict],
        recent_turn_count: int = 5,
        session_mgr: Optional[Any] = None
    ) -> List[Dict]:
        """
        从历史中检索相关对话（支持归档文件）
        
        Args:
            md_content: MD 文件内容
            reference: _detect_history_reference 的返回值
            all_turns: 所有解析出的对话轮次
            recent_turn_count: 最近已加载的轮次数
            session_mgr: ConversationSessionManager 实例（用于访问归档文件）
            
        Returns:
            需要额外加载的历史对话列表
        """
        import re
        
        retrieved = []
        
        if not reference["has_reference"] or not all_turns:
            return retrieved
        
        # 早期对话 (不在最近5轮中的)
        early_turns = all_turns[:-recent_turn_count] if len(all_turns) > recent_turn_count else []
        
        ref_type = reference["reference_type"]
        
        # 1. 时间引用 - 返回最早的几轮
        if ref_type == "time":
            if early_turns:
                retrieved = early_turns[:3]  # 返回最早3轮
            else:
                # 🆕 如果当前文件没有早期对话，尝试从归档文件获取
                archived_turns = self._load_from_archive(session_mgr, target_range="earliest")
                if archived_turns:
                    retrieved = archived_turns[:3]
                    logger.info(f"🔎📦 从归档文件检索: 返回最早 {len(retrieved)} 轮")
                    return retrieved
            logger.info(f"🔎 时间引用检索: 返回最早 {len(retrieved)} 轮")
        
        # 2. 索引引用 - 返回特定轮次
        elif ref_type == "index" and reference["index"]:
            idx = reference["index"] - 1  # 转为0-based
            if 0 <= idx < len(all_turns):
                retrieved = [all_turns[idx]]
            else:
                # 🆕 索引超出当前范围，尝试从归档文件获取
                archived_turns = self._load_from_archive(
                    session_mgr, 
                    target_turn=reference["index"]
                )
                if archived_turns:
                    retrieved = archived_turns
                    logger.info(f"🔎📦 从归档文件检索: 返回第 {reference['index']} 轮")
                    return retrieved
            logger.info(f"🔎 索引引用检索: 返回第 {reference['index']} 轮")
        
        # 3. 关键词引用 - 搜索包含关键词的对话
        elif ref_type == "keyword" and reference["keywords"]:
            keywords = reference["keywords"]
            
            # 先搜索当前文件的早期对话
            for turn in early_turns:
                user_query = turn.get("user_query", "")
                assistant_text = turn.get("assistant_text", "")
                combined = user_query + assistant_text
                
                for kw in keywords:
                    if kw in combined:
                        if turn not in retrieved:
                            retrieved.append(turn)
                        break
            
            # 🆕 如果当前文件找到的不够，尝试从归档文件搜索
            if len(retrieved) < 3:
                archived_turns = self._load_from_archive(
                    session_mgr,
                    keywords=keywords,
                    max_results=3 - len(retrieved)
                )
                if archived_turns:
                    retrieved.extend(archived_turns)
                    logger.info(f"🔎📦 从归档文件额外检索: 找到 {len(archived_turns)} 轮")
            
            # 最多返回3轮
            retrieved = retrieved[:3]
            logger.info(f"🔎 关键词引用检索: 共找到 {len(retrieved)} 轮相关对话")
        
        return retrieved
    
    def _load_from_archive(
        self,
        session_mgr: Optional[Any],
        target_range: str = None,  # "earliest", "latest"
        target_turn: int = None,   # 特定轮次号
        keywords: List[str] = None,  # 关键词搜索
        max_results: int = 3
    ) -> List[Dict]:
        """
        🆕 从归档文件加载对话详情
        
        Args:
            session_mgr: ConversationSessionManager 实例
            target_range: "earliest" 或 "latest"
            target_turn: 特定轮次号
            keywords: 关键词列表（用于搜索）
            max_results: 最大返回数量
            
        Returns:
            从归档文件解析出的对话列表
        """
        import re
        import json as json_lib
        
        if not session_mgr:
            return []
        
        # 获取归档文件列表
        metadata = getattr(session_mgr, 'session_metadata', {})
        archive_files = metadata.get("archive_files", [])
        
        if not archive_files:
            # 尝试自动发现归档文件
            storage_path = getattr(session_mgr, 'storage_path', None)
            session_id = getattr(session_mgr, 'current_session_id', None)
            
            if storage_path and session_id:
                from pathlib import Path
                archive_pattern = f"{session_id}_archive_*.md"
                discovered = list(Path(storage_path).glob(archive_pattern))
                archive_files = [{"filename": f.name} for f in discovered]
        
        if not archive_files:
            logger.debug("📦 No archive files found")
            return []
        
        retrieved = []
        
        for archive_info in archive_files:
            if len(retrieved) >= max_results:
                break
            
            archive_filename = archive_info.get("filename") if isinstance(archive_info, dict) else archive_info
            storage_path = getattr(session_mgr, 'storage_path', None)
            
            if not storage_path:
                continue
            
            from pathlib import Path
            archive_path = Path(storage_path) / archive_filename
            
            if not archive_path.exists():
                logger.warning(f"📦 Archive file not found: {archive_path}")
                continue
            
            try:
                content = archive_path.read_text(encoding='utf-8')
                
                # 解析归档文件中的对话
                json_pattern = r'<details>.*?```json\s*(\{[^`]*?"turn_number"[^`]*?\})\s*```'
                json_matches = re.findall(json_pattern, content, re.DOTALL)
                
                archived_turns = []
                for json_str in json_matches:
                    try:
                        data = json_lib.loads(json_str)
                        user_query = data.get("user_query", "")
                        agent_content = data.get("agent_response", {}).get("content", {})
                        assistant_text = agent_content.get("text", "")
                        turn_number = data.get("turn_number", 0)
                        
                        archived_turns.append({
                            "turn_number": turn_number,
                            "user_query": user_query,
                            "assistant_text": assistant_text,
                            "source": f"archive:{archive_filename}"
                        })
                    except json_lib.JSONDecodeError:
                        continue
                
                # 根据检索条件筛选
                if target_range == "earliest":
                    # 返回最早的对话
                    archived_turns.sort(key=lambda x: x.get("turn_number", 0))
                    retrieved.extend(archived_turns[:max_results - len(retrieved)])
                
                elif target_turn:
                    # 返回特定轮次
                    for turn in archived_turns:
                        if turn.get("turn_number") == target_turn:
                            retrieved.append(turn)
                            break
                
                elif keywords:
                    # 关键词搜索
                    for turn in archived_turns:
                        if len(retrieved) >= max_results:
                            break
                        combined = turn.get("user_query", "") + turn.get("assistant_text", "")
                        for kw in keywords:
                            if kw in combined:
                                retrieved.append(turn)
                                break
                
                else:
                    # 默认返回该归档的所有内容
                    retrieved.extend(archived_turns[:max_results - len(retrieved)])
                
                logger.info(f"📦 Loaded {len(retrieved)} turns from archive: {archive_filename}")
                
            except Exception as e:
                logger.error(f"❌ Failed to load archive {archive_filename}: {e}")
                continue
        
        return retrieved

    async def _load_context(
        self,
        session_mgr: ConversationSessionManager,
        session_id: str,
        token_usage: Dict,
        user_message: str = ""
    ) -> Dict[str, Any]:
        """
        加载历史上下文 - 支持智能检索早期内容
        
        实现:
        1. 滑动窗口: 加载最近 5 轮
        2. 智能检索: 检测用户引用早期内容时，从 MD 检索相关对话
        """
        context_lines = []
        turns = 0
        total_chars = 0
        compressed_count = 0
        retrieved_count = 0
        all_parsed_turns = []
        
        try:
            import re
            import json as json_lib
            
            session_file = getattr(session_mgr, 'current_session_file', None)
            md_path = str(session_file) if session_file else None
            
            if md_path and os.path.exists(md_path):
                with open(md_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 解析所有对话轮次
                json_pattern = r'<details>.*?```json\s*(\{[^`]*?"turn_number"[^`]*?\})\s*```'
                json_matches = re.findall(json_pattern, content, re.DOTALL)
                
                for json_str in json_matches:
                    try:
                        data = json_lib.loads(json_str)
                        user_query = data.get("user_query", "")
                        agent_content = data.get("agent_response", {}).get("content", {})
                        assistant_text = agent_content.get("text", "")
                        turn_number = data.get("turn_number", 0)
                        
                        all_parsed_turns.append({
                            "turn_number": turn_number,
                            "user_query": user_query,
                            "assistant_text": assistant_text
                        })
                    except json_lib.JSONDecodeError:
                        continue
                
                # ========== 智能检索 ==========
                reference = self._detect_history_reference(user_message)
                retrieved_turns = []
                
                if reference["has_reference"]:
                    # 🆕 即使当前文件对话少于5轮，也尝试从归档文件检索
                    retrieved_turns = self._retrieve_from_history(
                        content, reference, all_parsed_turns, 
                        recent_turn_count=5,
                        session_mgr=session_mgr  # 🆕 传入 session_mgr 以支持归档检索
                    )
                    
                    # 添加检索到的早期对话
                    if retrieved_turns:
                        context_lines.append("[📚 检索到的早期对话]")
                        for turn in retrieved_turns:
                            context_lines.append(f"T{turn['turn_number']} 用户: {turn['user_query']}")
                            context_lines.append(f"T{turn['turn_number']} 助手: {turn['assistant_text'][:100]}...")
                            context_lines.append("")
                            total_chars += len(turn['user_query']) + 100
                            retrieved_count += 1
                        context_lines.append("[当前对话上下文]")
                        logger.info(f"🔎 智能检索: 额外加载 {retrieved_count} 轮早期对话")
                
                # ========== 滑动窗口: 最近 5 轮 ==========
                recent_turns = all_parsed_turns[-5:] if len(all_parsed_turns) > 5 else all_parsed_turns
                
                for turn in recent_turns:
                    user_query = turn["user_query"]
                    assistant_text = turn["assistant_text"][:150]
                    
                    if user_query:
                        context_lines.append(f"用户: {user_query}")
                        context_lines.append(f"助手: {assistant_text}...")
                        context_lines.append("")
                        
                        total_chars += len(user_query) + len(assistant_text)
                        turns += 1
                
                if turns > 0:
                    logger.info(f"📚 Loaded {turns} recent + {retrieved_count} retrieved turns")
                else:
                    logger.warning(f"⚠️ No conversation history found in MD")
                
        except Exception as e:
            logger.warning(f"⚠️ Failed to load MD history: {e}")
        
        # 从 session_metadata 获取补充信息
        metadata = getattr(session_mgr, 'session_metadata', {})
        
        total_turns = getattr(session_mgr, 'turn_counter', 0)
        if total_turns == 0:
            total_turns = metadata.get("total_turns", turns)
        
        # 获取压缩摘要（如果有）
        summary = metadata.get("compressed_summary", "")
        if summary:
            context_lines.insert(0, f"[对话摘要] {summary}\n")
            compressed_count = 1
            total_chars += len(summary)
        
        context = "\n".join(context_lines)
        
        return {
            "context": context,
            "stats": {
                "turns": total_turns,
                "loaded_turns": turns,
                "retrieved_turns": retrieved_count,  # 🆕 检索到的早期轮数
                "chars": total_chars,
                "compressed": compressed_count
            }
        }
    
    def _build_prompt(
        self,
        message: str,
        history_context: str,
        file_uris: Optional[List[str]]
    ) -> str:
        """构建 LLM prompt"""
        
        # 系统提示
        system_prompt = """你是一个智能学习助手，专注于帮助用户学习和理解知识。

你的特点:
- 回答清晰、准确、有条理
- 善于用简单的语言解释复杂概念
- 能够识别和分析图片、文档内容
- 记住对话历史，保持上下文连贯

请直接回答用户的问题，语言自然友好。"""

        # 历史上下文
        context_section = ""
        if history_context:
            context_section = f"""
### 对话历史
{history_context}
"""

        # 文件说明
        file_section = ""
        if file_uris:
            file_names = [uri.split('/')[-1] for uri in file_uris]
            file_section = f"\n### 用户附件\n{', '.join(file_names)}\n"

        # 完整 prompt
        prompt = f"""{system_prompt}
{context_section}
{file_section}
### 用户消息
{message}

请回复:"""

        return prompt
    
    async def _generate_response(
        self,
        prompt: str,
        file_uris: Optional[List[str]],
        token_usage: Dict
    ) -> Dict[str, Any]:
        """调用 LLM 生成回复"""
        
        try:
            result = await self.gemini.generate(
                prompt=prompt,
                model="gemini-2.5-flash",
                response_format="text",
                max_tokens=2000,
                temperature=0.7,
                file_uris=file_uris
            )
            
            # 提取 token 使用
            usage = result.get("usage", {})
            token_usage["llm_generation"]["input"] = usage.get("input_tokens", 0)
            token_usage["llm_generation"]["output"] = usage.get("output_tokens", 0)
            token_usage["llm_generation"]["total"] = usage.get("total_tokens", 0)
            
            return {
                "text": result.get("content", ""),
                "usage": usage
            }
            
        except Exception as e:
            logger.error(f"❌ LLM generation failed: {e}")
            return {
                "text": "抱歉，我遇到了一些问题，请稍后再试。",
                "usage": {}
            }
    
    async def _save_turn(
        self,
        session_mgr: ConversationSessionManager,
        user_message: str,
        assistant_response: str,
        file_uris: Optional[List[str]],
        token_usage: Dict
    ):
        """保存对话轮次 - 复用现有 MD session 存储逻辑"""
        
        # 构建 turn_data（兼容现有格式）
        turn_data = {
            "user_query": user_message,
            "agent_response": {
                "skill": "chat",
                "artifact_id": "",
                "content": {"text": assistant_response},
                "topic": ""
            },
            "response_type": "text",
            "timestamp": datetime.now(),
            "intent": {
                "intent": "chat",
                "topic": "",
                "confidence": 1.0,
                "parameters": {"file_uris": file_uris} if file_uris else {},
                "raw_text": user_message
            },
            "metadata": {
                "input_tokens": token_usage.get("llm_generation", {}).get("input", 0),
                "output_tokens": token_usage.get("llm_generation", {}).get("output", 0),
                "model": "gemini-2.5-flash",
                "has_files": bool(file_uris),
                "file_count": len(file_uris) if file_uris else 0
            }
        }
        
        # 使用现有的 append_turn 方法保存到 MD
        await session_mgr.append_turn(turn_data)
    
    async def _check_and_compress(
        self,
        session_mgr: ConversationSessionManager,
        token_usage: Dict
    ) -> bool:
        """
        检查是否需要上下文压缩
        
        复用现有 ConversationSessionManager 的压缩逻辑
        压缩由 session_mgr 在 append_turn 时自动触发
        这里只检查是否发生了压缩，并记录 token
        """
        # 从 MemoryTokenTracker 获取压缩 token（如果有）
        try:
            from app.services.memory_token_tracker import MemoryTokenTracker
            tracker = MemoryTokenTracker()
            compression_usage = tracker.get_and_clear_usage()
            
            if compression_usage:
                token_usage["context_compression"]["input"] = compression_usage.get("prompt_tokens", 0)
                token_usage["context_compression"]["output"] = compression_usage.get("completion_tokens", 0)
                token_usage["context_compression"]["total"] = (
                    compression_usage.get("prompt_tokens", 0) + 
                    compression_usage.get("completion_tokens", 0)
                )
                logger.info(f"🗜️ Compression tokens recorded: {token_usage['context_compression']['total']}")
                return True
        except Exception as e:
            logger.debug(f"No compression this turn: {e}")
        
        return False
    
    async def _record_stats(
        self,
        user_id: str,
        session_id: str,
        message: str,
        token_usage: Dict,
        file_uris: Optional[List[str]]
    ):
        """记录 Token 统计 - 复用现有 TokenStatsService"""
        
        self.token_stats.record_usage(
            user_id=user_id,
            session_id=session_id,
            message=message[:50],
            intent="chat",
            content_type="text",
            token_usage={
                "intent_router": {"method": "none", "tokens": 0},
                "skill_execution": {
                    "source": "gemini",
                    "model": "gemini-2.5-flash",
                    "prompt_tokens": token_usage["llm_generation"]["input"],
                    "completion_tokens": token_usage["llm_generation"]["output"],
                    "total_tokens": token_usage["llm_generation"]["total"]
                },
                "memory_operations": {
                    "compression_input": token_usage["context_compression"]["input"],
                    "compression_output": token_usage["context_compression"]["output"],
                    "compression_tokens": token_usage["context_compression"]["total"]
                },
                "total_internal_tokens": token_usage["total"]["total"]
            },
            file_uris=file_uris
        )


# ============= API 端点 =============

# 全局服务实例
_chat_service: Optional[PureChatService] = None

def get_chat_service() -> PureChatService:
    global _chat_service
    if _chat_service is None:
        _chat_service = PureChatService()
    return _chat_service


@router.post("/send", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    """
    发送 Chat 消息
    
    支持:
    - 纯文本消息
    - 语音转文本（voice_text）
    - 多图片附件（file_uris）
    - 多文档附件（file_uris）
    
    返回:
    - 纯文本回复
    - Token 使用统计
    - 上下文管理状态
    """
    try:
        service = get_chat_service()
        
        result = await service.chat(
            message=request.message,
            user_id=request.user_id,
            session_id=request.session_id,
            file_uris=request.file_uris,
            voice_text=request.voice_text
        )
        
        return ChatResponse(
            code=0,
            msg="success",
            data={
                "text": result["response"],
                "session_id": result["session_id"],
                "token_usage": result["token_usage"],
                "context_stats": result["context_stats"],
                "generation_time": result["generation_time"]
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Chat API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{user_id}/{session_id}")
async def get_session_info(user_id: str, session_id: str):
    """获取会话信息"""
    try:
        service = get_chat_service()
        session_mgr = service.memory_manager.get_conversation_session_manager(user_id)
        
        # 加载指定会话
        await session_mgr.start_or_continue_session(
            user_message="get_info",
            session_id=session_id
        )
        
        history = getattr(session_mgr, 'session_history', [])
        
        return {
            "code": 0,
            "data": {
                "session_id": session_id,
                "user_id": user_id,
                "turns": len(history),
                "compressed_turns": sum(1 for t in history if t.get("compressed")),
                "total_chars": sum(
                    len(t.get("user", "")) + len(t.get("assistant", ""))
                    for t in history
                )
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/today")
async def get_today_stats():
    """获取今日 Token 统计"""
    service = get_chat_service()
    return {
        "code": 0,
        "data": service.token_stats.get_today_summary()
    }

