"""
StudyX Agent Service - 外部 StudyX Flashcard Agent API 服务

基于新的 createFlashcardAgent API 实现完整流程:
1. 从前端接收 noteDto（包含 contentList URL）
2. 下载 note 内容（或使用本地测试文件）
3. 调用 createFlashcardAgent API 创建 Note → 获取 noteId
4. 将 note 内容注入到上下文管理框架，开始对话
5. 基于 note 内容进行 chat/flashcard/quiz 生成

这与现有的 external_flashcard_service / external_quiz_service 不同，
是专为新的 Agent API 接口设计的服务，并集成上下文管理框架。
"""

import logging
import aiohttp
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)


# ============================================================
# 数据传输对象 (DTOs)
# ============================================================

@dataclass
class NoteDto:
    """Note 数据传输对象 - 所有字段来自前端"""
    # 创建新 Note 时使用
    libraryCourseId: Optional[str] = None
    noteTitle: Optional[str] = None
    noteType: Optional[int] = None
    disableAutoInsertToLibrary: Optional[int] = None
    contentList: Optional[List[Dict[str, Any]]] = None
    
    # 引用已有 Note 时使用
    noteId: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为 API 请求格式"""
        result = {}
        if self.noteId:
            result["noteId"] = self.noteId
        else:
            if self.libraryCourseId:
                result["libraryCourseId"] = self.libraryCourseId
            if self.noteTitle:
                result["noteTitle"] = self.noteTitle
            if self.noteType is not None:
                result["noteType"] = self.noteType
            if self.disableAutoInsertToLibrary is not None:
                result["disableAutoInsertToLibrary"] = self.disableAutoInsertToLibrary
            if self.contentList:
                result["contentList"] = self.contentList
        return result


@dataclass
class CardSetNoteDto:
    """Flashcard 配置数据传输对象"""
    outLanguage: Optional[str] = None
    libraryCourseId: Optional[str] = None
    isPublic: Optional[int] = None
    tags: Optional[str] = None
    cardCount: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {}
        if self.outLanguage:
            result["outLanguage"] = self.outLanguage
        if self.libraryCourseId:
            result["libraryCourseId"] = self.libraryCourseId
        if self.isPublic is not None:
            result["isPublic"] = self.isPublic
        if self.tags:
            result["tags"] = self.tags
        if self.cardCount is not None:
            result["cardCount"] = self.cardCount
        return result


@dataclass
class QuizSetNoteDto:
    """Quiz 配置数据传输对象"""
    quizCount: Optional[int] = None
    libraryCourseId: Optional[str] = None
    isPublic: Optional[int] = None
    tags: Optional[str] = None
    outLanguage: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {}
        if self.quizCount is not None:
            result["quizCount"] = self.quizCount
        if self.libraryCourseId:
            result["libraryCourseId"] = self.libraryCourseId
        if self.isPublic is not None:
            result["isPublic"] = self.isPublic
        if self.tags:
            result["tags"] = self.tags
        if self.outLanguage:
            result["outLanguage"] = self.outLanguage
        return result


@dataclass
class ChatMessage:
    """对话消息"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class NoteSession:
    """Note 会话上下文 - 保存 note 内容和 noteId"""
    note_id: str
    note_title: str
    note_content: str  # 下载的 note 内容
    library_course_id: str
    content_urls: List[str]  # 原始 contentList URLs
    session_id: str  # 关联的 chat session ID
    created_at: datetime = field(default_factory=datetime.now)
    
    # 生成的内容
    flashcards: Optional[Dict[str, Any]] = None
    quiz: Optional[Dict[str, Any]] = None
    
    # 🆕 Chat 对话历史
    chat_history: List[ChatMessage] = field(default_factory=list)
    
    def add_chat_message(self, role: str, content: str):
        """添加对话消息"""
        self.chat_history.append(ChatMessage(role=role, content=content))
        # 保持最近 20 轮对话
        if len(self.chat_history) > 40:  # 20 轮 = 40 条消息
            self.chat_history = self.chat_history[-40:]
    
    def get_chat_context(self, max_turns: int = 5) -> str:
        """获取最近的对话历史作为上下文"""
        recent = self.chat_history[-(max_turns * 2):]  # 每轮2条消息
        lines = []
        for msg in recent:
            prefix = "用户" if msg.role == "user" else "助手"
            lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)


# ============================================================
# StudyX Agent Service
# ============================================================

