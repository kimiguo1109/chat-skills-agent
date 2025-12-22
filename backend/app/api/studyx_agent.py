"""
StudyX Agent API - 基于新 createFlashcardAgent 接口的服务

这是一个独立的 API 模块，不影响现有的 /api/external/chat 和 /api/chat/send 接口。

完整流程：
1. POST /api/studyx-agent/init-session  - 初始化 Note 会话（核心入口）
   - 前端传入 noteDto（所有字段来自前端）
   - 下载 note 内容
   - 调用 API 创建 Note + Flashcards → 获取 noteId
   - 返回 noteId + sessionId，后续可用于 chat 框架

2. POST /api/studyx-agent/chat          - 基于 Note 上下文的对话
3. POST /api/studyx-agent/flashcards    - 基于 noteId 生成更多闪卡
4. POST /api/studyx-agent/quiz          - 基于 noteId 生成测验

其他端点（兼容旧版）：
- POST /api/studyx-agent/create-all        - 创建 Flashcards + Quiz
- POST /api/studyx-agent/create-flashcards - 只创建 Flashcards
- POST /api/studyx-agent/create-quiz       - 只创建 Quiz（需要 noteId）
"""

import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.studyx_agent_service import (
    get_studyx_agent_service,
    StudyXAgentService,
    NoteSession
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/studyx-agent", tags=["studyx-agent"])


# ============================================================
# Request Models
# ============================================================

class ContentItem(BaseModel):
    """内容项"""
    content: str = Field(..., description="内容 URL 或文本")
    contentSize: Optional[int] = Field(None, description="内容大小（字节）")


class NoteDtoRequest(BaseModel):
    """noteDto - 所有字段来自前端"""
    libraryCourseId: Optional[str] = Field(None, description="课程库 ID")
    noteTitle: Optional[str] = Field(None, description="笔记标题")
    noteType: Optional[int] = Field(1, description="笔记类型")
    disableAutoInsertToLibrary: Optional[int] = Field(1, description="禁止自动插入库")
    contentList: Optional[List[ContentItem]] = Field(None, description="内容列表")


class CardSetNoteDtoRequest(BaseModel):
    """cardSetNoteDto - Flashcard 配置"""
    outLanguage: Optional[str] = Field(None, description="输出语言 (cn/en/jp/kr)")
    libraryCourseId: Optional[str] = Field(None, description="课程库 ID")
    isPublic: Optional[int] = Field(1, description="是否公开")
    tags: Optional[str] = Field(None, description="标签")
    cardCount: Optional[int] = Field(None, description="闪卡数量")


class QuizSetNoteDtoRequest(BaseModel):
    """quizSetNoteDto - Quiz 配置"""
    quizCount: Optional[int] = Field(None, description="题目数量")
    libraryCourseId: Optional[str] = Field(None, description="课程库 ID")
    isPublic: Optional[int] = Field(1, description="是否公开")
    tags: Optional[str] = Field(None, description="标签")
    outLanguage: Optional[str] = Field(None, description="输出语言")


# ============================================================
# 🔥 核心 API：初始化 Note 会话
# ============================================================

class InitSessionRequest(BaseModel):
    """
    初始化 Note 会话请求
    
    这是核心入口 - 前端传入 noteDto，后端：
    1. 下载 note 内容
    2. 调用 API 创建 Note → 获取 noteId
    3. 返回 sessionId，后续用于 chat 框架
    """
    noteDto: NoteDtoRequest = Field(..., description="Note 数据（所有字段来自前端）")
    cardSetNoteDto: Optional[CardSetNoteDtoRequest] = Field(None, description="Flashcard 配置（可选）")
    token: Optional[str] = Field(None, description="API Token（不传使用默认）")
    downloadContent: bool = Field(True, description="是否下载 note 内容")


class InitSessionResponse(BaseModel):
    """初始化会话响应"""
    noteId: str
    sessionId: str
    noteTitle: str
    noteContentLength: int
    flashcards: Optional[Dict[str, Any]] = None


@router.post("/init-session", response_model=Dict[str, Any])
async def init_note_session(request: InitSessionRequest):
    """
    🔥 核心 API：初始化 Note 会话
    
    这是使用新接口的主要入口点。
    
    流程：
    1. 前端传入 noteDto（包含 contentList URL）
    2. 后端下载 note 内容
    3. 调用 createFlashcardAgent API 创建 Note
    4. 返回 noteId + sessionId
    5. 后续可使用 sessionId 进行 chat/flashcard/quiz
    
    请求示例:
    ```json
    {
        "noteDto": {
            "libraryCourseId": "01k5zyf4qwp4ktbxj5a9x6s0tq",
            "noteTitle": "一步到位",
            "noteType": 1,
            "disableAutoInsertToLibrary": 1,
            "contentList": [
                {
                    "content": "https://files.istudyx.com/d0b60b61/xxx.txt",
                    "contentSize": 154055
                }
            ]
        },
        "cardSetNoteDto": {
            "outLanguage": "cn",
            "cardCount": 5
        }
    }
    ```
    
    响应示例:
    ```json
    {
        "code": 0,
        "msg": "Session initialized",
        "data": {
            "noteId": "xxx",
            "sessionId": "note_xxx_20251202_120000",
            "noteTitle": "一步到位",
            "noteContentLength": 15000,
            "flashcards": {...}
        }
    }
    ```
    """
    start_time = time.time()
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/init-session")
    logger.info(f"   • noteDto: {request.noteDto.dict()}")
    logger.info(f"   • cardSetNoteDto: {request.cardSetNoteDto.dict() if request.cardSetNoteDto else 'None'}")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        if request.token:
            service = StudyXAgentService(api_token=request.token)
        
        # 转换 noteDto
        note_dto = request.noteDto.dict()
        if note_dto.get("contentList"):
            note_dto["contentList"] = [
                {"content": item["content"], "contentSize": item.get("contentSize")}
                for item in note_dto["contentList"]
            ]
        
        # 转换 cardSetNoteDto
        card_set_dto = request.cardSetNoteDto.dict() if request.cardSetNoteDto else None
        
        # 初始化会话
        note_session = await service.initialize_note_session(
            note_dto=note_dto,
            card_set_note_dto=card_set_dto,
            download_content=request.downloadContent
        )
        
        total_time = time.time() - start_time
        
        logger.info(f"✅ Session initialized in {total_time:.2f}s")
        logger.info(f"   • noteId: {note_session.note_id}")
        logger.info(f"   • sessionId: {note_session.session_id}")
        
        return {
            "code": 0,
            "msg": "Session initialized",
            "data": {
                "noteId": note_session.note_id,
                "sessionId": note_session.session_id,
                "noteTitle": note_session.note_title,
                "noteContentLength": len(note_session.note_content),
                "flashcards": note_session.flashcards,
                "timing": {
                    "totalTime": round(total_time, 2)
                }
            }
        }
        
    except Exception as e:
        logger.error(f"❌ init_session error: {e}", exc_info=True)
        return {
            "code": 500,
            "msg": str(e),
            "data": None
        }


# ============================================================
# 🔥 Chat：基于 Note 内容的对话
# ============================================================

class NoteChatRequest(BaseModel):
    """基于 Note 内容的对话请求"""
    noteId: str = Field(..., description="noteId（从 init-session 获取）")
    message: str = Field(..., description="用户消息")
    userId: Optional[str] = Field("studyx_user", description="用户 ID（用于 MD 存储）")
    # 🆕 多输入源支持
    fileUris: Optional[List[str]] = Field(None, description="文件 URI 列表（图片、文档等）")
    voiceText: Optional[str] = Field(None, description="语音转文本内容")


@router.post("/chat", response_model=Dict[str, Any])
async def chat_with_note(request: NoteChatRequest):
    """
    🔥 基于 Note 内容进行对话
    
    这是 "Learn with Sai" 功能的后端接口。
    用户可以基于 note 内容提问，AI 会结合 note 内容回答。
    
    流程：
    1. 先调用 /init-session 获取 noteId
    2. 使用此接口进行对话
    
    请求示例:
    ```json
    {
        "noteId": "evu7r2",
        "message": "Explain the concept of 骨骼肌"
    }
    ```
    
    响应示例:
    ```json
    {
        "code": 0,
        "msg": "success",
        "data": {
            "response": "骨骼肌是一种...",
            "noteId": "evu7r2",
            "sessionId": "note_evu7r2_xxx",
            "noteTitle": "一步到位",
            "chatTurns": 3,
            "generationTime": 1.5
        }
    }
    ```
    
    支持的对话场景：
    - "Explain the concept" - 解释概念
    - "Make it simpler" - 用更简单的方式解释
    - "Common mistakes" - 常见错误
    - 任何关于 note 内容的问题
    """
    start_time = time.time()
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/chat")
    logger.info(f"   • noteId: {request.noteId}")
    logger.info(f"   • message: {request.message[:50]}...")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        result = await service.chat_with_note(
            note_id=request.noteId,
            message=request.message,
            user_id=request.userId or "studyx_user",
            file_uris=request.fileUris,
            voice_text=request.voiceText
        )
        
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "response": result["response"],
                "noteId": result["note_id"],
                "sessionId": result["session_id"],
                "noteTitle": result["note_title"],
                "chatTurns": result["chat_turns"],
                "generationTime": result["generation_time"],
                # 🆕 上下文管理统计
                "contextStats": result.get("context_stats", {}),
                "tokenUsage": result.get("token_usage", {})
            }
        }
        
    except Exception as e:
        logger.error(f"❌ chat_with_note error: {e}", exc_info=True)
        return {
            "code": 500,
            "msg": str(e),
            "data": None
        }


