"""
External Web API - Web 专用聊天接口（SSE 流式 + Edit/Regenerate）

与 /api/external/chat (App端) 共享相同的核心功能：
- Intent Router（意图识别）
- Skill Orchestrator（技能执行）
- Memory Manager（上下文管理）
- MD 持久化

Web 端专属功能：
- SSE 流式输出
- Edit/Regenerate 支持（保留历史版本）
- Clear Session 支持
- 并发安全（per-session 锁）

端点:
- POST /api/external/chat/web - 流式聊天（支持所有 Skill）
- POST /api/external/chat/web/clear - 清除会话
- GET /api/external/chat/web/versions - 获取历史版本
- GET /api/external/chat/web/status - 获取会话状态
"""
import logging
import asyncio
import json
import time
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator, Literal
from fastapi import APIRouter, HTTPException, Depends, Header, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from enum import Enum

from app.core import SkillOrchestrator, MemoryManager
from app.core.intent_router import IntentRouter
from app.core.request_context import set_user_api_token, clear_user_api_token
from app.dependencies import get_memory_manager
from app.services.gemini import GeminiClient
from app.config import settings

# 🔥 复用 external.py 的核心功能
from app.api.external import (
    execute_skill_pipeline,
    get_skill_orchestrator,
    get_user_language_from_studyx,
    fetch_question_context_from_studyx,  # 🆕 获取题目上下文
    _load_conversation_history,
    _save_chat_to_session,
    _convert_to_text_format,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/external/chat/web", tags=["external-web"])


# ============= 🔒 并发控制 =============

_session_locks: Dict[str, asyncio.Lock] = {}
_lock_manager_lock = asyncio.Lock()


async def get_session_lock(session_id: str) -> asyncio.Lock:
    """获取或创建 session 级别的锁"""
    async with _lock_manager_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = asyncio.Lock()
        return _session_locks[session_id]


# ============= 请求/响应模型 =============

class ActionType(str, Enum):
    SEND = "send"
    EDIT = "edit"
    REGENERATE = "regenerate"


class FileInfo(BaseModel):
    type: Literal["image", "document"] = Field(..., description="文件类型")
    url: Optional[str] = Field(None, description="图片 HTTP URL")
    name: Optional[str] = Field(None, description="文档文件名")


class WebChatRequest(BaseModel):
    message: str = Field("", description="用户消息")
    user_id: str = Field(..., description="用户 ID")
    question_id: str = Field(..., description="题目 ID (aiQuestionId)")
    answer_id: str = Field(..., description="答案 ID (answerId)")
    
    # Web 专用参数
    action: ActionType = Field(ActionType.SEND, description="操作类型: send/edit/regenerate")
    turn_id: Optional[int] = Field(None, description="Edit/Regenerate 时指定的轮次号")
    
    # 通用参数（与 App 端一致）
    file_uri: Optional[str] = Field(None, description="单个 GCS 文件 URI")
    file_uris: Optional[List[str]] = Field(None, description="多个 GCS 文件 URI")
    files: Optional[List[FileInfo]] = Field(None, description="文件信息数组")
    referenced_text: Optional[str] = Field(None, description="引用的文本内容")
    action_type: Optional[str] = Field(None, description="快捷操作: explain_concept, make_simpler, common_mistakes")
    language: Optional[str] = Field(None, description="回复语言")
    # 🆕 题目上下文支持（与 App 端一致）
    qid: Optional[str] = Field(None, description="题目 slug（从 URL 获取，如 96rhhg4），用于自动获取题目上下文")
    resource_id: Optional[str] = Field(None, description="题目资源 ID（与 qid 作用相同，前端可用此字段）")  # 🆕 兼容前端字段名
    question_context: Optional[str] = Field(None, description="题目上下文文本（前端直接传入时优先使用）")


class ClearSessionRequest(BaseModel):
    user_id: str = Field(..., description="用户 ID")
    question_id: str = Field(..., description="题目 ID")
    answer_id: str = Field(..., description="答案 ID")


# ============= SSE 流式生成 =============

async def generate_sse_stream(
    message: str,
    user_id: str,
    session_id: str,
    action: ActionType,
    turn_id: Optional[int],
    orchestrator: SkillOrchestrator,
    file_uris: Optional[List[str]] = None,
    files: Optional[List[Dict]] = None,
    referenced_text: Optional[str] = None,
    action_type_hint: Optional[str] = None,
    language: str = "en",
    # 🆕 题目上下文
    qid: Optional[str] = None,
    question_context: Optional[str] = None,
    token: Optional[str] = None,
    environment: str = "test"  # 🆕 环境标识
) -> AsyncGenerator[str, None]:
    """
    生成 SSE 事件流（使用完整的 Skill Pipeline）
    
    Events:
    - start: 开始生成
    - intent: 意图识别结果
    - chunk: 内容块（流式输出）
    - done: 完成，返回完整响应
    - error: 错误
    """
    start_time = time.time()
    
    try:
        # 1. 发送开始事件
        yield f"data: {json.dumps({'type': 'start', 'action': action.value, 'turn_id': turn_id, 'timestamp': datetime.now().isoformat()})}\n\n"
        
        # 2. 处理 Edit/Regenerate
        if action == ActionType.EDIT:
            if not turn_id:
                yield f"data: {json.dumps({'type': 'error', 'message': 'turn_id is required for edit action'})}\n\n"
                return
            
            # 截断并保存版本
            await _truncate_and_save_version(
                orchestrator.memory_manager,
                user_id,
                session_id,
                turn_id,
                action="edit",
                new_message=message
            )
            
        elif action == ActionType.REGENERATE:
            if not turn_id:
                # 🆕 没有 turn_id 时，转换为 send action
                logger.info(f"⚠️ Regenerate without turn_id, converting to send action")
                action = ActionType.SEND
            else:
                # 获取原始消息
                original_message = await _get_turn_message(
                    orchestrator.memory_manager,
                    user_id,
                    session_id,
                    turn_id
                )
                
                if not original_message:
                    # 🆕 找不到历史消息时，使用传入的 message 作为新消息（转换为 send）
                    logger.info(f"⚠️ Turn {turn_id} not found, converting to send action with message: {message[:50]}...")
                    action = ActionType.SEND
                else:
                    message = original_message
                    
                    # 截断并保存版本
                    await _truncate_and_save_version(
                        orchestrator.memory_manager,
                        user_id,
                        session_id,
                        turn_id,
                        action="regenerate"
                    )
        
        # 2.5 🆕 处理题目上下文
        # 每次快捷问答都应该基于题目上下文，不仅限于新 session
        final_question_context = question_context
        logger.info(f"📚 Question context check: qid={qid}, token={'present' if token else 'missing'}, existing_context={'yes' if question_context else 'no'}")
        
        if not final_question_context and qid:
            if token:
                logger.info(f"📚 Fetching question context from StudyX (qid={qid}, env={environment})...")
                final_question_context = await fetch_question_context_from_studyx(qid, token, environment)
                if final_question_context:
                    logger.info(f"✅ Question context fetched: {len(final_question_context)} chars")
                else:
                    logger.warning(f"⚠️ Failed to fetch question context for qid={qid}")
            else:
                logger.warning(f"⚠️ Cannot fetch question context: token is missing (qid={qid})")
        
        # 3. 🔥 调用完整的 Skill Pipeline（与 App 端一致）
        result = await execute_skill_pipeline(
            message=message,
            user_id=user_id,
            session_id=session_id,
            orchestrator=orchestrator,
            quantity_override=None,
            skill_hint=None,
            file_uris=file_uris,
            referenced_text=referenced_text,
            action_type=action_type_hint,
            files=files,
            language=language,
            question_context=final_question_context  # 🆕 传递题目上下文
        )
        
        # 4. 发送意图识别结果
        intent = result.get("intent", "other")
        content_type = result.get("content_type", "text")
        topic = result.get("topic", "")
        
        yield f"data: {json.dumps({'type': 'intent', 'intent': intent, 'content_type': content_type, 'topic': topic})}\n\n"
        
        # 5. 提取内容并流式发送
        content = result.get("content") or result.get("response_content") or {}
        
        # 🆕 根据 content_type 提取文本内容
        text = ""
        if isinstance(content, dict):
            if "text" in content:
                # 普通 chat 响应
                text = content.get("text", "")
            elif "intuition" in content:
                # explain_skill 响应：组合多个字段为完整文本
                parts = []
                if content.get("concept"):
                    parts.append(f"**{content['concept']}**\n")
                if content.get("intuition"):
                    parts.append(f"📚 **直觉理解**\n{content['intuition']}\n")
                if content.get("formal_definition"):
                    parts.append(f"📖 **正式定义**\n{content['formal_definition']}\n")
                if content.get("why_it_matters"):
                    parts.append(f"💡 **为什么重要**\n{content['why_it_matters']}\n")
                # 示例
                examples = content.get("examples", [])
                if examples:
                    parts.append("🌟 **实例**\n")
                    for i, ex in enumerate(examples, 1):
                        if isinstance(ex, dict):
                            parts.append(f"{i}. **{ex.get('example', '')}**\n   {ex.get('explanation', '')}\n")
                # 常见误区
                mistakes = content.get("common_mistakes", [])
                if mistakes:
                    parts.append("⚠️ **常见误区**\n")
                    for i, m in enumerate(mistakes, 1):
                        if isinstance(m, dict):
                            parts.append(f"{i}. ❌ {m.get('mistake', '')}\n   ✅ {m.get('correction', '')}\n")
                # 相关概念
                related = content.get("related_concepts", [])
                if related:
                    parts.append(f"🔗 **相关概念**: {', '.join(related)}\n")
                text = "\n".join(parts)
            elif "flashcards" in content:
                # flashcard_skill 响应
                flashcards = content.get("flashcards", [])
                parts = [f"📚 已生成 {len(flashcards)} 张闪卡\n"]
                for i, card in enumerate(flashcards[:5], 1):  # 最多显示5张
                    if isinstance(card, dict):
                        front = card.get("front", card.get("question", ""))
                        back = card.get("back", card.get("answer", ""))
                        parts.append(f"\n**卡片 {i}**\n🔹 正面: {front}\n🔸 背面: {back}\n")
                if len(flashcards) > 5:
                    parts.append(f"\n... 还有 {len(flashcards) - 5} 张卡片")
                text = "\n".join(parts)
            elif "questions" in content:
                # quiz_skill 响应
                questions = content.get("questions", [])
                parts = [f"📝 已生成 {len(questions)} 道练习题\n"]
                for i, q in enumerate(questions[:3], 1):  # 最多显示3题
                    if isinstance(q, dict):
                        q_text = q.get("question", q.get("text", ""))
                        parts.append(f"\n**题目 {i}**: {q_text}\n")
                        options = q.get("options", [])
                        if options:
                            for opt in options:
                                if isinstance(opt, dict):
                                    parts.append(f"   {opt.get('label', '')}) {opt.get('text', '')}\n")
                if len(questions) > 3:
                    parts.append(f"\n... 还有 {len(questions) - 3} 道题目")
                text = "\n".join(parts)
            else:
                # 尝试将整个 content 转为字符串
                text = json.dumps(content, ensure_ascii=False, indent=2)
        elif isinstance(content, str):
            text = content
        else:
            text = str(content) if content else ""
        
        # 流式发送内容（分块）
        if text:
            chunk_size = 50  # 每块字符数
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i+chunk_size]
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
                await asyncio.sleep(0.01)  # 模拟流式效果
        else:
            # 🆕 即使没有文本，也发送一个空 chunk 表示处理完成
            yield f"data: {json.dumps({'type': 'chunk', 'content': '处理完成'})}\n\n"
        
        # 6. 获取实际轮次
        actual_turn_id = await _get_current_turn_count(
            orchestrator.memory_manager,
            user_id,
            session_id
        )
        
        # 7. 发送完成事件
        elapsed_time = time.time() - start_time
        token_usage = result.get("token_usage", {})
        context_stats = result.get("context_stats", {})
        
        yield f"data: {json.dumps({'type': 'done', 'turn_id': actual_turn_id, 'intent': intent, 'content_type': content_type, 'topic': topic, 'full_response': text, 'elapsed_time': round(elapsed_time, 2), 'token_usage': token_usage, 'context_stats': context_stats, 'action': action.value})}\n\n"
        
    except Exception as e:
        logger.error(f"❌ SSE generation error: {e}", exc_info=True)
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