class StudyXAgentService:
    """
    StudyX Agent 服务
    
    封装 createFlashcardAgent API 的完整流程，并集成上下文管理
    """
    
    # 默认测试数据
    DEFAULT_LIBRARY_COURSE_ID = "01k5zyf4qwp4ktbxj5a9x6s0tq"
    DEFAULT_CONTENT_URL = "https://files.istudyx.com/d0b60b61/b79abb5d5a0d461f9dc334e4fac2ec87.txt"
    DEFAULT_CONTENT_SIZE = 154055
    
    # 本地测试文件路径
    LOCAL_TEST_NOTE_DIR = Path(__file__).parent.parent.parent / "test_notes"
    
    def __init__(
        self,
        api_url: Optional[str] = None,
        api_token: Optional[str] = None
    ):
        """
        初始化 StudyX Agent 服务
        
        Args:
            api_url: API 端点 URL（默认从 settings 读取）
            api_token: API 认证 Token（默认从 settings 读取）
        """
        self.api_url = api_url or getattr(
            settings, 
            'STUDYX_AGENT_API_URL', 
            'https://test.istudyx.com/api/studyx/v5/cloud/note/flashcardsAndQuiz/createFlashcardAgent'
        )
        self.api_token = api_token or getattr(
            settings, 
            'STUDYX_AGENT_API_TOKEN', 
            settings.EXTERNAL_API_TOKEN
        )
        
        # Note 会话缓存：note_id -> NoteSession
        self._note_sessions: Dict[str, NoteSession] = {}
        
        # 确保本地测试目录存在
        self.LOCAL_TEST_NOTE_DIR.mkdir(parents=True, exist_ok=True)
    
    # ============================================================
    # Note 内容管理
    # ============================================================
    
    async def download_note_content(
        self,
        content_url: str,
        timeout: int = 30
    ) -> str:
        """
        从 URL 下载 note 内容
        
        Args:
            content_url: 内容 URL（如 https://files.istudyx.com/...）
            timeout: 超时时间
            
        Returns:
            下载的文本内容
        """
        logger.info(f"📥 Downloading note content from: {content_url[:50]}...")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    content_url,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"Failed to download: HTTP {response.status}")
                    
                    content = await response.text()
                    logger.info(f"✅ Downloaded {len(content)} characters")
                    return content
                    
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            raise
    
    async def get_note_content(
        self,
        content_list: List[Dict[str, Any]],
        use_local_fallback: bool = True
    ) -> str:
        """
        获取 note 内容 - 优先从 URL 下载，失败时使用本地文件
        
        Args:
            content_list: [{"content": "url", "contentSize": 123}]
            use_local_fallback: 下载失败时是否使用本地测试文件
            
        Returns:
            合并后的 note 内容
        """
        all_content = []
        
        for item in content_list:
            url = item.get("content", "")
            
            try:
                # 尝试从 URL 下载
                content = await self.download_note_content(url)
                all_content.append(content)
                
            except Exception as e:
                logger.warning(f"⚠️ Download failed for {url}: {e}")
                
                if use_local_fallback:
                    # 使用本地测试文件
                    local_content = self._get_local_test_content()
                    if local_content:
                        logger.info("📂 Using local test content as fallback")
                        all_content.append(local_content)
        
        return "\n\n".join(all_content) if all_content else ""
    
    def _get_local_test_content(self) -> Optional[str]:
        """获取本地测试 note 内容"""
        test_file = self.LOCAL_TEST_NOTE_DIR / "test_note.txt"
        
        if test_file.exists():
            return test_file.read_text(encoding='utf-8')
        
        # 创建默认测试文件
        default_content = """# 测试学习笔记 - 牛顿三大定律

## 第一定律（惯性定律）
一个物体如果不受外力作用，将保持静止状态或匀速直线运动状态。

关键概念：
- 惯性：物体保持原有运动状态的性质
- 参考系：惯性定律在惯性参考系中成立

## 第二定律（加速度定律）
物体的加速度与作用力成正比，与物体质量成反比。

公式：F = ma

其中：
- F：作用力（牛顿，N）
- m：质量（千克，kg）
- a：加速度（米/秒²，m/s²）

应用例子：
1. 推动购物车：用力越大，加速度越大
2. 汽车刹车：刹车力产生负加速度

## 第三定律（作用与反作用定律）
两个物体之间的作用力和反作用力，大小相等，方向相反，作用在同一条直线上。

特点：
- 同时产生，同时消失
- 作用在不同物体上
- 性质相同

生活实例：
1. 游泳时手向后划水，水给人向前的反作用力
2. 火箭发射时，燃气向下喷出，火箭向上运动
3. 走路时脚蹬地，地面给脚向前的摩擦力

## 总结
牛顿三大定律是经典力学的基础，描述了物体运动与力的关系。
"""
        test_file.write_text(default_content, encoding='utf-8')
        logger.info(f"📝 Created default test note: {test_file}")
        return default_content
    
    # ============================================================
    # API 调用
    # ============================================================
    
    async def _call_api(
        self,
        request_body: Dict[str, Any],
        timeout: int = 120
    ) -> Dict[str, Any]:
        """
        调用 createFlashcardAgent API
        
        Args:
            request_body: 请求体
            timeout: 超时时间（秒）
            
        Returns:
            API 响应数据
        """
        headers = {
            "token": self.api_token,
            "User-Agent": "Apifox/1.0.0 (https://apifox.com)",
            "Content-Type": "application/json"
        }
        
        logger.info(f"{'='*60}")
        logger.info(f"🌐 STUDYX AGENT API CALL")
        logger.info(f"{'='*60}")
        logger.info(f"📤 URL: {self.api_url}")
        logger.info(f"📤 Request Body: {request_body}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    response_data = await response.json()
                    
                    logger.info(f"{'─'*60}")
                    logger.info(f"📥 Response Status: {response.status}")
                    logger.info(f"📥 Response Data: {response_data}")
                    
                    if response.status != 200:
                        logger.error(f"❌ API HTTP error: {response.status}")
                        raise Exception(f"API HTTP error: {response.status}")
                    
                    if response_data.get("code") != 0:
                        error_msg = response_data.get("msg", "Unknown error")
                        logger.error(f"❌ API business error: {error_msg}")
                        raise Exception(f"API business error: {error_msg}")
                    
                    logger.info(f"{'='*60}")
                    logger.info(f"✅ STUDYX AGENT API SUCCESS")
                    logger.info(f"{'='*60}")
                    
                    return response_data
                    
        except aiohttp.ClientError as e:
            logger.error(f"❌ Network error: {e}")
            raise Exception(f"Network error: {e}")
        except asyncio.TimeoutError:
            logger.error(f"❌ Request timeout after {timeout}s")
            raise Exception(f"Request timeout after {timeout}s")
        except Exception as e:
            logger.error(f"❌ API call failed: {e}")
            raise
    
    # ============================================================
    # 核心流程：初始化 Note 会话
    # ============================================================
    
    async def initialize_note_session(
        self,
        note_dto: Dict[str, Any],
        card_set_note_dto: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        download_content: bool = True
    ) -> NoteSession:
        """
        🔥 核心方法：初始化 Note 会话
        
        完整流程：
        1. 从 noteDto 的 contentList URL 下载内容
        2. 调用 createFlashcardAgent API 创建 Note + Flashcards
        3. 获取 noteId
        4. 创建 NoteSession 保存上下文
        
        Args:
            note_dto: 前端传入的 noteDto（包含所有字段）
            card_set_note_dto: Flashcard 配置（可选）
            session_id: 关联的 chat session ID（可选，自动生成）
            download_content: 是否下载 note 内容
            
        Returns:
            NoteSession 对象，包含 noteId 和 note 内容
        """
        logger.info("🚀 Initializing Note Session...")
        logger.info(f"   • noteDto: {note_dto}")
        
        # 1. 提取 contentList
        content_list = note_dto.get("contentList", [])
        if not content_list:
            # 使用默认内容
            content_list = [{
                "content": self.DEFAULT_CONTENT_URL,
                "contentSize": self.DEFAULT_CONTENT_SIZE
            }]
        
        # 2. 下载 note 内容（用于上下文管理）
        note_content = ""
        if download_content:
            note_content = await self.get_note_content(content_list)
            logger.info(f"📄 Note content loaded: {len(note_content)} chars")
        
        # 3. 构建 API 请求
        api_note_dto = NoteDto(
            libraryCourseId=note_dto.get("libraryCourseId", self.DEFAULT_LIBRARY_COURSE_ID),
            noteTitle=note_dto.get("noteTitle", "StudyX Agent Note"),
            noteType=note_dto.get("noteType", 1),
            disableAutoInsertToLibrary=note_dto.get("disableAutoInsertToLibrary", 1),
            contentList=content_list
        )
        
        # 4. 如果提供了 cardSetNoteDto，创建 Flashcards
        flashcards_data = None
        if card_set_note_dto:
            api_card_dto = CardSetNoteDto(
                outLanguage=card_set_note_dto.get("outLanguage"),
                libraryCourseId=card_set_note_dto.get("libraryCourseId", api_note_dto.libraryCourseId),
                isPublic=card_set_note_dto.get("isPublic", 1),
                tags=card_set_note_dto.get("tags"),
                cardCount=card_set_note_dto.get("cardCount")
            )
            
            request_body = {
                "noteDto": api_note_dto.to_dict(),
                "cardSetNoteDto": api_card_dto.to_dict()
            }
        else:
            # 只创建 Note，不创建 Flashcards
            # 注意：API 可能需要 cardSetNoteDto，使用最小配置
            request_body = {
                "noteDto": api_note_dto.to_dict(),
                "cardSetNoteDto": {
                    "libraryCourseId": api_note_dto.libraryCourseId,
                    "isPublic": 1,
                    "cardCount": 1  # 最少创建1张卡片
                }
            }
        
        # 5. 调用 API
        response = await self._call_api(request_body)
        
        # 6. 提取 noteId
        data = response.get("data", {})
        note_id = data.get("noteId")
        
        if not note_id:
            raise Exception("API response missing noteId")
        
        # 7. 创建 NoteSession
        if not session_id:
            session_id = f"note_{note_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        note_session = NoteSession(
            note_id=note_id,
            note_title=api_note_dto.noteTitle or "Untitled",
            note_content=note_content,
            library_course_id=api_note_dto.libraryCourseId or self.DEFAULT_LIBRARY_COURSE_ID,
            content_urls=[item.get("content", "") for item in content_list],
            session_id=session_id,
            flashcards=data.get("cardSetDto") if card_set_note_dto else None
        )
        
        # 8. 缓存会话
        self._note_sessions[note_id] = note_session
        
        logger.info(f"✅ Note Session initialized:")
        logger.info(f"   • noteId: {note_id}")
        logger.info(f"   • sessionId: {session_id}")
        logger.info(f"   • contentLength: {len(note_content)}")
        
        return note_session
    
    def get_note_session(self, note_id: str) -> Optional[NoteSession]:
        """获取已缓存的 Note 会话"""
        return self._note_sessions.get(note_id)
    
    # ============================================================
    # 🔥 Chat：基于 Note 内容的对话
    # ============================================================
    
    async def chat_with_note(
        self,
        note_id: str,
        message: str,
        user_id: str = "studyx_user",
        file_uris: Optional[List[str]] = None,
        voice_text: Optional[str] = None,
        max_context_chars: int = 8000
    ) -> Dict[str, Any]:
        """
        🔥 核心方法：基于 Note 内容进行对话
        
        支持完整的上下文管理（滑动窗口 + 智能检索）和多输入源。
        
        Args:
            note_id: noteId（从 init-session 获取）
            message: 用户消息
            user_id: 用户 ID（用于 MD 文件存储）
            file_uris: 文件 URI 列表（图片、文档等）
            voice_text: 语音转文本内容
            max_context_chars: note 内容最大字符数
            
        Returns:
            包含响应和上下文统计的字典
        """
        import time
        import re
        start_time = time.time()
        
        # Token 统计
        token_usage = {
            "llm_generation": {"input": 0, "output": 0, "total": 0},
            "context_retrieval": {"retrieved_turns": 0},
            "total": {"total": 0}
        }
        
        # 上下文统计
        context_stats = {
            "session_turns": 0,
            "loaded_turns": 0,
            "retrieved_turns": 0,
            "total_context_chars": 0,
            "has_files": False,
            "file_count": 0
        }
        
        # 1. 获取 Note 会话
        note_session = self.get_note_session(note_id)
        if not note_session:
            raise Exception(f"Note session not found: {note_id}. Please call /init-session first.")
        
        # 2. 合并输入（文本 + 语音）
        full_message = message
        if voice_text:
            full_message = f"{message}\n[语音输入]: {voice_text}" if message else voice_text
        
        logger.info(f"💬 Chat with Note: {note_id}")
        logger.info(f"   • Message: {full_message[:50]}...")
        logger.info(f"   • Note content: {len(note_session.note_content)} chars")
        logger.info(f"   • Files: {len(file_uris) if file_uris else 0}")
        
        # 3. 保存用户消息到内存
        note_session.add_chat_message("user", full_message)
        
        # 4. 上下文管理：滑动窗口 + 智能检索
        chat_history, retrieved_context = self._build_chat_context_with_retrieval(
            note_session=note_session,
            current_message=full_message,
            max_turns=5
        )
        
        context_stats["session_turns"] = len(note_session.chat_history) // 2
        context_stats["loaded_turns"] = min(5, context_stats["session_turns"])
        context_stats["retrieved_turns"] = len(retrieved_context) if retrieved_context else 0
        token_usage["context_retrieval"]["retrieved_turns"] = context_stats["retrieved_turns"]
        
        # 5. 构建 prompt
        # 截取 note 内容（避免超长）
        note_content = note_session.note_content
        if len(note_content) > max_context_chars:
            note_content = note_content[:max_context_chars] + "\n...[内容已截断]..."
        
        # 文件附件说明
        file_section = ""
        if file_uris:
            context_stats["has_files"] = True
            context_stats["file_count"] = len(file_uris)
            file_names = [uri.split('/')[-1] for uri in file_uris]
            file_section = f"\n## 用户附件\n{', '.join(file_names)}\n"
        
        # 检索到的早期对话
        retrieval_section = ""
        if retrieved_context:
            retrieval_section = f"\n## 📚 检索到的早期对话\n{retrieved_context}\n"
        
        prompt = f"""你是一个智能学习助手 "Sai"，正在帮助用户学习和理解以下学习材料。

## 学习材料（Note）
标题: {note_session.note_title}

{note_content}
{retrieval_section}
## 最近对话历史
{chat_history if chat_history else "（这是第一轮对话）"}
{file_section}
## 用户问题
{full_message}

## 要求
1. 基于上面的学习材料回答用户的问题
2. 如果用户上传了图片/文档，请分析其内容并结合学习材料回答
3. 如果用户引用早期对话（"之前讲的..."），请参考检索到的早期对话
4. 回答要清晰、准确、有帮助
5. 可以给出例子、类比来帮助理解

请直接回答："""

        context_stats["total_context_chars"] = len(prompt)
        
        # 6. 调用 LLM
        try:
            from app.services.gemini import GeminiClient
            gemini = GeminiClient()
            
            result = await gemini.generate(
                prompt=prompt,
                model="gemini-2.5-flash",
                response_format="text",
                max_tokens=2000,
                temperature=0.7,
                file_uris=file_uris  # 🆕 传递文件附件
            )
            
            response_text = result.get("content", "抱歉，我无法生成回复。")
            usage = result.get("usage", {})
            token_usage["llm_generation"]["input"] = usage.get("input_tokens", 0)
            token_usage["llm_generation"]["output"] = usage.get("output_tokens", 0)
            token_usage["llm_generation"]["total"] = usage.get("total_tokens", 0)
            token_usage["total"]["total"] = token_usage["llm_generation"]["total"]
            
        except Exception as e:
            logger.error(f"❌ LLM generation failed: {e}")
            response_text = f"抱歉，生成回复时出错：{str(e)}"
        
        # 7. 保存 AI 回复到内存
        note_session.add_chat_message("assistant", response_text)
        
        elapsed = time.time() - start_time
        chat_turns = len(note_session.chat_history) // 2
        
        # 8. 保存到 artifact MD 文件
        await self._save_chat_to_md(
            note_session=note_session,
            user_id=user_id,
            user_message=full_message,
            assistant_response=response_text,
            token_usage=token_usage,
            file_uris=file_uris
        )
        
        logger.info(f"✅ Chat response generated in {elapsed:.2f}s")
        logger.info(f"   • Response: {response_text[:50]}...")
        logger.info(f"   • Chat turns: {chat_turns}")
        logger.info(f"   • Retrieved turns: {context_stats['retrieved_turns']}")
        
        return {
            "response": response_text,
            "note_id": note_id,
            "session_id": note_session.session_id,
            "note_title": note_session.note_title,
            "chat_turns": chat_turns,
            "generation_time": round(elapsed, 2),
            "context_stats": context_stats,
            "token_usage": token_usage
        }
    
    def _build_chat_context_with_retrieval(
        self,
        note_session: NoteSession,
        current_message: str,
        max_turns: int = 5
    ) -> tuple:
        """
        构建对话上下文 + 智能检索早期对话
        
        实现滑动窗口 + 关键词检索
        
        Returns:
            (recent_history_str, retrieved_context_str)
        """
        import re
        
        # 1. 滑动窗口：最近 max_turns 轮
        recent_messages = note_session.chat_history[-(max_turns * 2):]
        recent_lines = []
        for msg in recent_messages:
            prefix = "用户" if msg.role == "user" else "助手"
            # 截断过长的回复
            content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
            recent_lines.append(f"{prefix}: {content}")
        recent_history = "\n".join(recent_lines)
        
        # 2. 智能检索：检测是否引用早期内容
        retrieved_context = ""
        
        # 检测时间引用
        time_patterns = [
            r'最开始|一开始|开头|最初|之前|早些时候|刚开始',
            r'回到.*(开始|最初|之前)',
            r'前面.*(说|讲|提到)',
        ]
        
        # 检测索引引用
        index_pattern = r'第([一二三四五六七八九十\d]+)[轮个道]'
        
        # 检测关键词引用
        keyword_patterns = [
            r'(Redis|DynamoDB|DTO|DAO)',
            r'(增值税|消费税|企业所得税)',
            r'(市场营销|细分|目标市场)',
        ]
        
        has_reference = False
        reference_type = None
        
        for pattern in time_patterns:
            if re.search(pattern, current_message):
                has_reference = True
                reference_type = "time"
                break
        
        if not has_reference:
            match = re.search(index_pattern, current_message)
            if match:
                has_reference = True
                reference_type = "index"
        
        if not has_reference:
            for pattern in keyword_patterns:
                if re.search(pattern, current_message, re.IGNORECASE):
                    has_reference = True
                    reference_type = "keyword"
                    break
        
        # 3. 如果检测到引用，从早期对话中检索
        if has_reference and len(note_session.chat_history) > max_turns * 2:
            early_messages = note_session.chat_history[:-(max_turns * 2)]
            
            if reference_type == "time":
                # 返回最早的几轮
                earliest = early_messages[:6]  # 最早3轮
                retrieved_lines = []
                for i, msg in enumerate(earliest):
                    prefix = "用户" if msg.role == "user" else "助手"
                    content = msg.content[:150] + "..." if len(msg.content) > 150 else msg.content
                    turn_num = i // 2 + 1
                    retrieved_lines.append(f"[T{turn_num}] {prefix}: {content}")
                retrieved_context = "\n".join(retrieved_lines)
                logger.info(f"🔎 时间引用检索: 返回最早 {len(earliest)//2} 轮")
            
            elif reference_type == "keyword":
                # 关键词搜索
                keywords = []
                for pattern in keyword_patterns:
                    matches = re.findall(pattern, current_message, re.IGNORECASE)
                    keywords.extend(matches)
                
                retrieved_msgs = []
                for i, msg in enumerate(early_messages):
                    for kw in keywords:
                        if kw.lower() in msg.content.lower():
                            retrieved_msgs.append((i, msg))
                            break
                
                if retrieved_msgs:
                    retrieved_lines = []
                    for i, msg in retrieved_msgs[:6]:  # 最多3轮
                        prefix = "用户" if msg.role == "user" else "助手"
                        content = msg.content[:150] + "..." if len(msg.content) > 150 else msg.content
                        turn_num = i // 2 + 1
                        retrieved_lines.append(f"[T{turn_num}] {prefix}: {content}")
                    retrieved_context = "\n".join(retrieved_lines)
                    logger.info(f"🔎 关键词检索: 找到 {len(retrieved_msgs)//2} 轮相关对话")
        
        return recent_history, retrieved_context
    
    async def _save_chat_to_md(
        self,
        note_session: NoteSession,
        user_id: str,
        user_message: str,
        assistant_response: str,
        token_usage: Dict[str, Any],
        file_uris: Optional[List[str]] = None
    ):
        """
        🆕 保存 chat 对话到 artifact MD 文件
        
        复用现有的 ConversationSessionManager 逻辑
        """
        try:
            from app.core.memory_manager import MemoryManager
            
            memory_manager = MemoryManager()
            session_mgr = memory_manager.get_conversation_session_manager(user_id)
            
            # 使用 note_session 的 session_id
            await session_mgr.start_or_continue_session(
                user_message=user_message,
                session_id=note_session.session_id
            )
            
            # 提取 token 统计
            llm_usage = token_usage.get("llm_generation", {})
            
            # 构建 turn_data（兼容现有格式）
            turn_data = {
                "user_query": user_message,
                "agent_response": {
                    "skill": "note_chat",
                    "artifact_id": note_session.note_id,
                    "content": {
                        "text": assistant_response,
                        "note_id": note_session.note_id,
                        "note_title": note_session.note_title
                    },
                    "topic": note_session.note_title
                },
                "response_type": "text",
                "timestamp": datetime.now(),
                "intent": {
                    "intent": "note_chat",
                    "topic": note_session.note_title,
                    "confidence": 1.0,
                    "parameters": {
                        "note_id": note_session.note_id,
                        "library_course_id": note_session.library_course_id,
                        "file_uris": file_uris
                    },
                    "raw_text": user_message
                },
                "metadata": {
                    "input_tokens": llm_usage.get("input", 0),
                    "output_tokens": llm_usage.get("output", 0),
                    "total_tokens": llm_usage.get("total", 0),
                    "model": "gemini-2.5-flash",
                    "source": "/api/studyx-agent/chat",
                    "note_content_length": len(note_session.note_content),
                    "has_files": bool(file_uris),
                    "file_count": len(file_uris) if file_uris else 0,
                    "retrieved_turns": token_usage.get("context_retrieval", {}).get("retrieved_turns", 0)
                }
            }
            
            # 保存到 MD 文件
            await session_mgr.append_turn(turn_data)
            
            logger.info(f"📝 Saved chat to MD: session={note_session.session_id}, note={note_session.note_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save chat to MD: {e}")
    
    # ============================================================
    # 基于 Note 会话生成内容
    # ============================================================
    
    async def create_flashcards_from_note(
        self,
        note_id: str,
        card_set_note_dto: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        基于已有的 noteId 创建 Flashcards
        
        注意：这使用 noteId 调用 API，不是重新创建 Note
        """
        note_session = self.get_note_session(note_id)
        
        request_body = {
            "noteDto": {"noteId": note_id},
            "cardSetNoteDto": {
                "outLanguage": card_set_note_dto.get("outLanguage"),
                "libraryCourseId": card_set_note_dto.get("libraryCourseId", 
                    note_session.library_course_id if note_session else self.DEFAULT_LIBRARY_COURSE_ID),
                "isPublic": card_set_note_dto.get("isPublic", 1),
                "tags": card_set_note_dto.get("tags"),
                "cardCount": card_set_note_dto.get("cardCount")
            }
        }
        
        response = await self._call_api(request_body)
        
        # 更新会话缓存
        if note_session:
            note_session.flashcards = response.get("data", {}).get("cardSetDto")
        
        return response.get("data", {})
    
    async def create_quiz_from_note(
        self,
        note_id: str,
        quiz_set_note_dto: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        基于已有的 noteId 创建 Quiz
        
        注意：这使用 noteId 调用 API
        """
        note_session = self.get_note_session(note_id)
        
        request_body = {
            "noteDto": {"noteId": note_id},
            "quizSetNoteDto": {
                "quizCount": quiz_set_note_dto.get("quizCount"),
                "libraryCourseId": quiz_set_note_dto.get("libraryCourseId",
                    note_session.library_course_id if note_session else self.DEFAULT_LIBRARY_COURSE_ID),
                "isPublic": quiz_set_note_dto.get("isPublic", 1),
                "tags": quiz_set_note_dto.get("tags"),
                "outLanguage": quiz_set_note_dto.get("outLanguage")
            }
        }
        
        response = await self._call_api(request_body)
        
        # 更新会话缓存
        if note_session:
            note_session.quiz = response.get("data", {})
        
        return response.get("data", {})
    
    # ============================================================
    # 遗留方法（保持向后兼容）
    # ============================================================
    
    async def create_flashcards(
        self,
        note_dto: NoteDto,
        card_set_note_dto: CardSetNoteDto
    ) -> Dict[str, Any]:
        """Step 1: 创建 Note + Flashcards"""
        request_body = {
            "noteDto": note_dto.to_dict(),
            "cardSetNoteDto": card_set_note_dto.to_dict()
        }
        return await self._call_api(request_body)
    
    async def create_quiz(
        self,
        note_id: str,
        quiz_set_note_dto: QuizSetNoteDto
    ) -> Dict[str, Any]:
        """Step 2: 使用 noteId 创建 Quiz"""
        note_dto = NoteDto(noteId=note_id)
        request_body = {
            "noteDto": note_dto.to_dict(),
            "quizSetNoteDto": quiz_set_note_dto.to_dict()
        }
        return await self._call_api(request_body)
    
    async def create_flashcards_and_quiz(
        self,
        library_course_id: Optional[str] = None,
        note_title: Optional[str] = None,
        content_list: Optional[List[Dict[str, Any]]] = None,
        flashcard_language: Optional[str] = None,
        flashcard_count: Optional[int] = None,
        flashcard_tags: Optional[str] = None,
        flashcard_is_public: int = 1,
        quiz_language: Optional[str] = None,
        quiz_count: Optional[int] = None,
        quiz_tags: Optional[str] = None,
        quiz_is_public: int = 1,
        create_flashcards: bool = True,
        create_quiz: bool = True
    ) -> Dict[str, Any]:
        """完整流程：创建 Note + Flashcards + Quiz"""
        result = {
            "note_id": None,
            "note_content": None,  # 🆕 添加 note 内容
            "flashcards": None,
            "quiz": None
        }
        
        library_course_id = library_course_id or self.DEFAULT_LIBRARY_COURSE_ID
        note_title = note_title or "StudyX Agent Generated Note"
        
        if not content_list:
            content_list = [{
                "content": self.DEFAULT_CONTENT_URL,
                "contentSize": self.DEFAULT_CONTENT_SIZE
            }]
        
        # 🆕 下载 note 内容
        try:
            note_content = await self.get_note_content(content_list)
            result["note_content"] = note_content
        except Exception as e:
            logger.warning(f"⚠️ Failed to download note content: {e}")
        
        # Step 1: 创建 Flashcards
        if create_flashcards:
            note_dto = NoteDto(
                libraryCourseId=library_course_id,
                noteTitle=note_title,
                noteType=1,
                disableAutoInsertToLibrary=1,
                contentList=content_list
            )
            
            card_set_note_dto = CardSetNoteDto(
                outLanguage=flashcard_language,
                libraryCourseId=library_course_id,
                isPublic=flashcard_is_public,
                tags=flashcard_tags,
                cardCount=flashcard_count
            )
            
            flashcard_response = await self.create_flashcards(note_dto, card_set_note_dto)
            
            data = flashcard_response.get("data", {})
            note_id = data.get("noteId")
            
            result["note_id"] = note_id
            result["flashcards"] = data
            
            logger.info(f"✅ Step 1 Complete: noteId={note_id}")
        
        # Step 2: 创建 Quiz
        if create_quiz and result["note_id"]:
            quiz_set_note_dto = QuizSetNoteDto(
                quizCount=quiz_count,
                libraryCourseId=library_course_id,
                isPublic=quiz_is_public,
                tags=quiz_tags,
                outLanguage=quiz_language
            )
            
            try:
                quiz_response = await self.create_quiz(result["note_id"], quiz_set_note_dto)
                result["quiz"] = quiz_response.get("data", {})
                logger.info(f"✅ Step 2 Complete: Quiz created")
            except Exception as e:
                logger.warning(f"⚠️ Quiz creation failed (continuing): {e}")
                result["quiz_error"] = str(e)
        
        return result
    
    async def create_flashcards_only(
        self,
        library_course_id: Optional[str] = None,
        note_title: Optional[str] = None,
        content_list: Optional[List[Dict[str, Any]]] = None,
        language: Optional[str] = None,
        count: Optional[int] = None,
        tags: Optional[str] = None
    ) -> Dict[str, Any]:
        """只创建 Flashcards（不创建 Quiz）"""
        return await self.create_flashcards_and_quiz(
            library_course_id=library_course_id,
            note_title=note_title,
            content_list=content_list,
            flashcard_language=language,
            flashcard_count=count,
            flashcard_tags=tags,
            create_flashcards=True,
            create_quiz=False
        )
    
    async def create_quiz_only(
        self,
        note_id: str,
        library_course_id: Optional[str] = None,
        language: Optional[str] = None,
        count: Optional[int] = None,
        tags: Optional[str] = None
    ) -> Dict[str, Any]:
        """只创建 Quiz（需要已有的 noteId）"""
        library_course_id = library_course_id or self.DEFAULT_LIBRARY_COURSE_ID
        
        quiz_set_note_dto = QuizSetNoteDto(
            quizCount=count,
            libraryCourseId=library_course_id,
            isPublic=1,
            tags=tags,
            outLanguage=language
        )
        
        quiz_response = await self.create_quiz(note_id, quiz_set_note_dto)
        
        return {
            "note_id": note_id,
            "quiz": quiz_response.get("data", {})
        }
    
    # ============================================================
    # 🔥 本地生成方法（使用 prompts + Gemini）
    # ============================================================
    
    def _load_prompt(self, prompt_name: str) -> str:
        """加载 prompt 文件"""
        prompt_path = Path(__file__).parent.parent / "prompts" / f"{prompt_name}.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        else:
            logger.warning(f"⚠️ Prompt file not found: {prompt_path}")
            return ""
    
    async def generate_flashcards_local(
        self,
        user_request: str,
        reference_content: Optional[str] = None,
        output_language: str = "cn",
        card_count: int = 5,
        note_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        🔥 使用本地 prompt + Gemini 生成 Flashcards
        
        返回格式与外部 API 一致:
        {
            "title": "...",
            "cardList": [{"front": "...", "back": "..."}, ...]
        }
        """
        import json
        import time
        start_time = time.time()
        
        logger.info(f"📝 Generating flashcards locally: {user_request[:50]}...")
        
        # 如果提供了 note_id，尝试获取 note 内容
        if note_id and not reference_content:
            note_session = self.get_note_session(note_id)
            if note_session:
                reference_content = note_session.note_content[:10000]  # 限制长度
        
        # 加载 prompt
        prompt_template = self._load_prompt("flashcard_skill_external")
        if not prompt_template:
            # 使用内置 prompt
            prompt_template = """Generate flashcards in JSON format:
{"title": "Topic Title", "cardList": [{"front": "Question", "back": "Answer"}]}
User request: {user_request}
Reference: {reference_content}
Language: {output_language}
Count: {card_count}
Output ONLY valid JSON."""
        
        # 构建 prompt
        prompt = prompt_template.replace("{user_request}", user_request)
        prompt = prompt.replace("{reference_content}", reference_content or "无参考内容")
        prompt = prompt.replace("{output_language}", output_language)
        prompt = prompt.replace("{card_count}", str(card_count))
        
        # 调用 Gemini
        try:
            from app.services.gemini import GeminiClient
            gemini = GeminiClient()
            
            result = await gemini.generate(
                prompt=prompt,
                model="gemini-2.5-flash",
                response_format="json",
                max_tokens=2000,
                temperature=0.7
            )
            
            content = result.get("content", "")
            
            # 解析 JSON
            try:
                # 清理可能的 markdown 标记
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                flashcard_data = json.loads(content.strip())
                
                # 确保格式正确
                if "cardList" not in flashcard_data:
                    # 尝试转换其他可能的格式
                    if "cards" in flashcard_data:
                        flashcard_data["cardList"] = flashcard_data.pop("cards")
                
                elapsed = time.time() - start_time
                logger.info(f"✅ Flashcards generated locally in {elapsed:.2f}s: {len(flashcard_data.get('cardList', []))} cards")
                
                return {
                    "code": 0,
                    "msg": "Request succeeded",
                    "data": flashcard_data,
                    "source": "local_gemini",
                    "generation_time": round(elapsed, 2),
                    "token_usage": result.get("usage", {})
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON parse error: {e}, content: {content[:200]}")
                return {
                    "code": 500,
                    "msg": f"JSON parse error: {e}",
                    "data": None
                }
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return {
                "code": 500,
                "msg": str(e),
                "data": None
            }
    
    async def generate_quiz_local(
        self,
        user_request: str,
        reference_content: Optional[str] = None,
        output_language: str = "cn",
        quiz_count: int = 3,
        note_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        🔥 使用本地 prompt + Gemini 生成 Quiz
        
        返回格式与外部 API 一致:
        {
            "title": "...",
            "questions": [
                {
                    "question": "...",
                    "answer_options": [
                        {"text": "...", "rationale": "...", "is_correct": true/false}
                    ],
                    "hint": "..."
                }
            ]
        }
        """
        import json
        import time
        start_time = time.time()
        
        logger.info(f"📝 Generating quiz locally: {user_request[:50]}...")
        
        # 如果提供了 note_id，尝试获取 note 内容
        if note_id and not reference_content:
            note_session = self.get_note_session(note_id)
            if note_session:
                reference_content = note_session.note_content[:10000]  # 限制长度
        
        # 加载 prompt
        prompt_template = self._load_prompt("quiz_skill_external")
        if not prompt_template:
            # 使用内置 prompt
            prompt_template = """Generate quiz in JSON format:
{"title": "Quiz Title", "questions": [{"question": "...", "answer_options": [{"text": "...", "rationale": "...", "is_correct": false/true}], "hint": "..."}]}
User request: {user_request}
Reference: {reference_content}
Language: {output_language}
Count: {quiz_count}
Output ONLY valid JSON. Each question must have 4 options with exactly 1 correct."""
        
        # 构建 prompt
        prompt = prompt_template.replace("{user_request}", user_request)
        prompt = prompt.replace("{reference_content}", reference_content or "无参考内容")
        prompt = prompt.replace("{output_language}", output_language)
        prompt = prompt.replace("{quiz_count}", str(quiz_count))
        
        # 调用 Gemini
        try:
            from app.services.gemini import GeminiClient
            gemini = GeminiClient()
            
            result = await gemini.generate(
                prompt=prompt,
                model="gemini-2.5-flash",
                response_format="json",
                max_tokens=3000,
                temperature=0.7
            )
            
            content = result.get("content", "")
            
            # 解析 JSON
            try:
                # 清理可能的 markdown 标记
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                quiz_data = json.loads(content.strip())
                
                # 确保格式正确
                if "questions" not in quiz_data:
                    # 尝试转换其他可能的格式
                    if "quiz" in quiz_data:
                        quiz_data["questions"] = quiz_data.pop("quiz")
                
                elapsed = time.time() - start_time
                logger.info(f"✅ Quiz generated locally in {elapsed:.2f}s: {len(quiz_data.get('questions', []))} questions")
                
                return {
                    "code": 0,
                    "msg": "Request succeeded",
                    "data": quiz_data,
                    "source": "local_gemini",
                    "generation_time": round(elapsed, 2),
                    "token_usage": result.get("usage", {})
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON parse error: {e}, content: {content[:200]}")
                return {
                    "code": 500,
                    "msg": f"JSON parse error: {e}",
                    "data": None
                }
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return {
                "code": 500,
                "msg": str(e),
                "data": None
            }
    
    async def generate_mindmap_local(
        self,
        user_request: str,
        reference_content: Optional[str] = None,
        output_language: str = "cn",
        max_depth: int = 3,
        max_branches: int = 4,
        note_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        🔥 使用本地 prompt + Gemini 生成思维导图
        """
        import json
        import time
        start_time = time.time()
        
        logger.info(f"📝 Generating mindmap locally: {user_request[:50]}...")
        
        # 如果提供了 note_id，尝试获取 note 内容
        if note_id and not reference_content:
            note_session = self.get_note_session(note_id)
            if note_session:
                reference_content = note_session.note_content[:10000]
        
        # 加载 prompt
        prompt_template = self._load_prompt("mindmap_skill")
        if not prompt_template:
            prompt_template = """Generate mindmap in JSON format based on the topic.
Topic: {user_request}
Reference: {reference_content}
Language: {output_language}
Max depth: {max_depth}
Max branches: {max_branches}

Output JSON format:
{
  "mindmap_id": "mindmap_xxx",
  "subject": "Subject",
  "topic": "Topic",
  "root": {
    "id": "root",
    "text": "Central Topic",
    "color": "#10b981",
    "children": [
      {
        "id": "node-1",
        "text": "Branch 1",
        "color": "#3b82f6",
        "children": []
      }
    ]
  },
  "structure_summary": "Brief description"
}
Output ONLY valid JSON."""
        
        # 构建 prompt
        prompt = prompt_template.replace("{user_request}", user_request)
        prompt = prompt.replace("{reference_content}", reference_content or "无参考内容")
        prompt = prompt.replace("{output_language}", output_language)
        prompt = prompt.replace("{max_depth}", str(max_depth))
        prompt = prompt.replace("{max_branches}", str(max_branches))
        prompt = prompt.replace("{topic}", user_request)
        prompt = prompt.replace("{subject}", "General")
        prompt = prompt.replace("{reference_explanation}", reference_content or "无参考内容")
        
        try:
            from app.services.gemini import GeminiClient
            gemini = GeminiClient()
            
            result = await gemini.generate(
                prompt=prompt,
                model="gemini-2.5-flash",
                response_format="json",
                max_tokens=2000,
                temperature=0.7
            )
            
            content = result.get("content", "")
            
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                mindmap_data = json.loads(content.strip())
                
                elapsed = time.time() - start_time
                logger.info(f"✅ Mindmap generated locally in {elapsed:.2f}s")
                
                return {
                    "code": 0,
                    "msg": "Request succeeded",
                    "data": mindmap_data,
                    "source": "local_gemini",
                    "generation_time": round(elapsed, 2),
                    "token_usage": result.get("usage", {})
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON parse error: {e}")
                return {"code": 500, "msg": f"JSON parse error: {e}", "data": None}
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return {"code": 500, "msg": str(e), "data": None}
    
    async def generate_notes_local(
        self,
        user_request: str,
        reference_content: Optional[str] = None,
        output_language: str = "cn",
        note_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        🔥 使用本地 prompt + Gemini 生成笔记/总结
        """
        import json
        import time
        start_time = time.time()
        
        logger.info(f"📝 Generating notes locally: {user_request[:50]}...")
        
        # 如果提供了 note_id，尝试获取 note 内容
        if note_id and not reference_content:
            note_session = self.get_note_session(note_id)
            if note_session:
                reference_content = note_session.note_content[:10000]
        
        # 加载 prompt
        prompt_template = self._load_prompt("notes_skill")
        if not prompt_template:
            prompt_template = """Extract notes from reference content.
Topic: {user_request}
Reference: {reference_content}
Language: {output_language}

Output JSON format:
{
  "notes_id": "notes_xxx",
  "subject": "Subject",
  "topic": "Topic",
  "structured_notes": {
    "title": "Notes Title",
    "sections": [
      {"heading": "Section 1", "bullet_points": ["point 1", "point 2"]},
      {"heading": "Section 2", "bullet_points": ["point 3", "point 4"]}
    ]
  }
}
Output ONLY valid JSON. Include 2-4 sections with 2-5 bullet points each."""
        
        # 构建 prompt
        prompt = prompt_template.replace("{user_request}", user_request)
        prompt = prompt.replace("{reference_content}", reference_content or "无参考内容")
        prompt = prompt.replace("{output_language}", output_language)
        prompt = prompt.replace("{topic}", user_request)
        prompt = prompt.replace("{subject}", "General")
        prompt = prompt.replace("{reference_explanation}", reference_content or "无参考内容")
        
        try:
            from app.services.gemini import GeminiClient
            gemini = GeminiClient()
            
            result = await gemini.generate(
                prompt=prompt,
                model="gemini-2.5-flash",
                response_format="json",
                max_tokens=2000,
                temperature=0.7
            )
            
            content = result.get("content", "")
            
            try:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                
                notes_data = json.loads(content.strip())
                
                elapsed = time.time() - start_time
                logger.info(f"✅ Notes generated locally in {elapsed:.2f}s")
                
                return {
                    "code": 0,
                    "msg": "Request succeeded",
                    "data": notes_data,
                    "source": "local_gemini",
                    "generation_time": round(elapsed, 2),
                    "token_usage": result.get("usage", {})
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"❌ JSON parse error: {e}")
                return {"code": 500, "msg": f"JSON parse error: {e}", "data": None}
                
        except Exception as e:
            logger.error(f"❌ Gemini generation failed: {e}")
            return {"code": 500, "msg": str(e), "data": None}


# ============================================================
# 全局单例
# ============================================================

_service_instance: Optional[StudyXAgentService] = None


def get_studyx_agent_service() -> StudyXAgentService:
    """获取全局 StudyXAgentService 实例（单例模式）"""
    global _service_instance
    if _service_instance is None:
        _service_instance = StudyXAgentService()
    return _service_instance