# ============================================================
# 基于 Note 会话的后续操作
# ============================================================

class NoteFlashcardsRequest(BaseModel):
    """基于 noteId 生成更多闪卡"""
    noteId: str = Field(..., description="noteId（从 init-session 获取）")
    cardSetNoteDto: CardSetNoteDtoRequest = Field(..., description="Flashcard 配置")
    token: Optional[str] = Field(None, description="API Token")


@router.post("/flashcards-from-note", response_model=Dict[str, Any])
async def create_flashcards_from_note(request: NoteFlashcardsRequest):
    """
    基于已有的 noteId 生成更多闪卡
    
    先调用 /init-session 获取 noteId，然后使用此接口生成更多闪卡。
    
    请求示例:
    ```json
    {
        "noteId": "xxx",
        "cardSetNoteDto": {
            "outLanguage": "jp",
            "cardCount": 10
        }
    }
    ```
    """
    start_time = time.time()
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/flashcards")
    logger.info(f"   • noteId: {request.noteId}")
    logger.info(f"   • cardSetNoteDto: {request.cardSetNoteDto.dict()}")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        if request.token:
            service = StudyXAgentService(api_token=request.token)
        
        result = await service.create_flashcards_from_note(
            note_id=request.noteId,
            card_set_note_dto=request.cardSetNoteDto.dict()
        )
        
        total_time = time.time() - start_time
        
        return {
            "code": 0,
            "msg": "Flashcards created",
            "data": {
                "noteId": request.noteId,
                "flashcards": result,
                "timing": {"totalTime": round(total_time, 2)}
            }
        }
        
    except Exception as e:
        logger.error(f"❌ create_flashcards error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


class NoteQuizRequest(BaseModel):
    """基于 noteId 生成测验"""
    noteId: str = Field(..., description="noteId（从 init-session 获取）")
    quizSetNoteDto: QuizSetNoteDtoRequest = Field(..., description="Quiz 配置")
    token: Optional[str] = Field(None, description="API Token")


@router.post("/quiz-from-note", response_model=Dict[str, Any])
async def create_quiz_from_note(request: NoteQuizRequest):
    """
    基于已有的 noteId 生成测验
    
    先调用 /init-session 获取 noteId，然后使用此接口生成测验。
    
    请求示例:
    ```json
    {
        "noteId": "xxx",
        "quizSetNoteDto": {
            "outLanguage": "cn",
            "quizCount": 5
        }
    }
    ```
    """
    start_time = time.time()
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/quiz")
    logger.info(f"   • noteId: {request.noteId}")
    logger.info(f"   • quizSetNoteDto: {request.quizSetNoteDto.dict()}")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        if request.token:
            service = StudyXAgentService(api_token=request.token)
        
        result = await service.create_quiz_from_note(
            note_id=request.noteId,
            quiz_set_note_dto=request.quizSetNoteDto.dict()
        )
        
        total_time = time.time() - start_time
        
        return {
            "code": 0,
            "msg": "Quiz created",
            "data": {
                "noteId": request.noteId,
                "quiz": result,
                "timing": {"totalTime": round(total_time, 2)}
            }
        }
        
    except Exception as e:
        logger.error(f"❌ create_quiz error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


# ============================================================
# 获取 Note 会话信息
# ============================================================

@router.get("/session/{note_id}", response_model=Dict[str, Any])
async def get_note_session(note_id: str):
    """
    获取 Note 会话信息
    
    返回已初始化的 Note 会话的详细信息，包括：
    - note 内容
    - 已生成的 flashcards
    - 已生成的 quiz
    """
    service = get_studyx_agent_service()
    note_session = service.get_note_session(note_id)
    
    if not note_session:
        return {
            "code": 404,
            "msg": f"Note session not found: {note_id}",
            "data": None
        }
    
    return {
        "code": 0,
        "msg": "Session found",
        "data": {
            "noteId": note_session.note_id,
            "sessionId": note_session.session_id,
            "noteTitle": note_session.note_title,
            "noteContentLength": len(note_session.note_content),
            "noteContentPreview": note_session.note_content[:500] + "..." if len(note_session.note_content) > 500 else note_session.note_content,
            "libraryCourseId": note_session.library_course_id,
            "contentUrls": note_session.content_urls,
            "createdAt": note_session.created_at.isoformat(),
            "hasFlashcards": note_session.flashcards is not None,
            "hasQuiz": note_session.quiz is not None
        }
    }


# ============================================================
# 兼容旧版 API
# ============================================================

class CreateAllRequest(BaseModel):
    """创建 Flashcards + Quiz 的完整请求"""
    libraryCourseId: Optional[str] = Field(None, description="课程库 ID")
    noteTitle: Optional[str] = Field(None, description="笔记标题")
    contentList: Optional[List[ContentItem]] = Field(None, description="内容列表")
    flashcardLanguage: Optional[str] = Field(None, description="闪卡输出语言")
    flashcardCount: Optional[int] = Field(None, description="闪卡数量")
    flashcardTags: Optional[str] = Field(None, description="闪卡标签")
    flashcardIsPublic: int = Field(1, description="闪卡是否公开")
    quizLanguage: Optional[str] = Field(None, description="测验输出语言")
    quizCount: Optional[int] = Field(None, description="测验题目数量")
    quizTags: Optional[str] = Field(None, description="测验标签")
    quizIsPublic: int = Field(1, description="测验是否公开")
    createFlashcards: bool = Field(True, description="是否创建闪卡")
    createQuiz: bool = Field(True, description="是否创建测验")
    token: Optional[str] = Field(None, description="API Token")


class CreateFlashcardsRequest(BaseModel):
    """只创建 Flashcards 的请求"""
    libraryCourseId: Optional[str] = Field(None, description="课程库 ID")
    noteTitle: Optional[str] = Field(None, description="笔记标题")
    contentList: Optional[List[ContentItem]] = Field(None, description="内容列表")
    language: Optional[str] = Field(None, description="输出语言")
    count: Optional[int] = Field(None, description="闪卡数量")
    tags: Optional[str] = Field(None, description="标签")
    token: Optional[str] = Field(None, description="API Token")


class CreateQuizRequest(BaseModel):
    """基于 noteId 创建 Quiz 的请求"""
    noteId: str = Field(..., description="已有的 noteId")
    libraryCourseId: Optional[str] = Field(None, description="课程库 ID")
    language: Optional[str] = Field(None, description="输出语言")
    count: Optional[int] = Field(None, description="题目数量")
    tags: Optional[str] = Field(None, description="标签")
    token: Optional[str] = Field(None, description="API Token")


@router.post("/create-all", response_model=Dict[str, Any])
async def create_flashcards_and_quiz(request: CreateAllRequest):
    """
    创建 Flashcards + Quiz 完整流程（兼容旧版）
    
    推荐使用新的 /init-session API
    """
    start_time = time.time()
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/create-all")
    logger.info(f"   • Note Title: {request.noteTitle or 'default'}")
    logger.info(f"   • Flashcard: lang={request.flashcardLanguage}, count={request.flashcardCount}")
    logger.info(f"   • Quiz: lang={request.quizLanguage}, count={request.quizCount}")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        if request.token:
            service = StudyXAgentService(api_token=request.token)
        
        content_list = None
        if request.contentList:
            content_list = [
                {"content": item.content, "contentSize": item.contentSize}
                for item in request.contentList
            ]
        
        result = await service.create_flashcards_and_quiz(
            library_course_id=request.libraryCourseId,
            note_title=request.noteTitle,
            content_list=content_list,
            flashcard_language=request.flashcardLanguage,
            flashcard_count=request.flashcardCount,
            flashcard_tags=request.flashcardTags,
            flashcard_is_public=request.flashcardIsPublic,
            quiz_language=request.quizLanguage,
            quiz_count=request.quizCount,
            quiz_tags=request.quizTags,
            quiz_is_public=request.quizIsPublic,
            create_flashcards=request.createFlashcards,
            create_quiz=request.createQuiz
        )
        
        total_time = time.time() - start_time
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "data": {
                "noteId": result.get("note_id"),
                "noteContentLength": len(result.get("note_content", "") or ""),
                "flashcards": result.get("flashcards"),
                "quiz": result.get("quiz"),
                "quizError": result.get("quiz_error"),
                "timing": {"totalTime": round(total_time, 2)}
            }
        }
        
    except Exception as e:
        logger.error(f"❌ create_flashcards_and_quiz error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


@router.post("/create-flashcards", response_model=Dict[str, Any])
async def create_flashcards_only(request: CreateFlashcardsRequest):
    """只创建 Flashcards（兼容旧版）"""
    start_time = time.time()
    
    try:
        service = get_studyx_agent_service()
        
        if request.token:
            service = StudyXAgentService(api_token=request.token)
        
        content_list = None
        if request.contentList:
            content_list = [
                {"content": item.content, "contentSize": item.contentSize}
                for item in request.contentList
            ]
        
        result = await service.create_flashcards_only(
            library_course_id=request.libraryCourseId,
            note_title=request.noteTitle,
            content_list=content_list,
            language=request.language,
            count=request.count,
            tags=request.tags
        )
        
        total_time = time.time() - start_time
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "data": {
                "noteId": result.get("note_id"),
                "flashcards": result.get("flashcards"),
                "timing": {"totalTime": round(total_time, 2)}
            }
        }
        
    except Exception as e:
        logger.error(f"❌ create_flashcards_only error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


@router.post("/create-quiz", response_model=Dict[str, Any])
async def create_quiz_only(request: CreateQuizRequest):
    """基于 noteId 创建 Quiz（兼容旧版）"""
    start_time = time.time()
    
    try:
        service = get_studyx_agent_service()
        
        if request.token:
            service = StudyXAgentService(api_token=request.token)
        
        result = await service.create_quiz_only(
            note_id=request.noteId,
            library_course_id=request.libraryCourseId,
            language=request.language,
            count=request.count,
            tags=request.tags
        )
        
        total_time = time.time() - start_time
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "data": {
                "noteId": result.get("note_id"),
                "quiz": result.get("quiz"),
                "timing": {"totalTime": round(total_time, 2)}
            }
        }
        
    except Exception as e:
        logger.error(f"❌ create_quiz_only error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


# ============================================================
# 🔥 本地生成 API（使用 prompts + Gemini）
# ============================================================

class InputItem(BaseModel):
    """输入项（兼容外部 API 格式）"""
    text: str = Field(..., description="用户输入文本")


class LocalGenerateRequest(BaseModel):
    """
    本地生成请求（兼容外部 API 格式）
    
    示例:
    {
        "inputList": [{"text": "我需要光合作用三张卡"}]
    }
    """
    inputList: List[InputItem] = Field(..., description="输入列表")
    noteId: Optional[str] = Field(None, description="关联的 noteId（可选，用于获取参考内容）")
    outputLanguage: Optional[str] = Field("cn", description="输出语言")


@router.post("/flashcard", response_model=Dict[str, Any])
async def create_flashcard(request: LocalGenerateRequest):
    """
    🔥 本地生成闪卡（使用 Gemini + prompts）
    
    兼容外部 API 的输入格式，但使用本地 LLM 生成。
    
    请求示例:
    ```json
    {
        "inputList": [{"text": "我需要光合作用三张卡"}]
    }
    ```
    
    响应格式与外部 API 一致:
    ```json
    {
        "code": 0,
        "msg": "Request succeeded",
        "data": {
            "title": "光合作用",
            "cardList": [
                {"front": "什么是光合作用？", "back": "..."}
            ]
        }
    }
    ```
    """
    start_time = time.time()
    
    # 合并所有输入
    user_request = " ".join([item.text for item in request.inputList])
    
    # 提取数量（尝试从文本中解析）
    import re
    count_match = re.search(r'(\d+)\s*[张道个]', user_request)
    card_count = int(count_match.group(1)) if count_match else 5
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/flashcard")
    logger.info(f"   • userRequest: {user_request}")
    logger.info(f"   • cardCount: {card_count}")
    logger.info(f"   • noteId: {request.noteId}")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        result = await service.generate_flashcards_local(
            user_request=user_request,
            output_language=request.outputLanguage or "cn",
            card_count=card_count,
            note_id=request.noteId
        )
        
        total_time = time.time() - start_time
        
        if result.get("code") == 0:
            # 添加 timing 信息
            result["timing"] = {"totalTime": round(total_time, 2)}
        
        return result
        
    except Exception as e:
        logger.error(f"❌ create_flashcards_local error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


@router.post("/quiz", response_model=Dict[str, Any])
async def create_quiz(request: LocalGenerateRequest):
    """
    🔥 本地生成测验题（使用 Gemini + prompts）
    
    兼容外部 API 的输入格式，但使用本地 LLM 生成。
    
    请求示例:
    ```json
    {
        "inputList": [{"text": "我需要光合作用三道题"}]
    }
    ```
    
    响应格式与外部 API 一致:
    ```json
    {
        "code": 0,
        "msg": "Request succeeded",
        "data": {
            "title": "Photosynthesis Quiz",
            "questions": [
                {
                    "question": "...",
                    "answer_options": [
                        {"text": "...", "rationale": "...", "is_correct": true}
                    ],
                    "hint": "..."
                }
            ]
        }
    }
    ```
    """
    start_time = time.time()
    
    # 合并所有输入
    user_request = " ".join([item.text for item in request.inputList])
    
    # 提取数量（尝试从文本中解析）
    import re
    count_match = re.search(r'(\d+)\s*[张道个]', user_request)
    quiz_count = int(count_match.group(1)) if count_match else 3
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/quiz")
    logger.info(f"   • userRequest: {user_request}")
    logger.info(f"   • quizCount: {quiz_count}")
    logger.info(f"   • noteId: {request.noteId}")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        result = await service.generate_quiz_local(
            user_request=user_request,
            output_language=request.outputLanguage or "cn",
            quiz_count=quiz_count,
            note_id=request.noteId
        )
        
        total_time = time.time() - start_time
        
        if result.get("code") == 0:
            # 添加 timing 信息
            result["timing"] = {"totalTime": round(total_time, 2)}
        
        return result
        
    except Exception as e:
        logger.error(f"❌ create_quiz error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


@router.post("/mindmap", response_model=Dict[str, Any])
async def create_mindmap(request: LocalGenerateRequest):
    """
    🔥 本地生成思维导图（使用 Gemini + prompts）
    
    请求示例:
    ```json
    {
        "inputList": [{"text": "帮我画一个光合作用的思维导图"}]
    }
    ```
    """
    start_time = time.time()
    
    user_request = " ".join([item.text for item in request.inputList])
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/mindmap")
    logger.info(f"   • userRequest: {user_request}")
    logger.info(f"   • noteId: {request.noteId}")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        result = await service.generate_mindmap_local(
            user_request=user_request,
            output_language=request.outputLanguage or "cn",
            note_id=request.noteId
        )
        
        total_time = time.time() - start_time
        
        if result.get("code") == 0:
            result["timing"] = {"totalTime": round(total_time, 2)}
        
        return result
        
    except Exception as e:
        logger.error(f"❌ create_mindmap error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


@router.post("/notes", response_model=Dict[str, Any])
async def create_notes(request: LocalGenerateRequest):
    """
    🔥 本地生成笔记/总结（使用 Gemini + prompts）
    
    请求示例:
    ```json
    {
        "inputList": [{"text": "帮我总结一下光合作用的要点"}]
    }
    ```
    """
    start_time = time.time()
    
    user_request = " ".join([item.text for item in request.inputList])
    
    logger.info("="*60)
    logger.info("📥 POST /api/studyx-agent/notes")
    logger.info(f"   • userRequest: {user_request}")
    logger.info(f"   • noteId: {request.noteId}")
    logger.info("="*60)
    
    try:
        service = get_studyx_agent_service()
        
        result = await service.generate_notes_local(
            user_request=user_request,
            output_language=request.outputLanguage or "cn",
            note_id=request.noteId
        )
        
        total_time = time.time() - start_time
        
        if result.get("code") == 0:
            result["timing"] = {"totalTime": round(total_time, 2)}
        
        return result
        
    except Exception as e:
        logger.error(f"❌ create_notes error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


# ============================================================
# 健康检查
# ============================================================

@router.get("/health", response_model=Dict[str, Any])
async def health_check():
    """健康检查端点"""
    service = get_studyx_agent_service()
    
    return {
        "code": 0,
        "msg": "Service is healthy",
        "data": {
            "service": "StudyX Agent API",
            "version": "2.1.0",  # 🆕 版本升级
            "mode": "local_generation",  # 🆕 标记本地生成模式
            "api_url": service.api_url,
            "default_library_course_id": service.DEFAULT_LIBRARY_COURSE_ID,
            "active_sessions": len(service._note_sessions),
            "timestamp": datetime.now().isoformat()
        }
    }