# ============= 版本管理 =============

async def _truncate_and_save_version(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    turn_id: int,
    action: str,
    new_message: Optional[str] = None
) -> bool:
    """截断会话历史并保存版本"""
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        versions_file = artifacts_dir / f"{session_id}_versions.json"
        
        if not md_file.exists():
            logger.warning(f"⚠️ MD file not found: {md_file}")
            return False
        
        content = md_file.read_text(encoding='utf-8')
        
        # 解析 turns
        turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})'
        turns = list(re.finditer(turn_pattern, content))
        
        if not turns:
            return False
        
        # 找到要截断的位置
        truncate_idx = None
        for i, match in enumerate(turns):
            if int(match.group(1)) == turn_id:
                truncate_idx = i
                break
        
        if truncate_idx is None:
            logger.warning(f"⚠️ Turn {turn_id} not found")
            return False
        
        # 提取要保存的版本内容
        truncate_pos = turns[truncate_idx].start()
        version_content = content[truncate_pos:]
        header_content = content[:truncate_pos]
        
        # 加载或创建版本历史
        versions = []
        if versions_file.exists():
            try:
                versions = json.loads(versions_file.read_text(encoding='utf-8'))
            except:
                versions = []
        
        # 保存版本
        versions.append({
            "version_id": len(versions) + 1,
            "action": action,
            "turn_id": turn_id,
            "timestamp": datetime.now().isoformat(),
            "content": version_content,
            "new_message": new_message
        })
        
        versions_file.write_text(json.dumps(versions, ensure_ascii=False, indent=2), encoding='utf-8')
        
        # 截断 MD 文件
        md_file.write_text(header_content, encoding='utf-8')
        
        logger.info(f"✅ Truncated session at turn {turn_id}, saved version {len(versions)}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to truncate and save version: {e}")
        return False


async def _get_turn_message(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    turn_id: int
) -> Optional[str]:
    """获取指定轮次的用户消息"""
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        
        if not md_file.exists():
            return None
        
        content = md_file.read_text(encoding='utf-8')
        
        # 查找 turn 的 JSON 数据
        json_pattern = r'```json\s*\n(\{[^`]+\})\s*\n```'
        matches = list(re.finditer(json_pattern, content, re.DOTALL))
        
        for match in matches:
            try:
                data = json.loads(match.group(1))
                if data.get("turn_number") == turn_id:
                    return data.get("user_query", "")
            except:
                continue
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Failed to get turn message: {e}")
        return None


async def _get_current_turn_count(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str
) -> int:
    """获取当前会话的轮次数"""
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        
        if not md_file.exists():
            return 0
        
        content = md_file.read_text(encoding='utf-8')
        turn_pattern = r'## Turn (\d+)'
        matches = re.findall(turn_pattern, content)
        
        if matches:
            return max(int(m) for m in matches)
        return 0
        
    except:
        return 0


async def _get_chat_tree(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str
) -> Dict[str, Any]:
    """
    获取聊天树结构（包含版本历史）
    
    返回结构：
    {
        "current": [turn1, turn2, ...],
        "versions": [
            {"version_id": 1, "action": "edit", "turn_id": 3, "branches": [turn3_v1, turn4_v1, ...]},
            ...
        ]
    }
    """
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        versions_file = artifacts_dir / f"{session_id}_versions.json"
        
        result = {
            "current": [],
            "versions": []
        }
        
        # 解析当前会话
        if md_file.exists():
            content = md_file.read_text(encoding='utf-8')
            json_pattern = r'```json\s*\n(\{[^`]+\})\s*\n```'
            
            for match in re.finditer(json_pattern, content, re.DOTALL):
                try:
                    data = json.loads(match.group(1))
                    turn_data = {
                        "turn_number": data.get("turn_number"),
                        "timestamp": data.get("timestamp"),
                        "user_query": data.get("user_query"),
                        "intent": data.get("intent", {}).get("intent"),
                        "response_preview": str(data.get("agent_response", {}).get("content", {}).get("text", ""))[:100]
                    }
                    result["current"].append(turn_data)
                except:
                    continue
        
        # 解析版本历史
        if versions_file.exists():
            try:
                versions = json.loads(versions_file.read_text(encoding='utf-8'))
                for v in versions:
                    version_data = {
                        "version_id": v.get("version_id"),
                        "action": v.get("action"),
                        "turn_id": v.get("turn_id"),
                        "timestamp": v.get("timestamp"),
                        "new_message": v.get("new_message"),
                        "branches": []
                    }
                    
                    # 解析版本内的 turns
                    version_content = v.get("content", "")
                    for match in re.finditer(r'```json\s*\n(\{[^`]+\})\s*\n```', version_content, re.DOTALL):
                        try:
                            data = json.loads(match.group(1))
                            branch_turn = {
                                "turn_number": data.get("turn_number"),
                                "user_query": data.get("user_query"),
                                "response_preview": str(data.get("agent_response", {}).get("content", {}).get("text", ""))[:100]
                            }
                            version_data["branches"].append(branch_turn)
                        except:
                            continue
                    
                    result["versions"].append(version_data)
            except:
                pass
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Failed to get chat tree: {e}")
        return {"current": [], "versions": []}


# ============= API 端点 =============

@router.post("", response_class=StreamingResponse)
async def web_chat_stream(
    request: WebChatRequest,
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator),
    token: Optional[str] = Header(None, description="用户认证 Token"),
    environment: Optional[str] = Header("test", description="环境标识 (dev/test/prod)")
):
    """
    🌐 Web 流式聊天接口（SSE）
    
    功能：
    - 完整的 Intent 识别（与 App 端一致）
    - 完整的 Skill 执行（Quiz/Flashcard/Explain/Plan 等）
    - SSE 流式输出
    - Edit/Regenerate 支持
    
    Actions:
    - send: 发送新消息
    - edit: 编辑某轮并重新生成
    - regenerate: 重新生成某轮回复
    """
    # 设置 token
    if token:
        set_user_api_token(token)
    
    try:
        # 构建 session_id（使用数字格式的 question_id）
        session_id = f"q{request.question_id}_a{request.answer_id}"
        
        # 🔧 关键区分：
        # - question_id（数字格式，如 20000003451）：用于 session_id
        # - resource_id / qid（slug 格式，如 96rhh58）：用于获取题目上下文
        # StudyX 的 newQueryQuestionInfo API 需要 slug 格式的 ID
        effective_qid_for_context = request.resource_id or request.qid  # 优先使用 slug 格式
        logger.info(f"   • Question ID: {request.question_id}, QID: {request.qid}, Resource ID: {request.resource_id}")
        logger.info(f"   • QID for context: {effective_qid_for_context or 'N/A (will skip context fetch)'}")
        
        # 日志记录
        logger.info("="*60)
        logger.info(f"📥 [Web] /api/external/chat/web")
        logger.info(f"   • User: {request.user_id}")
        logger.info(f"   • Session: {session_id}")
        logger.info(f"   • Action: {request.action}")
        logger.info(f"   • QID/Resource ID: {effective_qid_for_context or 'N/A'}")
        logger.info("="*60)
        
        # 🆕 环境标识
        env = environment or "test"
        logger.info(f"   • Environment: {env}")
        
        # 获取语言设置
        language = request.language
        if not language and token:
            language = await get_user_language_from_studyx(token, env)
        language = language or "en"
        
        logger.info(f"   • Language: {language}")
        
        # 合并 file_uris
        file_uris = []
        if request.file_uri:
            file_uris.append(request.file_uri)
        if request.file_uris:
            file_uris.extend(request.file_uris)
        
        # 🆕 检查是否有文件上传
        has_files = bool(file_uris or request.files)
        
        # 🆕 同步 App 端逻辑：处理消息
        message = request.message.strip() if request.message else ""
        
        # 场景 A: 快捷按钮模式（action_type）- 不需要输入文字
        if not message and request.action_type:
            # 根据语言设置选择默认提示
            if language in ["zh", "zh-CN", "zh-TW"]:
                action_default_messages = {
                    "explain_concept": "请详细解释这个概念",
                    "make_simpler": "请用更简单的方式解释",
                    "common_mistakes": "这个知识点有哪些常见错误",
                    "step_by_step": "请一步一步解释解题过程",
                    "why_important": "为什么这个知识点很重要",
                }
                default_msg = "请帮我理解这个内容"
            elif language == "ja":
                action_default_messages = {
                    "explain_concept": "この概念を詳しく説明してください",
                    "make_simpler": "もっと簡単に説明してください",
                    "common_mistakes": "このトピックでよくある間違いは何ですか",
                    "step_by_step": "解き方をステップバイステップで説明してください",
                    "why_important": "なぜこの知識点が重要ですか",
                }
                default_msg = "この内容を理解するのを手伝ってください"
            elif language == "ko":
                action_default_messages = {
                    "explain_concept": "이 개념을 자세히 설명해 주세요",
                    "make_simpler": "더 간단하게 설명해 주세요",
                    "common_mistakes": "이 주제에서 흔히 하는 실수는 무엇인가요",
                    "step_by_step": "풀이 과정을 단계별로 설명해 주세요",
                    "why_important": "왜 이 지식이 중요한가요",
                }
                default_msg = "이 내용을 이해하는 데 도움을 주세요"
            else:
                action_default_messages = {
                    "explain_concept": "Please explain this concept in detail",
                    "make_simpler": "Please explain this in a simpler way",
                    "common_mistakes": "What are the common mistakes for this topic",
                    "step_by_step": "Please explain the solution step by step",
                    "why_important": "Why is this concept important",
                }
                default_msg = "Please help me understand this content"
            message = action_default_messages.get(request.action_type, default_msg)
            logger.info(f"   • 🎯 Action Type: {request.action_type} -> Default message: {message}")
        
        # 场景 B: 文件上传模式（图片/文档）- 不需要输入文字
        if not message and has_files:
            if language in ["zh", "zh-CN", "zh-TW"]:
                message = "请帮我分析这个图片/文件的内容"
            elif language == "ja":
                message = "この画像/ファイルの内容を分析してください"
            elif language == "ko":
                message = "이 이미지/파일의 내용을 분석해 주세요"
            else:
                message = "Please help me analyze this image/file"
            logger.info(f"   • 📎 File upload without message, using default: {message}")
        
        # 转换 files
        files = None
        if request.files:
            files = [f.model_dump() for f in request.files]
        
        # 🔒 获取 session 锁
        lock = await get_session_lock(session_id)
        
        async def locked_generator():
            """带锁的生成器"""
            async with lock:
                logger.info(f"🔒 [Web] Acquired lock for session: {session_id}")
                async for event in generate_sse_stream(
                    message=message,  # 🆕 使用处理后的 message（支持快捷按钮/文件上传默认消息）
                    user_id=request.user_id,
                    session_id=session_id,
                    action=request.action,
                    turn_id=request.turn_id,
                    orchestrator=orchestrator,
                    file_uris=file_uris if file_uris else None,
                    files=files,
                    referenced_text=request.referenced_text,
                    action_type_hint=request.action_type,
                    language=language,
                    # 🔧 使用 slug 格式的 qid 获取题目上下文（resource_id 或 qid）
                    qid=effective_qid_for_context,
                    question_context=request.question_context,
                    token=token,
                    environment=env  # 🆕 环境标识
                ):
                    yield event
                logger.info(f"🔓 [Web] Released lock for session: {session_id}")
        
        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ Web chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        clear_user_api_token()


@router.post("/clear")
async def clear_session(
    request: ClearSessionRequest,
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
):
    """
    🗑️ 清除当前题目的会话
    
    会将当前会话归档，并为用户创建新的空白会话。
    """
    from pathlib import Path
    import shutil
    
    session_id = f"q{request.question_id}_a{request.answer_id}"
    
    lock = await get_session_lock(session_id)
    
    async with lock:
        try:
            artifacts_dir = orchestrator.memory_manager.artifact_storage.base_dir / request.user_id
            md_file = artifacts_dir / f"{session_id}.md"
            versions_file = artifacts_dir / f"{session_id}_versions.json"
            
            previous_turns = 0
            
            if md_file.exists():
                content = md_file.read_text(encoding='utf-8')
                turn_pattern = r'## Turn (\d+)'
                matches = re.findall(turn_pattern, content)
                previous_turns = len(matches)
                
                # 归档旧文件
                archive_name = f"{session_id}_archived_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                archive_file = artifacts_dir / archive_name
                shutil.move(str(md_file), str(archive_file))
                logger.info(f"📦 Archived session to: {archive_file}")
                
                # 归档版本文件
                if versions_file.exists():
                    archive_versions = artifacts_dir / f"{session_id}_archived_{datetime.now().strftime('%Y%m%d_%H%M%S')}_versions.json"
                    shutil.move(str(versions_file), str(archive_versions))
            
            return {
                "code": 0,
                "msg": "Session cleared successfully",
                "data": {
                    "session_id": session_id,
                    "previous_turns": previous_turns,
                    "archived": True,
                    "new_session_ready": True
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to clear session: {e}")
            return {
                "code": 500,
                "msg": f"Failed to clear session: {str(e)}",
                "data": None
            }


@router.get("/versions")
async def get_turn_versions(
    user_id: str = Query(..., description="用户 ID"),
    question_id: str = Query(..., description="题目 ID"),
    answer_id: str = Query(..., description="答案 ID"),
    turn_id: Optional[int] = Query(None, description="指定轮次（不传则返回所有版本）"),
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
):
    """
    📜 获取 Edit/Regenerate 的历史版本
    """
    session_id = f"q{question_id}_a{answer_id}"
    
    try:
        artifacts_dir = orchestrator.memory_manager.artifact_storage.base_dir / user_id
        versions_file = artifacts_dir / f"{session_id}_versions.json"
        
        if not versions_file.exists():
            return {
                "code": 0,
                "msg": "No versions found",
                "data": {
                    "session_id": session_id,
                    "versions": []
                }
            }
        
        versions = json.loads(versions_file.read_text(encoding='utf-8'))
        
        if turn_id is not None:
            versions = [v for v in versions if v.get("turn_id") == turn_id]
        
        return {
            "code": 0,
            "msg": "Success",
            "data": {
                "session_id": session_id,
                "total_versions": len(versions),
                "versions": versions
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get versions: {e}")
        return {
            "code": 500,
            "msg": f"Failed to get versions: {str(e)}",
            "data": None
        }


@router.get("/status")
async def get_session_status(
    user_id: str = Query(..., description="用户 ID"),
    question_id: str = Query(..., description="题目 ID"),
    answer_id: str = Query(..., description="答案 ID"),
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
):
    """
    📊 获取会话状态
    """
    session_id = f"q{question_id}_a{answer_id}"
    
    try:
        lock = _session_locks.get(session_id)
        is_locked = lock.locked() if lock else False
        
        turn_count = await _get_current_turn_count(
            orchestrator.memory_manager,
            user_id,
            session_id
        )
        
        artifacts_dir = orchestrator.memory_manager.artifact_storage.base_dir / user_id
        versions_file = artifacts_dir / f"{session_id}_versions.json"
        version_count = 0
        if versions_file.exists():
            try:
                versions = json.loads(versions_file.read_text(encoding='utf-8'))
                version_count = len(versions)
            except:
                pass
        
        return {
            "code": 0,
            "msg": "Success",
            "data": {
                "session_id": session_id,
                "turn_count": turn_count,
                "version_count": version_count,
                "is_processing": is_locked,
                "exists": turn_count > 0
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get session status: {e}")
        return {
            "code": 500,
            "msg": f"Failed: {str(e)}",
            "data": None
        }


@router.get("/tree")
async def get_chat_tree(
    user_id: str = Query(..., description="用户 ID"),
    question_id: str = Query(..., description="题目 ID"),
    answer_id: str = Query(..., description="答案 ID"),
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
):
    """
    🌳 获取聊天树结构（包含版本历史分支）
    
    返回当前会话和所有历史版本分支，支持前端展示"查看其他版本"功能。
    """
    session_id = f"q{question_id}_a{answer_id}"
    
    try:
        tree = await _get_chat_tree(
            orchestrator.memory_manager,
            user_id,
            session_id
        )
        
        return {
            "code": 0,
            "msg": "Success",
            "data": {
                "session_id": session_id,
                "current_turns": len(tree.get("current", [])),
                "version_count": len(tree.get("versions", [])),
                "tree": tree
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get chat tree: {e}")
        return {
            "code": 500,
            "msg": f"Failed: {str(e)}",
            "data": None
        }


# ============= 🆕 会话列表接口 =============

@router.get("/sessions")
async def get_user_sessions(
    user_id: str = Query(..., description="用户 ID"),
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=50, description="每页数量"),
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
):
    """
    📋 获取用户的会话列表
    
    返回用户所有的聊天会话，包含 session_id、创建时间、轮次数等信息。
    """
    from pathlib import Path
    import os
    
    try:
        # 查找用户目录
        artifacts_dir = Path("artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("backend/artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("/root/usr/skill_agent_demo/backend/artifacts")
        
        user_dir = artifacts_dir / user_id
        
        if not user_dir.exists():
            return {
                "code": 0,
                "msg": "No sessions found",
                "data": {
                    "user_id": user_id,
                    "sessions": [],
                    "total": 0,
                    "page": page,
                    "limit": limit
                }
            }
        
        # 获取所有 .md 文件（排除 _versions.json）
        md_files = list(user_dir.glob("*.md"))
        
        sessions = []
        for md_file in md_files:
            session_id = md_file.stem
            
            # 解析 session_id 获取 question_id 和 answer_id
            question_id = None
            answer_id = None
            if session_id.startswith("q") and "_a" in session_id:
                parts = session_id.split("_a")
                question_id = parts[0][1:]  # 去掉前缀 'q'
                answer_id = parts[1] if len(parts) > 1 else None
            
            # 获取文件信息
            stat = md_file.stat()
            
            # 读取文件获取 turn_count
            turn_count = 0
            first_timestamp = None
            try:
                content = md_file.read_text()
                turn_count = content.count("## Turn ")
                
                # 提取第一个时间戳
                import re
                timestamp_match = re.search(r'## Turn \d+ - (\d{2}:\d{2}:\d{2})', content)
                if timestamp_match:
                    first_timestamp = timestamp_match.group(1)
            except:
                pass
            
            sessions.append({
                "session_id": session_id,
                "question_id": question_id,
                "answer_id": answer_id,
                "turn_count": turn_count,
                "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "first_timestamp": first_timestamp
            })
        
        # 按更新时间排序（最新的在前）
        sessions.sort(key=lambda x: x["updated_at"], reverse=True)
        
        # 分页
        total = len(sessions)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_sessions = sessions[start_idx:end_idx]
        
        return {
            "code": 0,
            "msg": "Success",
            "data": {
                "user_id": user_id,
                "sessions": paginated_sessions,
                "total": total,
                "page": page,
                "limit": limit,
                "has_more": end_idx < total
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get user sessions: {e}")
        return {
            "code": 500,
            "msg": f"Failed: {str(e)}",
            "data": None
        }


@router.get("/history")
async def get_chat_history(
    question_id: str = Query(..., alias="aiQuestionId", description="题目 ID"),
    answer_id: str = Query(..., alias="answerId", description="答案 ID"),
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
):
    """
    📜 获取单个会话的聊天历史
    
    与 App 端 /api/external/chat/history 功能一致，提供 Web 端路径。
    """
    from pathlib import Path
    import re
    
    session_id = f"q{question_id}_a{answer_id}"
    
    try:
        # 查找 MD 文件
        artifacts_dir = Path("artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("backend/artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("/root/usr/skill_agent_demo/backend/artifacts")
        
        # 搜索所有用户目录，找最近修改的文件
        md_file = None
        user_id = None
        latest_mtime = 0
        
        for user_dir in artifacts_dir.iterdir():
            if user_dir.is_dir():
                potential_file = user_dir / f"{session_id}.md"
                if potential_file.exists():
                    # 🆕 选择最近修改的文件
                    mtime = potential_file.stat().st_mtime
                    if mtime > latest_mtime:
                        latest_mtime = mtime
                        md_file = potential_file
                        user_id = user_dir.name
        
        if md_file:
            logger.info(f"📄 Found session file: {md_file} (user={user_id})")
        
        if not md_file:
            return {
                "code": 0,
                "msg": "No chat history found",
                "data": {
                    "question_id": question_id,
                    "answer_id": answer_id,
                    "session_id": session_id,
                    "chat_list": [],
                    "total": 0
                }
            }
        
        # 解析 MD 文件
        content = md_file.read_text()
        chat_list = []
        
        # 匹配每个 Turn
        turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})\n\n### 👤 User Query\n(.*?)\n\n### 🤖 Agent Response\n\*\*Type\*\*: (\w+)'
        
        # 简化匹配 - 按 Turn 分割
        turns = content.split("## Turn ")[1:]  # 跳过第一个空元素
        
        for turn_text in turns:
            try:
                # 提取 turn number 和 timestamp
                header_match = re.match(r'(\d+) - (\d{2}:\d{2}:\d{2})', turn_text)
                if not header_match:
                    continue
                
                turn_num = int(header_match.group(1))
                timestamp = header_match.group(2)
                
                # 提取用户消息
                user_match = re.search(r'### 👤 User Query\n(.*?)\n\n### 🤖', turn_text, re.DOTALL)
                user_message = user_match.group(1).strip() if user_match else ""
                
                # 提取 assistant 消息（从 JSON 块中解析）
                assistant_message = ""
                
                # 方法1: 尝试从 JSON 代码块中解析 text 字段（简单 chat）
                json_block_match = re.search(r'```json\s*\n(\{[\s\S]*?\})\s*\n```', turn_text)
                if json_block_match:
                    try:
                        json_content = json.loads(json_block_match.group(1))
                        if isinstance(json_content, dict) and "text" in json_content:
                            assistant_message = json_content["text"]
                    except json.JSONDecodeError:
                        pass
                
                # 🆕 方法2: 从 details 块中的 JSON 解析（结构化数据）
                if not assistant_message:
                    details_match = re.search(r'<details>[\s\S]*?```json\s*\n(\{[\s\S]+?\n\})\s*\n```', turn_text)
                    if details_match:
                        try:
                            structured_json = json.loads(details_match.group(1))
                            agent_resp = structured_json.get("agent_response", {})
                            content = agent_resp.get("content", {})
                            
                            if isinstance(content, dict):
                                if "text" in content:
                                    # 普通 chat 响应
                                    assistant_message = content["text"]
                                elif "intuition" in content:
                                    # explain_skill 响应：组合多个字段
                                    parts = []
                                    if content.get("concept"):
                                        parts.append(f"**{content['concept']}**\n")
                                    if content.get("intuition"):
                                        parts.append(f"📚 **直觉理解**: {content['intuition']}\n")
                                    if content.get("formal_definition"):
                                        parts.append(f"📖 **正式定义**: {content['formal_definition']}\n")
                                    if content.get("why_it_matters"):
                                        parts.append(f"💡 **为什么重要**: {content['why_it_matters']}\n")
                                    # 添加示例（最多2个）
                                    examples = content.get("examples", [])
                                    if examples:
                                        parts.append("🌟 **实例**:\n")
                                        for i, ex in enumerate(examples[:2], 1):
                                            if isinstance(ex, dict):
                                                parts.append(f"  {i}. {ex.get('example', '')}: {ex.get('explanation', '')}\n")
                                    assistant_message = "\n".join(parts)
                                elif "flashcards" in content:
                                    # flashcard_skill 响应
                                    flashcards = content.get("flashcards", [])
                                    assistant_message = f"已生成 {len(flashcards)} 张闪卡"
                                    if flashcards and isinstance(flashcards[0], dict):
                                        first_card = flashcards[0]
                                        front = first_card.get("front", first_card.get("question", ""))
                                        assistant_message += f"\n\n**第1张**: {front[:100]}..."
                                elif "questions" in content:
                                    # quiz_skill 响应
                                    questions = content.get("questions", [])
                                    assistant_message = f"已生成 {len(questions)} 道练习题"
                                    if questions and isinstance(questions[0], dict):
                                        first_q = questions[0]
                                        q_text = first_q.get("question", first_q.get("text", ""))
                                        assistant_message += f"\n\n**第1题**: {q_text[:100]}..."
                        except json.JSONDecodeError:
                            pass
                
                # 方法3: 使用改进的正则（支持转义字符）
                if not assistant_message:
                    text_match = re.search(r'"text":\s*"((?:[^"\\]|\\.)*)"', turn_text)
                    if text_match:
                        assistant_message = text_match.group(1)
                        # 只处理常见的 JSON 转义字符，保留 LaTeX 反斜杠
                        assistant_message = assistant_message.replace('\\n', '\n').replace('\\r', '\r').replace('\\"', '"')
                
                # 方法4: 提取 直觉理解（markdown 格式的 explain_skill）
                if not assistant_message:
                    intuition_match = re.search(r'#### 📚 直觉理解\s*\n(.+?)(?=\n####|\n##|\Z)', turn_text, re.DOTALL)
                    if intuition_match:
                        assistant_message = intuition_match.group(1).strip()
                
                # 方法5: 取前 500 字符作为摘要
                if not assistant_message:
                    # 从 Agent Response 之后开始提取
                    response_match = re.search(r'### 🤖 Agent Response\s*\n(.*)', turn_text, re.DOTALL)
                    if response_match:
                        assistant_message = response_match.group(1)[:500].replace('\n', ' ')
                
                # 提取 referenced_text
                referenced_text = None
                ref_match = re.search(r'"referenced_text":\s*"([^"]*)"', turn_text)
                if ref_match and ref_match.group(1):
                    referenced_text = ref_match.group(1)
                
                # 提取 feedback
                feedback = None
                feedback_match = re.search(r'"feedback":\s*(\{[^}]+\}|null)', turn_text)
                if feedback_match and feedback_match.group(1) != "null":
                    try:
                        feedback = json.loads(feedback_match.group(1))
                    except:
                        pass
                
                chat_list.append({
                    "turn": turn_num,
                    "timestamp": timestamp,
                    "user_message": user_message,
                    "assistant_message": assistant_message,
                    "referenced_text": referenced_text,
                    "files": None,
                    "feedback": feedback
                })
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to parse turn: {e}")
                continue
        
        return {
            "code": 0,
            "msg": "Success",
            "data": {
                "question_id": question_id,
                "answer_id": answer_id,
                "session_id": session_id,
                "user_id": user_id,
                "chat_list": chat_list,
                "total": len(chat_list)
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get chat history: {e}")
        return {
            "code": 500,
            "msg": f"Failed: {str(e)}",
            "data": None
        }


# ============= 🆕 StudyX 兼容接口 =============
# 这些接口兼容 StudyX 原生格式，方便前端调用

# 创建 StudyX 兼容路由
studyx_router = APIRouter(prefix="/api/studyx/v5/cloud/chat", tags=["studyx-compat"])


async def generate_studyx_sse_stream(
    message: str,
    user_id: str,
    session_id: str,
    msg_id: str,
    orchestrator: SkillOrchestrator,
    language: str = "en",
    file_uris: Optional[List[str]] = None,
    files: Optional[List[Dict]] = None,
    referenced_text: Optional[str] = None,
    action_type_hint: Optional[str] = None,
    qid: Optional[str] = None,
    token: Optional[str] = None,
    environment: str = "test"  # 🆕 环境标识
) -> AsyncGenerator[str, None]:
    """
    🔄 生成 StudyX 兼容格式的 SSE 事件流
    
    格式：
    data: {"code":0,"msg":"Request succeeded","data":{"contents":[{"content":"xxx","contentType":"text","role":"assistant"}],"msgId":"xxx","sessionId":"xxx"}}
    """
    import uuid
    
    # 生成唯一的 sessionId
    studyx_session_id = str(uuid.uuid4().int)[:19]  # 模拟 StudyX 的 sessionId 格式
    
    def make_chunk_event(content: str) -> str:
        """生成 StudyX 格式的 chunk 事件"""
        event_data = {
            "code": 0,
            "msg": "Request succeeded",
            "eventId": None,
            "source": None,
            "data": {
                "contents": [{
                    "content": content,
                    "title": None,
                    "contentType": "text",
                    "msgId": None,
                    "role": "assistant",
                    "msgType": None,
                    "replaceFlag": None
                }],
                "msgId": msg_id,
                "sessionId": studyx_session_id,
                "data": None
            }
        }
        return f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    
    def make_end_event() -> str:
        """生成 StudyX 格式的结束事件"""
        event_data = {
            "code": 200,
            "msg": "success",
            "eventId": None,
            "source": None,
            "data": None
        }
        return f"data: {json.dumps(event_data)}\n\n"
    
    try:
        # 🆕 获取题目上下文（用于快速问题按钮）
        # 对于快捷问题（action_type_hint 存在），始终尝试获取题目上下文
        question_context = None
        if qid and token:
            from pathlib import Path
            artifacts_dir = Path("/root/usr/skill_agent_demo/backend/artifacts")
            if not artifacts_dir.exists():
                artifacts_dir = Path("backend/artifacts")
            if not artifacts_dir.exists():
                artifacts_dir = Path("artifacts")
            
            # 检查是否存在 session 文件及其 turn 数
            existing_turns = 0
            for user_dir in artifacts_dir.iterdir():
                if user_dir.is_dir():
                    md_file = user_dir / f"{session_id}.md"
                    if md_file.exists():
                        content = md_file.read_text(encoding='utf-8')
                        existing_turns = content.count("## Turn ")
                        break
            
            # 🆕 条件：新 session 或者有快捷操作类型 (action_type_hint)
            # 快捷问题需要题目上下文来理解 "this concept", "this problem" 等指代
            should_fetch_context = (existing_turns == 0) or action_type_hint
            
            if should_fetch_context:
                logger.info(f"🆕 [StudyX SSE] Fetching question context (qid={qid}, action={action_type_hint}, turns={existing_turns}, env={environment})...")
                from app.api.external import fetch_question_context_from_studyx
                question_context = await fetch_question_context_from_studyx(qid, token, environment)
                if question_context:
                    logger.info(f"✅ [StudyX SSE] Question context fetched: {len(question_context)} chars")
                else:
                    logger.warning(f"⚠️ [StudyX SSE] Failed to fetch question context")
        
        # 1. 调用完整的 Skill Pipeline
        result = await execute_skill_pipeline(
            message=message,
            user_id=user_id,
            session_id=session_id,
            orchestrator=orchestrator,
            quantity_override=None,
            skill_hint=None,
            file_uris=file_uris,
            referenced_text=referenced_text,
            action_type=action_type_hint,
            files=files,
            language=language,
            question_context=question_context  # 🆕 传递题目上下文
        )
        
        # 2. 提取内容
        content = result.get("content") or result.get("response_content") or {}
        
        # 根据 content_type 提取文本内容
        text = ""
        if isinstance(content, dict):
            if "text" in content:
                text = content.get("text", "")
            elif "intuition" in content:
                # explain_skill 响应
                parts = []
                if content.get("concept"):
                    parts.append(f"**{content['concept']}**\n\n")
                if content.get("intuition"):
                    parts.append(f"📚 **直觉理解**\n{content['intuition']}\n\n")
                if content.get("formal_definition"):
                    parts.append(f"📖 **正式定义**\n{content['formal_definition']}\n\n")
                if content.get("why_it_matters"):
                    parts.append(f"💡 **为什么重要**\n{content['why_it_matters']}\n\n")
                examples = content.get("examples", [])
                if examples:
                    parts.append("🌟 **实例**\n")
                    for i, ex in enumerate(examples, 1):
                        if isinstance(ex, dict):
                            parts.append(f"{i}. **{ex.get('example', '')}**\n   {ex.get('explanation', '')}\n\n")
                text = "".join(parts)
            elif "flashcards" in content:
                flashcards = content.get("flashcards", [])
                parts = [f"📚 已生成 {len(flashcards)} 张闪卡\n\n"]
                for i, card in enumerate(flashcards[:5], 1):
                    if isinstance(card, dict):
                        front = card.get("front", card.get("question", ""))
                        back = card.get("back", card.get("answer", ""))
                        parts.append(f"**卡片 {i}**\n🔹 正面: {front}\n🔸 背面: {back}\n\n")
                text = "".join(parts)
            elif "questions" in content:
                questions = content.get("questions", [])
                parts = [f"📝 已生成 {len(questions)} 道练习题\n\n"]
                for i, q in enumerate(questions, 1):
                    if isinstance(q, dict):
                        q_text = q.get("question", q.get("text", ""))
                        parts.append(f"**题目 {i}**: {q_text}\n")
                        options = q.get("options", [])
                        for opt in options:
                            if isinstance(opt, dict):
                                parts.append(f"   {opt.get('label', '')}) {opt.get('text', '')}\n")
                        parts.append("\n")
                text = "".join(parts)
            else:
                text = json.dumps(content, ensure_ascii=False, indent=2)
        elif isinstance(content, str):
            text = content
        else:
            text = str(content) if content else "处理完成"
        
        # 3. 流式发送内容（模拟 StudyX 的小块输出）
        if text:
            # StudyX 格式是非常小的块（约 1-5 个字符）
            chunk_size = 5
            for i in range(0, len(text), chunk_size):
                chunk = text[i:i+chunk_size]
                # 替换空格为 &nbsp; 以匹配 StudyX 格式
                # chunk = chunk.replace(' ', '&nbsp;')
                yield make_chunk_event(chunk)
                await asyncio.sleep(0.02)  # 模拟流式效果
        else:
            yield make_chunk_event("处理完成")
        
        # 4. 发送结束事件
        yield make_end_event()
        
    except Exception as e:
        logger.error(f"❌ StudyX SSE generation error: {e}", exc_info=True)
        error_event = {
            "code": 500,
            "msg": str(e),
            "eventId": None,
            "source": None,
            "data": None
        }
        yield f"data: {json.dumps(error_event)}\n\n"


class StudyXChatRequest(BaseModel):
    """StudyX 发送消息请求格式"""
    promptInput: str = Field(default="", description="用户消息（快捷按钮时可为空）")
    aiId: int = Field(default=21, description="AI ID")
    channelId: Optional[int] = Field(None, description="频道 ID")
    aiQuestionId: str = Field(..., description="题目 ID（数字格式，用于 session_id）")
    aiAnswerId: str = Field(..., description="答案 ID")
    chatType: int = Field(default=2, description="聊天类型")
    lastAnswerId: Optional[str] = Field(None, description="上一条回复 ID（用于 regenerate）")
    # 🆕 支持快捷按钮和文件上传
    actionType: Optional[str] = Field(None, description="快捷按钮类型（explain_concept/make_simpler/common_mistakes 等）")
    fileUris: Optional[List[str]] = Field(None, description="文件 URI 列表")
    files: Optional[List[Dict[str, Any]]] = Field(None, description="文件信息列表")
    referencedText: Optional[str] = Field(None, description="引用的文本")
    # 🆕 题目上下文支持（slug 格式的 resource_id 用于获取题目详情）
    resourceId: Optional[str] = Field(None, description="题目 slug（如 96rhh58），用于获取题目上下文")


class StudyXRefreshRequest(BaseModel):
    """StudyX 重新生成请求格式"""
    promptInput: str = Field(..., description="原始消息")
    aiId: int = Field(default=21, description="AI ID")
    channelId: Optional[int] = Field(None, description="频道 ID")
    aiQuestionId: str = Field(..., description="题目 ID")
    aiAnswerId: str = Field(..., description="答案 ID")
    chatType: int = Field(default=2, description="聊天类型")
    lastAnswerId: str = Field(..., description="要重新生成的回复 ID")


@studyx_router.post("/newHomeChatQuestionV2", response_class=StreamingResponse)
async def studyx_new_chat_question(
    request: StudyXChatRequest,
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator),
    token: Optional[str] = Header(None, description="用户认证 Token"),
    environment: Optional[str] = Header("test", description="环境标识 (dev/test/prod)")
):
    """
    🔄 StudyX 兼容接口 - 发送新消息
    
    将 StudyX 格式转换为内部格式并调用 SSE 流
    支持：快捷按钮、文件上传、语言偏好
    """
    if token:
        set_user_api_token(token)
    
    try:
        # 转换参数
        session_id = f"q{request.aiQuestionId}_a{request.aiAnswerId}"
        
        # 🆕 环境标识
        env = environment or "test"
        logger.info(f"🌍 Environment: {env}")
        
        # 获取语言设置
        language = "en"
        if token:
            language = await get_user_language_from_studyx(token, env) or "en"
        
        # 处理文件
        file_uris = request.fileUris or []
        has_files = bool(file_uris or request.files)
        
        # 🆕 同步 App 端逻辑：处理消息
        message = request.promptInput.strip() if request.promptInput else ""
        
        # 场景 A: 快捷按钮模式（actionType）
        if not message and request.actionType:
            if language in ["zh", "zh-CN", "zh-TW"]:
                action_default_messages = {
                    "explain_concept": "请详细解释这个概念",
                    "make_simpler": "请用更简单的方式解释",
                    "common_mistakes": "这个知识点有哪些常见错误",
                    "step_by_step": "请一步一步解释解题过程",
                    "why_important": "为什么这个知识点很重要",
                }
                default_msg = "请帮我理解这个内容"
            elif language == "ja":
                action_default_messages = {
                    "explain_concept": "この概念を詳しく説明してください",
                    "make_simpler": "もっと簡単に説明してください",
                    "common_mistakes": "このトピックでよくある間違いは何ですか",
                }
                default_msg = "この内容を理解するのを手伝ってください"
            elif language == "ko":
                action_default_messages = {
                    "explain_concept": "이 개념을 자세히 설명해 주세요",
                    "make_simpler": "더 간단하게 설명해 주세요",
                    "common_mistakes": "이 주제에서 흔히 하는 실수는 무엇인가요",
                }
                default_msg = "이 내용을 이해하는 데 도움을 주세요"
            else:
                action_default_messages = {
                    "explain_concept": "Please explain this concept in detail",
                    "make_simpler": "Please explain this in a simpler way",
                    "common_mistakes": "What are the common mistakes for this topic",
                    "step_by_step": "Please explain the solution step by step",
                    "why_important": "Why is this concept important",
                }
                default_msg = "Please help me understand this content"
            message = action_default_messages.get(request.actionType, default_msg)
        
        # 场景 B: 文件上传模式
        if not message and has_files:
            if language in ["zh", "zh-CN", "zh-TW"]:
                message = "请帮我分析这个图片/文件的内容"
            elif language == "ja":
                message = "この画像/ファイルの内容を分析してください"
            elif language == "ko":
                message = "이 이미지/파일의 내용을 분석해 주세요"
            else:
                message = "Please help me analyze this image/file"
        
        logger.info("="*60)
        logger.info(f"📥 [StudyX] /newHomeChatQuestionV2")
        logger.info(f"   • Session: {session_id}")
        logger.info(f"   • Language: {language}")
        logger.info(f"   • Action Type: {request.actionType or 'N/A'}")
        logger.info(f"   • Files: {len(file_uris)} URIs, {len(request.files or [])} files")
        logger.info(f"   • Message: {message[:50]}...")
        logger.info("="*60)
        
        # 从 token 获取 user_id
        user_id = "unknown"
        if token:
            try:
                import base64
                parts = token.split('.')
                if len(parts) >= 2:
                    payload = base64.b64decode(parts[1] + '==')
                    payload_data = json.loads(payload)
                    user_id = payload_data.get('userguid', 'unknown')
            except:
                pass
        
        # 获取 session 锁
        lock = await get_session_lock(session_id)
        
        # 🔧 关键区分：使用 resourceId（slug 格式）获取题目上下文
        qid_for_context = request.resourceId  # 优先使用 slug 格式的 resourceId
        logger.info(f"   • QID for context: {qid_for_context or 'N/A (will skip context fetch)'}")
        
        async def locked_generator():
            async with lock:
                logger.info(f"🔒 [StudyX] Acquired lock for session: {session_id}")
                # 🆕 使用 StudyX 兼容格式的 SSE 流生成器
                async for event in generate_studyx_sse_stream(
                    message=message,
                    user_id=user_id,
                    session_id=session_id,
                    msg_id=request.aiQuestionId,  # 使用题目 ID 作为 msgId
                    orchestrator=orchestrator,
                    language=language,
                    file_uris=file_uris if file_uris else None,
                    files=request.files,
                    referenced_text=request.referencedText,
                    action_type_hint=request.actionType,
                    qid=qid_for_context,  # 🔧 使用 slug 格式的 resourceId 获取题目上下文
                    token=token,
                    environment=env  # 🆕 环境标识
                ):
                    yield event
                logger.info(f"🔓 [StudyX] Released lock for session: {session_id}")
        
        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ [StudyX] newHomeChatQuestionV2 error: {e}")
        error_event = f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return StreamingResponse(
            iter([error_event]),
            media_type="text/event-stream"
        )


@studyx_router.post("/newHwRefreshAnswer", response_class=StreamingResponse)
async def studyx_refresh_answer(
    request: StudyXRefreshRequest,
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator),
    token: Optional[str] = Header(None, description="用户认证 Token"),
    environment: Optional[str] = Header("test", description="环境标识 (dev/test/prod)")
):
    """
    🔄 StudyX 兼容接口 - 重新生成回复
    
    将 StudyX 格式转换为内部 regenerate 操作
    """
    if token:
        set_user_api_token(token)
    
    try:
        session_id = f"q{request.aiQuestionId}_a{request.aiAnswerId}"
        
        # 🆕 环境标识
        env = environment or "test"
        
        logger.info("="*60)
        logger.info(f"📥 [StudyX] /newHwRefreshAnswer")
        logger.info(f"   • Session: {session_id}")
        logger.info(f"   • LastAnswerId: {request.lastAnswerId}")
        logger.info(f"   • Environment: {env}")
        logger.info("="*60)
        
        # 获取语言设置
        language = "en"
        if token:
            language = await get_user_language_from_studyx(token, env) or "en"
        
        # 从 token 获取 user_id
        user_id = "unknown"
        if token:
            try:
                import base64
                parts = token.split('.')
                if len(parts) >= 2:
                    payload = base64.b64decode(parts[1] + '==')
                    payload_data = json.loads(payload)
                    user_id = payload_data.get('userguid', 'unknown')
            except:
                pass
        
        # 🆕 从 lastAnswerId 推断 turn_id
        # lastAnswerId 格式可能是数字字符串，需要映射到 turn_id
        # 简化处理：使用最后一轮作为 regenerate 目标
        turn_id = None
        try:
            # 读取 session 文件获取最新 turn
            from pathlib import Path
            artifacts_dir = Path("/root/usr/skill_agent_demo/backend/artifacts")
            
            for user_dir in artifacts_dir.iterdir():
                if not user_dir.is_dir():
                    continue
                session_file = user_dir / f"{session_id}.md"
                if session_file.exists():
                    content = session_file.read_text()
                    # 找到最后一个 Turn 号
                    turns = re.findall(r'## Turn (\d+)', content)
                    if turns:
                        turn_id = int(turns[-1])
                    break
        except Exception as e:
            logger.warning(f"⚠️ Failed to get last turn: {e}")
        
        if turn_id is None:
            turn_id = 1  # 默认重新生成第一轮
        
        logger.info(f"   • Regenerate Turn: {turn_id}")
        
        # 获取 session 锁
        lock = await get_session_lock(session_id)
        
        # 🆕 StudyX 兼容格式的 regenerate SSE 流
        import uuid
        studyx_session_id = str(uuid.uuid4().int)[:19]
        
        def make_studyx_chunk(content: str) -> str:
            return f"data: {json.dumps({'code': 0, 'msg': 'Request succeeded', 'eventId': None, 'source': None, 'data': {'contents': [{'content': content, 'title': None, 'contentType': 'text', 'msgId': None, 'role': 'assistant', 'msgType': None, 'replaceFlag': None}], 'msgId': request.aiQuestionId, 'sessionId': studyx_session_id, 'data': None}}, ensure_ascii=False)}\n\n"
        
        async def locked_generator():
            async with lock:
                logger.info(f"🔒 [StudyX] Acquired lock for session: {session_id}")
                
                full_text = ""
                async for event in generate_sse_stream(
                    message=request.promptInput,
                    user_id=user_id,
                    session_id=session_id,
                    action="regenerate",
                    turn_id=turn_id,
                    orchestrator=orchestrator,
                    language=language,
                    file_uris=None,
                    files=None,
                    referenced_text=None,
                    action_type_hint=None,
                    qid=request.aiQuestionId,
                    token=token,
                    environment=env  # 🆕 环境标识
                ):
                    # 解析内部 SSE 事件并转换为 StudyX 格式
                    if event.startswith("data: "):
                        try:
                            event_data = json.loads(event[6:].strip())
                            event_type = event_data.get("type")
                            
                            if event_type == "chunk":
                                chunk_content = event_data.get("content", "")
                                full_text += chunk_content
                                # 分小块发送（每 5 个字符）
                                for i in range(0, len(chunk_content), 5):
                                    yield make_studyx_chunk(chunk_content[i:i+5])
                                    await asyncio.sleep(0.02)
                            elif event_type == "done":
                                # 如果没有 chunk，从 done 事件获取完整响应
                                if not full_text:
                                    done_text = event_data.get("full_response", "")
                                    for i in range(0, len(done_text), 5):
                                        yield make_studyx_chunk(done_text[i:i+5])
                                        await asyncio.sleep(0.02)
                        except json.JSONDecodeError:
                            pass
                
                # 发送结束事件
                yield f"data: {json.dumps({'code': 200, 'msg': 'success', 'eventId': None, 'source': None, 'data': None})}\n\n"
                logger.info(f"🔓 [StudyX] Released lock for session: {session_id}")
        
        return StreamingResponse(
            locked_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
        
    except Exception as e:
        logger.error(f"❌ [StudyX] newHwRefreshAnswer error: {e}")
        error_event = f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        return StreamingResponse(
            iter([error_event]),
            media_type="text/event-stream"
        )


@studyx_router.get("/getHomeworkChatListV2")
async def studyx_get_chat_list(
    aiQuestionId: str,
    answerId: str,
    token: Optional[str] = Header(None, description="用户认证 Token")
):
    """
    🔄 StudyX 兼容接口 - 获取聊天历史列表
    
    返回格式与 StudyX 原生接口完全兼容：
    {
        "code": 0,
        "msg": "Request succeeded",
        "data": {
            "lastAnswerId": "xxx",
            "resultList": [
                {
                    "question": {...},
                    "answerList": [{...}]
                }
            ]
        }
    }
    """
    import uuid
    from datetime import datetime, timezone
    from pathlib import Path
    
    try:
        session_id = f"q{aiQuestionId}_a{answerId}"
        
        logger.info("="*60)
        logger.info(f"📥 [StudyX] /getHomeworkChatListV2")
        logger.info(f"   • Question ID: {aiQuestionId}")
        logger.info(f"   • Answer ID: {answerId}")
        logger.info(f"   • Session: {session_id}")
        logger.info("="*60)
        
        # 查找 session 文件
        artifacts_dir = Path("/root/usr/skill_agent_demo/backend/artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("backend/artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("artifacts")
        
        # 搜索所有用户目录，找到最新修改的 session 文件
        md_file = None
        user_id = None
        latest_mtime = 0
        
        for user_dir in artifacts_dir.iterdir():
            if user_dir.is_dir():
                potential_file = user_dir / f"{session_id}.md"
                if potential_file.exists():
                    current_mtime = potential_file.stat().st_mtime
                    if current_mtime > latest_mtime:
                        latest_mtime = current_mtime
                        md_file = potential_file
                        user_id = user_dir.name
        
        if not md_file:
            logger.info(f"📄 No session file found for session={session_id}")
            return {
                "code": 0,
                "msg": "Request succeeded",
                "eventId": None,
                "source": None,
                "data": {
                    "lastAnswerId": None,
                    "resultList": []
                }
            }
        
        logger.info(f"📄 Found session file: {md_file} (user={user_id})")
        content = md_file.read_text(encoding='utf-8')
        
        # 解析 MD 文件中的 turns
        turn_pattern = re.compile(r'## Turn (\d+).*?(?=## Turn \d+|\Z)', re.DOTALL)
        turns = turn_pattern.findall(content)
        turn_sections = turn_pattern.finditer(content)
        
        result_list = []
        last_answer_id = None
        
        for match in turn_sections:
            turn_text = match.group(0)
            turn_num = int(re.search(r'## Turn (\d+)', turn_text).group(1))
            
            try:
                # 提取时间戳
                time_match = re.search(r'\*\*Time\*\*:\s*(\d{2}:\d{2}:\d{2})', turn_text)
                timestamp = time_match.group(1) if time_match else "00:00:00"
                
                # 创建时间（使用今天的日期）
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                create_time = f"{today}T{timestamp}.000+00:00"
                
                # 生成唯一的 chatId
                base_id = int(uuid.uuid4().int % (10**19))
                question_chat_id = str(base_id + turn_num * 2)
                answer_chat_id = str(base_id + turn_num * 2 + 1)
                
                # 提取用户消息
                user_match = re.search(r'"user_query":\s*"((?:[^"\\]|\\.)*)"', turn_text)
                user_message = user_match.group(1) if user_match else ""
                if user_message:
                    user_message = user_message.replace('\\n', '\n').replace('\\r', '\r').replace('\\"', '"')
                
                # 提取 AI 响应
                assistant_message = ""
                
                # 方法1: 从 JSON 块解析
                details_match = re.search(r'<details>.*?```json\s*(.*?)\s*```.*?</details>', turn_text, re.DOTALL)
                if details_match:
                    try:
                        json_content = json.loads(details_match.group(1))
                        if isinstance(json_content, dict):
                            assistant_message = json_content.get("text", "")
                    except:
                        pass
                
                # 方法2: 从 "text" 字段提取
                if not assistant_message:
                    text_match = re.search(r'"text":\s*"((?:[^"\\]|\\.)*)"', turn_text)
                    if text_match:
                        assistant_message = text_match.group(1)
                        assistant_message = assistant_message.replace('\\n', '\n').replace('\\r', '\r').replace('\\"', '"')
                
                # 方法3: 取 Agent Response 部分
                if not assistant_message:
                    response_match = re.search(r'### 🤖 Agent Response\s*\n(.*?)(?=\n###|\n##|\Z)', turn_text, re.DOTALL)
                    if response_match:
                        assistant_message = response_match.group(1).strip()[:1000]
                
                # 构建 StudyX 格式的 question
                question_obj = {
                    "chatId": question_chat_id,
                    "messageId": None,
                    "sessionId": answerId,
                    "userId": user_id,
                    "messageType": None,
                    "messageOrigin": 1,  # 1 = 用户消息
                    "message": user_message,
                    "messageText": user_message,
                    "searchQnts": None,
                    "searchWeb": None,
                    "searchContent": None,
                    "sources": None,
                    "createTime": create_time,
                    "aiTypeId": 21,
                    "hasWebAccess": None,
                    "modelType": None,
                    "parentId": "0",
                    "likeType": None,
                    "aiName": None
                }
                
                # 构建 StudyX 格式的 answer
                answer_obj = {
                    "chatId": answer_chat_id,
                    "messageId": None,
                    "sessionId": answerId,
                    "userId": user_id,
                    "messageType": None,
                    "messageOrigin": 2,  # 2 = AI 响应
                    "message": assistant_message,
                    "messageText": None,
                    "searchQnts": None,
                    "searchWeb": None,
                    "searchContent": None,
                    "sources": None,
                    "createTime": create_time,
                    "aiTypeId": 21,
                    "hasWebAccess": None,
                    "modelType": None,
                    "parentId": question_chat_id,
                    "likeType": 0,
                    "aiName": None
                }
                
                result_list.append({
                    "question": question_obj,
                    "answerList": [answer_obj]
                })
                
                # 更新 lastAnswerId
                last_answer_id = answer_chat_id
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to parse turn {turn_num}: {e}")
                continue
        
        logger.info(f"✅ Parsed {len(result_list)} turns for StudyX format")
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "eventId": None,
            "source": None,
            "data": {
                "lastAnswerId": last_answer_id,
                "resultList": result_list
            }
        }
        
    except Exception as e:
        logger.error(f"❌ [StudyX] getHomeworkChatListV2 error: {e}", exc_info=True)
        return {
            "code": 500,
            "msg": str(e),
            "eventId": None,
            "source": None,
            "data": None
        }
