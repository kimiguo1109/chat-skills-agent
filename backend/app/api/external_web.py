"""
External Web API - Web 专用聊天接口（SSE 流式 + Edit/Regenerate）

与 /api/external/chat (App端) 共享相同的核心功能：
- Intent Router（意图识别）
- Skill Orchestrator（技能执行）
- Memory Manager（上下文管理）
- MD 持久化

Web 端专属功能：
- SSE 流式输出
- Edit/Regenerate 支持（树状版本管理）
- Clear Session 支持
- 并发安全（per-session 锁）

🌳 树状版本结构：
当 Regenerate Turn N 时：
1. 原来的 Turn N+1, N+2... 保留（作为原版本 v1 的后续）
2. 新回答成为 Turn N 的 v2
3. 后续新对话挂在 v2 分支下

示例：
        Q1 ─┬─ A1 (v1) ─── Q2 ─── A2 ─── Q3 ─── A3  (branch: main)
            │
            └─ A1' (v2) ─── Q4 ─── A4              (branch: v1_regen_1)

端点:
- POST /api/external/chat/web - 流式聊天（支持所有 Skill）
- POST /api/external/chat/web/clear - 清除会话
- GET /api/external/chat/web/versions - 获取历史版本
- GET /api/external/chat/web/status - 获取会话状态
- GET /api/external/chat/web/branches - 获取分支列表
- POST /api/external/chat/web/switch-branch - 切换分支
"""
import logging
import asyncio
import json
import time
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator, Literal
from fastapi import APIRouter, HTTPException, Depends, Header, Query, Request
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
    get_question_context_error_hint,  # 🆕 获取友好错误提示
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


# ============= 🌳 树状版本管理 =============

"""
树状版本数据结构 (存储在 {session_id}_tree.json):

{
    "session_id": "q123_a456",
    "active_branch": "main",  # 当前活动分支
    "branches": {
        "main": {
            "created_at": "2025-12-23T10:00:00",
            "parent_branch": null,
            "fork_from_turn": null,
            "turns": [1, 2, 3]  # 该分支包含的 turn IDs
        },
        "regen_1_v2": {
            "created_at": "2025-12-23T10:05:00",
            "parent_branch": "main",
            "fork_from_turn": 1,  # 从 turn 1 分叉
            "turns": [1]  # 初始只有重新生成的 turn 1
        }
    },
    "turns": {
        "1": {
            "versions": {
                "main": {"timestamp": "...", "response": "A1"},
                "regen_1_v2": {"timestamp": "...", "response": "A1'"}
            }
        },
        "2": {
            "versions": {
                "main": {"timestamp": "...", "response": "A2"}
            }
        }
    }
}
"""


async def _load_version_tree(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str
) -> Dict[str, Any]:
    """加载或创建版本树"""
    from pathlib import Path
    
    artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
    tree_file = artifacts_dir / f"{session_id}_tree.json"
    
    if tree_file.exists():
        try:
            return json.loads(tree_file.read_text(encoding='utf-8'))
        except:
            pass
    
    # 创建默认版本树
    return {
        "session_id": session_id,
        "active_branch": "main",
        "branches": {
            "main": {
                "created_at": datetime.now().isoformat(),
                "parent_branch": None,
                "fork_from_turn": None,
                "turns": []
            }
        },
        "turns": {}
    }


async def _save_version_tree(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    tree: Dict[str, Any]
) -> bool:
    """保存版本树"""
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        tree_file = artifacts_dir / f"{session_id}_tree.json"
        
        tree_file.write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding='utf-8')
        return True
    except Exception as e:
        logger.error(f"❌ Failed to save version tree: {e}")
        return False


async def _create_regenerate_branch(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    turn_id: int,
    user_message: str
) -> Optional[str]:
    """
    🌳 为 regenerate 创建新分支
    
    Returns: 新分支名称，或 None 如果失败
    """
    from pathlib import Path
    
    tree = await _load_version_tree(memory_manager, user_id, session_id)
    
    # 生成新分支名称
    branch_count = len([b for b in tree["branches"] if b.startswith(f"regen_{turn_id}_")])
    new_branch = f"regen_{turn_id}_v{branch_count + 2}"  # v2, v3, v4...
    
    current_branch = tree["active_branch"]
    
    # 创建新分支
    tree["branches"][new_branch] = {
        "created_at": datetime.now().isoformat(),
        "parent_branch": current_branch,
        "fork_from_turn": turn_id,
        "turns": []  # 新 turn 会追加到这里
    }
    
    # 复制 fork 点之前的 turns 到新分支（共享引用）
    if current_branch in tree["branches"]:
        parent_turns = tree["branches"][current_branch].get("turns", [])
        # 新分支继承 fork_from_turn 之前的所有 turns
        tree["branches"][new_branch]["turns"] = [t for t in parent_turns if t < turn_id]
    
    # 记录 turn 的版本信息
    turn_key = str(turn_id)
    if turn_key not in tree["turns"]:
        tree["turns"][turn_key] = {"versions": {}}
    
    # 保存原版本信息（如果还没保存）
    if current_branch not in tree["turns"][turn_key]["versions"]:
        tree["turns"][turn_key]["versions"][current_branch] = {
            "timestamp": datetime.now().isoformat(),
            "user_message": user_message,
            "status": "original"
        }
    
    # 切换到新分支
    tree["active_branch"] = new_branch
    
    # 保存
    await _save_version_tree(memory_manager, user_id, session_id, tree)
    
    # 🆕 同时保存到 versions.json（与 Edit 保持一致）
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        versions_file = artifacts_dir / f"{session_id}_versions.json"
        md_file = artifacts_dir / f"{session_id}.md"
        
        # 读取现有版本
        versions = []
        if versions_file.exists():
            try:
                versions = json.loads(versions_file.read_text(encoding='utf-8'))
            except:
                versions = []
        
        # 获取当前 turn 的原始回复和完整内容
        old_response = ""
        turn_content = ""
        if md_file.exists():
            content = md_file.read_text(encoding='utf-8')
            turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})'
            turns = list(re.finditer(turn_pattern, content))
            
            for i, match in enumerate(turns):
                if int(match.group(1)) == turn_id:
                    start = match.start()
                    end = turns[i + 1].start() if i + 1 < len(turns) else len(content)
                    turn_content = content[start:end]
                    
                    # 提取 response - 优先从 JSON 块提取
                    json_match = re.search(r'"text":\s*"((?:[^"\\]|\\.)*)"', turn_content)
                    if json_match:
                        try:
                            old_response = json.loads(f'"{json_match.group(1)}"')
                        except:
                            old_response = json_match.group(1).replace('\\n', '\n')
                    # 备选：从 **Response**: 格式提取
                    if not old_response:
                        response_match = re.search(r'\*\*Response\*\*:\s*\n(.*?)(?:\n---|\n<details>|$)', turn_content, re.DOTALL)
                        if response_match:
                            old_response = response_match.group(1).strip()
                    break
        
        # 🆕 检查是否已有原始版本，如果没有则先保存
        existing_turn_versions = [v for v in versions if v.get("turn_id") == turn_id]
        has_original = any(v.get("is_original", False) for v in existing_turn_versions)
        
        if not has_original and turn_content:
            # 保存原始版本
            versions.append({
                "version_id": 1,
                "turn_id": turn_id,
                "action": "original",
                "is_original": True,
                "timestamp": datetime.now().isoformat(),
                "content": turn_content,  # 保存完整 turn 内容
                "message": user_message,
                "response": old_response
            })
            logger.info(f"📝 Saved original version of turn {turn_id} before regenerate")
        
        # 添加 regenerate 版本（保存旧回复，等待新回复）
        new_version_id = len([v for v in versions if v.get("turn_id") == turn_id]) + 1
        versions.append({
            "version_id": new_version_id,
            "turn_id": turn_id,
            "action": "regenerate",
            "is_original": False,
            "timestamp": datetime.now().isoformat(),
            "message": user_message,  # Regenerate 时用户消息不变
            "response": old_response  # 保存旧回复（regenerate 前的）
        })
        
        versions_file.write_text(json.dumps(versions, ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info(f"🌳 Saved regenerate version to versions.json: turn {turn_id}, version {new_version_id}")
        
    except Exception as ver_err:
        logger.warning(f"⚠️ Failed to save regenerate version: {ver_err}")
    
    logger.info(f"🌳 Created regenerate branch: {new_branch} (forked from {current_branch} at turn {turn_id})")
    return new_branch


async def _create_edit_branch(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    turn_id: int,
    new_message: str
) -> Optional[str]:
    """
    🌳 为 edit 创建新分支
    
    Edit 与 Regenerate 的区别：
    - Edit: 用户修改了问题内容，创建新分支
    - Regenerate: 问题不变，只是重新生成回答
    
    Returns: 新分支名称，或 None 如果失败
    """
    tree = await _load_version_tree(memory_manager, user_id, session_id)
    
    # 生成新分支名称 - 使用 edit 前缀区分
    branch_count = len([b for b in tree["branches"] if b.startswith(f"edit_{turn_id}_")])
    new_branch = f"edit_{turn_id}_v{branch_count + 2}"  # v2, v3, v4...
    
    current_branch = tree["active_branch"]
    
    # 创建新分支
    tree["branches"][new_branch] = {
        "created_at": datetime.now().isoformat(),
        "parent_branch": current_branch,
        "fork_from_turn": turn_id,
        "edit_type": "question_modified",  # 标记这是问题修改
        "original_message": None,  # 将在下面填充
        "new_message": new_message,
        "turns": []
    }
    
    # 复制 fork 点之前的 turns 到新分支
    if current_branch in tree["branches"]:
        parent_turns = tree["branches"][current_branch].get("turns", [])
        tree["branches"][new_branch]["turns"] = [t for t in parent_turns if t < turn_id]
    
    # 记录 turn 的版本信息
    turn_key = str(turn_id)
    if turn_key not in tree["turns"]:
        tree["turns"][turn_key] = {"versions": {}}
    
    # 保存原版本信息（如果还没保存）
    if current_branch not in tree["turns"][turn_key]["versions"]:
        # 尝试从 MD 文件获取原始消息
        original_msg = await _get_turn_message(memory_manager, user_id, session_id, turn_id)
        tree["turns"][turn_key]["versions"][current_branch] = {
            "timestamp": datetime.now().isoformat(),
            "user_message": original_msg or "",
            "status": "original"
        }
        tree["branches"][new_branch]["original_message"] = original_msg
    
    # 记录新版本信息
    tree["turns"][turn_key]["versions"][new_branch] = {
        "timestamp": datetime.now().isoformat(),
        "user_message": new_message,
        "status": "edited"
    }
    
    # 切换到新分支
    tree["active_branch"] = new_branch
    
    await _save_version_tree(memory_manager, user_id, session_id, tree)
    
    logger.info(f"🌳 Created edit branch: {new_branch} (forked from {current_branch} at turn {turn_id}, new message: '{new_message[:30]}...')")
    return new_branch


async def _switch_to_version_path(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    version_path: str
) -> Optional[str]:
    """
    🌳 根据 version_path 切换到对应的分支
    
    version_path 格式: "turn_id:version_id" (如 "1:2" 表示 Turn 1 的 version 2)
    
    Returns: 切换后的分支名称，或 None 如果失败
    """
    if not version_path:
        return None
    
    try:
        tree = await _load_version_tree(memory_manager, user_id, session_id)
        
        # 解析 version_path
        parts = version_path.split(",")
        for part in parts:
            if ":" not in part:
                continue
            turn_id_str, version_id_str = part.split(":")
            turn_id = int(turn_id_str)
            version_id = int(version_id_str)
            
            turn_key = str(turn_id)
            if turn_key not in tree["turns"]:
                logger.warning(f"⚠️ Turn {turn_id} not found in tree")
                continue
            
            # 找到对应版本的分支
            versions = tree["turns"][turn_key].get("versions", {})
            branch_list = list(versions.keys())
            
            if version_id > 0 and version_id <= len(branch_list):
                target_branch = branch_list[version_id - 1]
                tree["active_branch"] = target_branch
                await _save_version_tree(memory_manager, user_id, session_id, tree)
                logger.info(f"🌳 Switched to branch '{target_branch}' via version_path '{version_path}'")
                return target_branch
        
        return tree["active_branch"]
        
    except Exception as e:
        logger.error(f"❌ Failed to switch version path: {e}")
        return None


async def _add_turn_to_branch(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    turn_id: int,
    user_message: str,
    response: str
) -> bool:
    """将新 turn 添加到当前活动分支"""
    tree = await _load_version_tree(memory_manager, user_id, session_id)
    
    active_branch = tree["active_branch"]
    
    # 添加 turn 到分支
    if active_branch not in tree["branches"]:
        tree["branches"][active_branch] = {
            "created_at": datetime.now().isoformat(),
            "parent_branch": None,
            "fork_from_turn": None,
            "turns": []
        }
    
    if turn_id not in tree["branches"][active_branch]["turns"]:
        tree["branches"][active_branch]["turns"].append(turn_id)
    
    # 记录 turn 版本信息
    turn_key = str(turn_id)
    if turn_key not in tree["turns"]:
        tree["turns"][turn_key] = {"versions": {}}
    
    tree["turns"][turn_key]["versions"][active_branch] = {
        "timestamp": datetime.now().isoformat(),
        "user_message": user_message,
        "response_preview": response[:100] if response else "",
        "status": "active"
    }
    
    await _save_version_tree(memory_manager, user_id, session_id, tree)
    return True


async def _get_branch_turns(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    branch: Optional[str] = None
) -> List[int]:
    """获取指定分支（或当前活动分支）的 turn 列表"""
    tree = await _load_version_tree(memory_manager, user_id, session_id)
    
    branch = branch or tree["active_branch"]
    
    if branch in tree["branches"]:
        return tree["branches"][branch].get("turns", [])
    
    return []


async def _switch_branch(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    branch: str
) -> bool:
    """切换到指定分支"""
    tree = await _load_version_tree(memory_manager, user_id, session_id)
    
    if branch not in tree["branches"]:
        logger.warning(f"⚠️ Branch not found: {branch}")
        return False
    
    tree["active_branch"] = branch
    await _save_version_tree(memory_manager, user_id, session_id, tree)
    
    logger.info(f"🌳 Switched to branch: {branch}")
    return True


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
    # 🌳 分支管理
    branch: Optional[str] = Field(None, description="指定分支名称（不传则使用当前活动分支）")
    # 🌳 版本路径（用于在特定版本下继续对话）
    version_path: Optional[str] = Field(None, description="版本路径，格式: 'turn_id:version_id'，如 '1:2' 表示在 Turn 1 的 version 2 下继续对话")
    
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


class FeedbackRequest(BaseModel):
    """反馈请求 - 兼容前端字段名"""
    user_id: str = Field(..., description="用户 ID")
    question_id: Optional[str] = Field(None, description="题目 ID")
    answer_id: Optional[str] = Field(None, description="答案 ID")
    # 兼容两种字段名
    turn_id: Optional[int] = Field(None, description="对话轮次")
    turn_number: Optional[int] = Field(None, description="对话轮次（兼容前端）")
    # 兼容数字和字符串类型
    feedback_type: Optional[str] = Field(None, description="反馈类型: like/dislike/cancel 或 1/2/3")
    # 前端可能传数字
    feedback_type_num: Optional[int] = Field(None, alias="feedback_type", description="反馈类型数字")
    reason: Optional[str] = Field(None, description="反馈原因（dislike时可选）")
    detail: Optional[str] = Field(None, description="反馈详情")
    # 🆕 从 URL 获取的参数（兼容）
    session_id: Optional[str] = Field(None, description="会话 ID")


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
    environment: str = "test",  # 🆕 环境标识
    # 🌳 版本路径（用于在特定版本下继续对话）
    version_path: Optional[str] = None
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
        
        # 2. 🌳 处理版本路径切换（在特定版本下继续对话）
        if version_path and action == ActionType.SEND:
            switched_branch = await _switch_to_version_path(
                orchestrator.memory_manager,
                user_id,
                session_id,
                version_path
            )
            if switched_branch:
                logger.info(f"🌳 Continuing conversation in branch: {switched_branch}")
        
        # 3. 处理 Edit/Regenerate
        if action == ActionType.EDIT:
            # 🆕 如果没有 turn_id，尝试从 version_path 提取
            if not turn_id and version_path:
                try:
                    # version_path 格式: "turn_id:version_id" 或 "turn_id:null"
                    parts = version_path.split(":")
                    if parts[0].isdigit():
                        turn_id = int(parts[0])
                        logger.info(f"🆕 Extracted turn_id={turn_id} from version_path={version_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to extract turn_id from version_path: {e}")
            
            if not turn_id:
                yield f"data: {json.dumps({'type': 'error', 'message': 'turn_id is required for edit action (can also use version_path)'})}\n\n"
                return
            
            if not message:
                yield f"data: {json.dumps({'type': 'error', 'message': 'message is required for edit action'})}\n\n"
                return
            
            # 🌳 树状版本管理：Edit 创建新分支（保留原问题和后续对话）
            new_branch = await _create_edit_branch(
                orchestrator.memory_manager,
                user_id,
                session_id,
                turn_id,
                message
            )
            
            if new_branch:
                logger.info(f"🌳 Edit turn {turn_id}: created branch '{new_branch}', new message: '{message[:50]}...'")
            else:
                logger.warning(f"⚠️ Failed to create edit branch, continuing anyway")
            
        elif action == ActionType.REGENERATE:
            # 🆕 如果没有 turn_id，尝试从 version_path 提取
            if not turn_id and version_path:
                try:
                    parts = version_path.split(":")
                    if parts[0].isdigit():
                        turn_id = int(parts[0])
                        logger.info(f"🆕 Extracted turn_id={turn_id} from version_path={version_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to extract turn_id from version_path: {e}")
            
            # 🌳 树状版本管理：Regenerate 创建新分支
            actual_turn_count = await _get_current_turn_count(
                orchestrator.memory_manager,
                user_id,
                session_id
            )
            
            if not turn_id or turn_id < 1:
                turn_id = actual_turn_count if actual_turn_count > 0 else None
                logger.info(f"🔄 Regenerate: no turn_id provided, using last turn = {turn_id}")
            elif turn_id > actual_turn_count:
                logger.info(f"🔄 Regenerate: turn_id {turn_id} > actual {actual_turn_count}, using last turn")
                turn_id = actual_turn_count
            
            if not turn_id or actual_turn_count == 0:
                logger.info(f"⚠️ Regenerate: no turns found, converting to send action")
                action = ActionType.SEND
            
            if action == ActionType.REGENERATE and turn_id:
                # 获取原始消息
                original_message = await _get_turn_message(
                    orchestrator.memory_manager,
                    user_id,
                    session_id,
                    turn_id
                )
                
                if not original_message:
                    logger.info(f"⚠️ Turn {turn_id} not found, converting to send action")
                    action = ActionType.SEND
                else:
                    message = original_message
                    
                    # 🌳 创建新分支（保留原有对话）
                    new_branch = await _create_regenerate_branch(
                        orchestrator.memory_manager,
                        user_id,
                        session_id,
                        turn_id,
                        message
                    )
                    
                    if new_branch:
                        logger.info(f"🌳 Regenerate turn {turn_id}: created branch '{new_branch}', message: '{message[:50]}...'")
                    else:
                        logger.warning(f"⚠️ Failed to create branch, continuing with regenerate")
        
        # 2.5 🆕 处理题目上下文
        # 每次快捷问答都应该基于题目上下文，不仅限于新 session
        final_question_context = question_context
        logger.info(f"📚 Question context check: qid={qid}, token={'present' if token else 'missing'}, existing_context={'yes' if question_context else 'no'}")
        
        if not final_question_context and qid:
            # 🆕 API 支持两种格式：slug（如 4merhtg）和数字 ID（如 10040632384）
            if token:
                logger.info(f"📚 Fetching question context from StudyX (qid={qid}, env={environment})...")
                final_question_context, error_type = await fetch_question_context_from_studyx(qid, token, environment)
                if final_question_context:
                    logger.info(f"✅ Question context fetched: {len(final_question_context)} chars")
                elif error_type:
                    # 🆕 获取失败时，添加友好的错误提示到上下文
                    error_hint = get_question_context_error_hint(error_type, language)
                    final_question_context = error_hint
                    logger.warning(f"⚠️ Failed to fetch question context for qid={qid}, error_type={error_type}")
            else:
                logger.warning(f"⚠️ Cannot fetch question context: token is missing (qid={qid})")
        
        # 🆕 发送 thinking 状态，让客户端知道正在处理
        yield f"data: {json.dumps({'type': 'thinking', 'message': 'Processing your request...'})}\n\n"
        
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
        
        # 流式发送内容（分块）- 优化分块策略
        if text:
            # 🆕 智能分块：按句子或段落分割，而不是固定字符数
            # 优先按换行分割，然后按句子分割
            chunks = []
            for para in text.split('\n'):
                if para.strip():
                    # 如果段落太长，按句子分割
                    if len(para) > 150:
                        # 按句子分割（支持中英文标点）
                        sentences = re.split(r'(?<=[。！？.!?])\s*', para)
                        chunks.extend([s for s in sentences if s.strip()])
                    else:
                        chunks.append(para)
                else:
                    chunks.append('')  # 保留空行
            
            # 如果分块后太少，使用固定大小分块
            if len(chunks) <= 2 and len(text) > 100:
                chunk_size = 30  # 更小的块，更流畅
                chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
            
            for chunk in chunks:
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
                await asyncio.sleep(0.005)  # 更快的发送间隔
        else:
            # 🆕 即使没有文本，也发送一个空 chunk 表示处理完成
            yield f"data: {json.dumps({'type': 'chunk', 'content': '处理完成'})}\n\n"
        
        # 6. 获取实际轮次（新追加的 turn）
        new_turn_id = await _get_current_turn_count(
            orchestrator.memory_manager,
            user_id,
            session_id
        )
        
        # 🌳 7. 树状版本管理：更新版本树
        actual_turn_id = new_turn_id
        tree = await _load_version_tree(orchestrator.memory_manager, user_id, session_id)
        active_branch = tree.get("active_branch", "main")
        
        if action == ActionType.EDIT and turn_id:
            # 🆕 Edit：替换原 turn 而不是追加新 turn
            try:
                # 1. 删除新追加的 turn（execute_skill_pipeline 会自动追加）
                await _delete_last_turn(
                    orchestrator.memory_manager,
                    user_id,
                    session_id
                )
                
                # 2. 替换原 turn 的内容（保存原版本并更新）
                success = await _save_and_replace_turn_for_edit(
                    orchestrator.memory_manager,
                    user_id,
                    session_id,
                    turn_id,
                    message,
                    text
                )
                
                if success:
                    actual_turn_id = turn_id  # 返回原 turn ID
                    logger.info(f"✅ Edit complete: turn {turn_id} replaced with new version")
                else:
                    logger.warning(f"⚠️ Edit replacement failed, using new turn {new_turn_id}")
                    
            except Exception as edit_err:
                logger.error(f"❌ Edit post-processing failed: {edit_err}", exc_info=True)
                
        elif action == ActionType.REGENERATE and turn_id:
            # 🆕 Regenerate：替换原 turn 的回答（不追加新 turn）
            try:
                # 1. 先替换原 turn 的回答（与 Edit 相同的方式）
                success = await _replace_turn_response(
                    orchestrator.memory_manager,
                    user_id,
                    session_id,
                    turn_id,
                    text
                )
                
                if success:
                    actual_turn_id = turn_id
                    logger.info(f"✅ Regenerate: turn {turn_id} response replaced")
                    
                    # 2. 删除刚追加的新 turn（因为我们已经替换了原 turn）
                    await _delete_last_turn(
                        orchestrator.memory_manager,
                        user_id,
                        session_id
                    )
                else:
                    logger.warning(f"⚠️ Regenerate replacement failed, keeping new turn {new_turn_id}")
                    actual_turn_id = new_turn_id
                
                # 3. 更新 versions.json
                try:
                    from pathlib import Path
                    artifacts_dir = orchestrator.memory_manager.artifact_storage.base_dir / user_id
                    versions_file = artifacts_dir / f"{session_id}_versions.json"
                    
                    if versions_file.exists():
                        versions = json.loads(versions_file.read_text(encoding='utf-8'))
                        # 找到最新的 regenerate 版本，添加新回复
                        for v in reversed(versions):
                            if v.get("turn_id") == turn_id and v.get("action") == "regenerate" and "new_response" not in v:
                                v["new_response"] = text
                                logger.info(f"🌳 Updated regenerate version with new response")
                                break
                        versions_file.write_text(json.dumps(versions, ensure_ascii=False, indent=2), encoding='utf-8')
                except Exception as ver_update_err:
                    logger.warning(f"⚠️ Failed to update regenerate version: {ver_update_err}")
                
                logger.info(f"🌳 Regenerate complete: turn {turn_id} on branch '{active_branch}'")
            except Exception as regen_err:
                logger.error(f"❌ Regenerate post-processing failed: {regen_err}")
        else:
            # 普通 send：记录新 turn 到版本树
            try:
                await _add_turn_to_branch(
                    orchestrator.memory_manager,
                    user_id,
                    session_id,
                    new_turn_id,
                    message,
                    text
                )
            except Exception as tree_err:
                logger.warning(f"⚠️ Failed to update version tree: {tree_err}")
        
        # 8. 发送完成事件
        elapsed_time = time.time() - start_time
        token_usage = result.get("token_usage", {})
        context_stats = result.get("context_stats", {})
        
        # 🌳 构建 done 事件数据，包含分支信息
        done_data = {
            'type': 'done',
            'turn_id': actual_turn_id,
            'intent': intent,
            'content_type': content_type,
            'topic': topic,
            'full_response': text,
            'elapsed_time': round(elapsed_time, 2),
            'token_usage': token_usage,
            'context_stats': context_stats,
            'action': action.value,
            'branch': active_branch  # 🌳 当前活动分支
        }
        
        # 如果是 regenerate，标记新分支创建
        if action == ActionType.REGENERATE:
            done_data['branch_created'] = True
        
        # 🆕 如果是 edit，标记版本更新
        if action == ActionType.EDIT:
            done_data['version_updated'] = True
            done_data['original_turn_id'] = turn_id  # 原 turn ID
        
        yield f"data: {json.dumps(done_data)}\n\n"
        
        # 🆕 发送标准 SSE 终止信号
        yield "data: [DONE]\n\n"
        
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
        
        # 🆕 同步更新 metadata 文件的 turn_count
        metadata_file = artifacts_dir / f"{session_id}_metadata.json"
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
                # 更新 turn_count 为截断后的数量（turn_id - 1，因为我们截断了从 turn_id 开始的所有内容）
                metadata["turn_count"] = turn_id - 1
                metadata["last_updated"] = datetime.now().isoformat()
                metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
                logger.info(f"📝 Updated metadata: turn_count -> {turn_id - 1}")
            except Exception as meta_err:
                logger.warning(f"⚠️ Failed to update metadata: {meta_err}")
        
        logger.info(f"✅ Truncated session at turn {turn_id}, saved version {len(versions)}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to truncate and save version: {e}")
        return False


async def _delete_last_turn(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str
) -> bool:
    """
    删除 MD 文件中的最后一个 turn
    用于 Edit 操作后清理自动追加的新 turn
    """
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        
        if not md_file.exists():
            return False
        
        content = md_file.read_text(encoding='utf-8')
        
        # 找到所有 turn
        turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})'
        turns = list(re.finditer(turn_pattern, content))
        
        if len(turns) < 2:
            # 只有一个或没有 turn，不删除
            return False
        
        # 删除最后一个 turn
        last_turn_start = turns[-1].start()
        new_content = content[:last_turn_start].rstrip() + "\n\n"
        
        md_file.write_text(new_content, encoding='utf-8')
        
        # 更新 metadata
        metadata_file = artifacts_dir / f"{session_id}_metadata.json"
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
                metadata["turn_count"] = len(turns) - 1
                metadata["last_updated"] = datetime.now().isoformat()
                metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            except:
                pass
        
        logger.info(f"🗑️ Deleted last turn (turn {len(turns)}), now {len(turns)-1} turns")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to delete last turn: {e}")
        return False


async def _save_and_replace_turn_for_edit(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    turn_id: int,
    new_message: str,
    new_response: str
) -> bool:
    """
    🆕 Edit 操作：保存原版本并替换 turn 内容
    
    实现同一 turn 的多版本管理：
    1. 保存原 turn 到 versions 文件（作为历史版本）
    2. 替换 MD 文件中原 turn 的问题和回答
    3. 不改变 turn 数量，不追加新 turn
    
    Returns: True 如果成功
    """
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        versions_file = artifacts_dir / f"{session_id}_versions.json"
        
        if not md_file.exists():
            logger.warning(f"⚠️ MD file not found for edit: {md_file}")
            return False
        
        content = md_file.read_text(encoding='utf-8')
        
        # 解析 turns
        turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})'
        turns = list(re.finditer(turn_pattern, content))
        
        if not turns:
            logger.warning(f"⚠️ No turns found in MD file")
            return False
        
        # 找到目标 turn
        target_idx = None
        for i, match in enumerate(turns):
            if int(match.group(1)) == turn_id:
                target_idx = i
                break
        
        if target_idx is None:
            logger.warning(f"⚠️ Turn {turn_id} not found for edit")
            return False
        
        # 提取原 turn 的内容
        turn_start = turns[target_idx].start()
        if target_idx + 1 < len(turns):
            turn_end = turns[target_idx + 1].start()
        else:
            turn_end = len(content)
        
        original_turn_content = content[turn_start:turn_end]
        
        # 加载或创建版本历史
        versions = []
        if versions_file.exists():
            try:
                versions = json.loads(versions_file.read_text(encoding='utf-8'))
            except:
                versions = []
        
        # 检查是否已经保存过这个 turn 的原始版本
        has_original = any(v.get("turn_id") == turn_id and v.get("is_original", False) for v in versions)
        
        if not has_original:
            # 保存原始版本（第一次编辑时）
            versions.append({
                "version_id": len([v for v in versions if v.get("turn_id") == turn_id]) + 1,
                "turn_id": turn_id,
                "action": "original",
                "is_original": True,
                "timestamp": datetime.now().isoformat(),
                "content": original_turn_content
            })
            logger.info(f"📝 Saved original version of turn {turn_id}")
        
        # 保存新版本
        new_version_id = len([v for v in versions if v.get("turn_id") == turn_id]) + 1
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 构建新 turn 内容（保持原格式）
        new_turn_content = f"""## Turn {turn_id} - {timestamp}

### 👤 User Query
{new_message}

### 🤖 Agent Response
**Intent**: edit_response
**Content Type**: text
**Topic**: 

**Response**:
{new_response}

---

"""
        
        versions.append({
            "version_id": new_version_id,
            "turn_id": turn_id,
            "action": "edit",
            "is_original": False,
            "timestamp": datetime.now().isoformat(),
            "message": new_message,
            "response": new_response  # 🆕 保存完整内容
        })
        
        # 写入版本文件
        versions_file.write_text(json.dumps(versions, ensure_ascii=False, indent=2), encoding='utf-8')
        
        # 替换 MD 文件中的 turn 内容
        new_content = content[:turn_start] + new_turn_content + content[turn_end:]
        md_file.write_text(new_content, encoding='utf-8')
        
        logger.info(f"✅ Edit complete: turn {turn_id} replaced with version {new_version_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to save and replace turn for edit: {e}", exc_info=True)
        return False


async def _save_version_for_regenerate(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    turn_id: int
) -> Optional[str]:
    """
    🆕 为 regenerate 保存旧版本（不修改原始文件！）
    
    Regenerate 的正确行为：
    1. 保存旧版本到 versions.json（作为历史记录）
    2. 返回用户消息（用于重新生成）
    3. 【重要】不删除/不修改原始 MD 文件！
       新的回答会由后续流程**原地替换**该 turn 的 assistant response
    """
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        versions_file = artifacts_dir / f"{session_id}_versions.json"
        
        if not md_file.exists():
            logger.warning(f"⚠️ MD file not found: {md_file}")
            return None
        
        content = md_file.read_text(encoding='utf-8')
        
        # 解析 turns
        turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})'
        turns = list(re.finditer(turn_pattern, content))
        
        if not turns:
            return None
        
        # 找到目标 turn
        target_idx = None
        for i, match in enumerate(turns):
            if int(match.group(1)) == turn_id:
                target_idx = i
                break
        
        if target_idx is None:
            logger.warning(f"⚠️ Turn {turn_id} not found for regenerate")
            return None
        
        # 获取该 turn 的内容
        target_start = turns[target_idx].start()
        if target_idx + 1 < len(turns):
            target_end = turns[target_idx + 1].start()
        else:
            target_end = len(content)
        
        turn_content = content[target_start:target_end]
        
        # 提取用户消息
        user_match = re.search(r'### 👤 User Query\n(.*?)\n\n### 🤖', turn_content, re.DOTALL)
        user_message = user_match.group(1).strip() if user_match else None
        
        if not user_message:
            logger.warning(f"⚠️ Could not extract user message from turn {turn_id}")
            return None
        
        # 保存版本（只作为历史记录，不修改原始文件）
        versions = []
        if versions_file.exists():
            try:
                versions = json.loads(versions_file.read_text(encoding='utf-8'))
            except:
                versions = []
        
        versions.append({
            "version_id": len(versions) + 1,
            "action": "regenerate",
            "turn_id": turn_id,
            "timestamp": datetime.now().isoformat(),
            "old_content": turn_content,  # 保存旧版本
            "user_message": user_message
        })
        
        versions_file.write_text(json.dumps(versions, ensure_ascii=False, indent=2), encoding='utf-8')
        
        logger.info(f"✅ Saved version {len(versions)} for turn {turn_id} regenerate, user_message: '{user_message[:50]}...'")
        return user_message
        
    except Exception as e:
        logger.error(f"❌ Failed to save version for regenerate: {e}")
        return None


async def _replace_turn_response(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str,
    turn_id: int,
    new_response: str,
    intent: str = "other",
    topic: str = ""
) -> bool:
    """
    🆕 原地替换指定 turn 的 assistant response（用于 regenerate）
    
    这个函数会：
    - 找到指定 turn 的 assistant response 部分
    - 用新的 response 替换它
    - 保留所有其他 turns 不变
    """
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        
        if not md_file.exists():
            logger.warning(f"⚠️ MD file not found: {md_file}")
            return False
        
        content = md_file.read_text(encoding='utf-8')
        
        # 解析 turns
        turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})'
        turns = list(re.finditer(turn_pattern, content))
        
        if not turns:
            return False
        
        # 找到目标 turn
        target_idx = None
        target_match = None
        for i, match in enumerate(turns):
            if int(match.group(1)) == turn_id:
                target_idx = i
                target_match = match
                break
        
        if target_idx is None:
            logger.warning(f"⚠️ Turn {turn_id} not found for replacement")
            return False
        
        # 获取该 turn 的范围
        target_start = turns[target_idx].start()
        if target_idx + 1 < len(turns):
            target_end = turns[target_idx + 1].start()
        else:
            target_end = len(content)
        
        turn_content = content[target_start:target_end]
        
        # 提取用户消息
        user_match = re.search(r'### 👤 User Query\n(.*?)\n\n### 🤖', turn_content, re.DOTALL)
        user_message = user_match.group(1).strip() if user_match else "Unknown"
        
        # 构建新的 turn 内容
        timestamp = target_match.group(2)  # 保留原始时间戳
        new_timestamp = datetime.now().strftime("%H:%M:%S")  # 或使用新时间戳
        
        # 构建新的 JSON response
        new_json_data = {
            "turn_number": turn_id,
            "timestamp": datetime.now().isoformat(),
            "user_query": user_message,
            "intent": {
                "intent": intent,
                "topic": topic,
                "raw_text": user_message
            },
            "agent_response": {
                "skill": "chat",
                "artifact_id": "",
                "content": {
                    "text": new_response
                }
            },
            "metadata": {
                "model": "gemini-2.5-flash",
                "source": "/api/external/chat",
                "regenerated": True
            },
            "attachments": None
        }
        
        new_turn_content = f"""## Turn {turn_id} - {new_timestamp}

### 👤 User Query
{user_message}

### 🤖 Agent Response
**Type**: text | **Topic**: {topic or 'N/A'} | **Skill**: chat

```json
{{
  "text": {json.dumps(new_response, ensure_ascii=False)}
}}
```


<details>
<summary>📦 <b>结构化数据（JSON）</b> - 点击展开</summary>

```json
{json.dumps(new_json_data, ensure_ascii=False, indent=2)}
```

</details>

---

"""
        
        # 替换
        new_content = content[:target_start] + new_turn_content + content[target_end:]
        md_file.write_text(new_content, encoding='utf-8')
        
        logger.info(f"✅ Replaced turn {turn_id} response with new content ({len(new_response)} chars)")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to replace turn response: {e}")
        return False


async def _delete_last_turn(
    memory_manager: MemoryManager,
    user_id: str,
    session_id: str
) -> bool:
    """
    🆕 删除最后一个 turn（用于 regenerate 后清理重复 turn）
    """
    from pathlib import Path
    
    try:
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        
        if not md_file.exists():
            return False
        
        content = md_file.read_text(encoding='utf-8')
        
        # 解析 turns
        turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})'
        turns = list(re.finditer(turn_pattern, content))
        
        if len(turns) < 2:
            # 只有一个或没有 turn，不能删除
            logger.warning(f"⚠️ Cannot delete last turn: only {len(turns)} turns exist")
            return False
        
        # 获取最后一个 turn 的范围
        last_turn = turns[-1]
        last_turn_start = last_turn.start()
        
        # 删除最后一个 turn
        new_content = content[:last_turn_start].rstrip() + "\n"
        md_file.write_text(new_content, encoding='utf-8')
        
        # 更新 metadata
        metadata_file = artifacts_dir / f"{session_id}_metadata.json"
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text(encoding='utf-8'))
                if "turn_count" in metadata:
                    metadata["turn_count"] = max(0, metadata["turn_count"] - 1)
                metadata["last_updated"] = datetime.now().isoformat()
                metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as meta_err:
                logger.warning(f"⚠️ Failed to update metadata after delete: {meta_err}")
        
        logger.info(f"🗑️ Deleted last turn (turn {int(last_turn.group(1))})")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to delete last turn: {e}")
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
            logger.warning(f"⚠️ MD file not found: {md_file}")
            return None
        
        content = md_file.read_text(encoding='utf-8')
        
        # 🆕 方法1：直接从 Turn 标题后的 User Query 提取
        turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})'
        turns = list(re.finditer(turn_pattern, content))
        
        for i, match in enumerate(turns):
            if int(match.group(1)) == turn_id:
                start = match.start()
                end = turns[i + 1].start() if i + 1 < len(turns) else len(content)
                turn_content = content[start:end]
                
                # 从 User Query 块提取
                user_match = re.search(r'### 👤 User Query\n(.*?)\n\n### 🤖', turn_content, re.DOTALL)
                if user_match:
                    return user_match.group(1).strip()
                break
        
        # 🆕 方法2：备选 - 从 JSON 数据块提取
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
        logger.info(f"   • Action Type: {request.action_type or 'N/A'}")  # 🆕 记录 action_type
        logger.info(f"   • Turn ID: {request.turn_id}")  # 🆕 记录 turn_id (edit/regenerate 时重要)
        logger.info(f"   • Message: {request.message[:50] if request.message else 'N/A'}...")
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
        
        # 🆕 警告：没有消息也没有 action_type
        if not message and not request.action_type and not has_files:
            logger.warning(f"⚠️ [Web] No message, action_type, or files provided! This may cause unexpected behavior.")
        
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
                    environment=env,  # 🆕 环境标识
                    version_path=request.version_path  # 🌳 版本路径
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
    
    会删除本地和 S3 上的会话文件，真正清空会话。
    """
    from pathlib import Path
    import boto3
    from botocore.exceptions import ClientError
    
    session_id = f"q{request.question_id}_a{request.answer_id}"
    
    lock = await get_session_lock(session_id)
    
    async with lock:
        try:
            artifacts_dir = orchestrator.memory_manager.artifact_storage.base_dir / request.user_id
            md_file = artifacts_dir / f"{session_id}.md"
            metadata_file = artifacts_dir / f"{session_id}_metadata.json"
            versions_file = artifacts_dir / f"{session_id}_versions.json"
            
            previous_turns = 0
            deleted_files = []
            
            # 1. 删除本地 MD 文件
            if md_file.exists():
                content = md_file.read_text(encoding='utf-8')
                turn_pattern = r'## Turn (\d+)'
                matches = re.findall(turn_pattern, content)
                previous_turns = len(matches)
                
                md_file.unlink()
                deleted_files.append(str(md_file))
                logger.info(f"🗑️ Deleted local MD: {md_file}")
            
            # 2. 删除本地 metadata 文件
            if metadata_file.exists():
                metadata_file.unlink()
                deleted_files.append(str(metadata_file))
                logger.info(f"🗑️ Deleted local metadata: {metadata_file}")
            
            # 3. 删除本地 versions 文件
            if versions_file.exists():
                versions_file.unlink()
                deleted_files.append(str(versions_file))
                logger.info(f"🗑️ Deleted local versions: {versions_file}")
            
            # 4. 删除 S3 文件
            s3_deleted = []
            try:
                s3_client = boto3.client('s3')
                bucket_name = "skill-agent-demo"
                s3_prefix = f"{request.user_id}/{session_id}"
                
                # 列出并删除所有相关 S3 对象
                s3_keys = [
                    f"{request.user_id}/{session_id}.md",
                    f"{request.user_id}/{session_id}_metadata.json",
                ]
                
                for s3_key in s3_keys:
                    try:
                        s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
                        s3_deleted.append(s3_key)
                        logger.info(f"☁️ Deleted S3 object: s3://{bucket_name}/{s3_key}")
                    except ClientError as e:
                        if e.response['Error']['Code'] != 'NoSuchKey':
                            logger.warning(f"⚠️ Failed to delete S3 object {s3_key}: {e}")
                            
            except Exception as s3_err:
                logger.warning(f"⚠️ S3 cleanup failed (non-critical): {s3_err}")
            
            # 5. 清除内存中的 session 缓存（如果有）
            try:
                session_mgr = orchestrator.memory_manager.conversation_session_manager
                if hasattr(session_mgr, '_sessions') and session_id in session_mgr._sessions:
                    del session_mgr._sessions[session_id]
                    logger.info(f"🧹 Cleared session cache: {session_id}")
            except Exception as cache_err:
                logger.warning(f"⚠️ Cache cleanup failed (non-critical): {cache_err}")
            
            # 6. 🆕 清除该 session 的 feedback
            feedback_cleared = 0
            try:
                feedback_dir = Path("feedback")
                if not feedback_dir.exists():
                    feedback_dir = Path("backend/feedback")
                if not feedback_dir.exists():
                    feedback_dir = Path("/root/usr/skill_agent_demo/backend/feedback")
                
                user_feedback_file = feedback_dir / f"{request.user_id}_feedback.json"
                if user_feedback_file.exists():
                    existing_feedback = json.loads(user_feedback_file.read_text(encoding='utf-8'))
                    # 过滤掉该 session 的反馈
                    original_count = len(existing_feedback)
                    filtered_feedback = [fb for fb in existing_feedback if fb.get("session_id") != session_id]
                    feedback_cleared = original_count - len(filtered_feedback)
                    
                    if feedback_cleared > 0:
                        user_feedback_file.write_text(json.dumps(filtered_feedback, ensure_ascii=False, indent=2), encoding='utf-8')
                        logger.info(f"🧹 Cleared {feedback_cleared} feedback entries for session: {session_id}")
            except Exception as fb_err:
                logger.warning(f"⚠️ Feedback cleanup failed (non-critical): {fb_err}")
            
            # 7. 🆕 删除 tree.json 文件
            tree_file = artifacts_dir / f"{session_id}_tree.json"
            if tree_file.exists():
                tree_file.unlink()
                deleted_files.append(str(tree_file))
                logger.info(f"🗑️ Deleted local tree: {tree_file}")
            
            return {
                "code": 0,
                "msg": "Session cleared successfully",
                "data": {
                    "session_id": session_id,
                    "user_id": request.user_id,
                    "previous_turns": previous_turns,
                    "deleted_local": len(deleted_files),
                    "deleted_s3": len(s3_deleted),
                    "feedback_cleared": feedback_cleared,
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
    version_path: Optional[str] = Query(None, description="🌳 版本路径，格式: 'turn_id:version_id,turn_id:version_id'，如 '1:2' 表示选中 Turn 1 的 version 2"),
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
):
    """
    📜 获取单个会话的聊天历史（支持树状版本结构）
    
    🌳 树状版本概念：
    - 每个 turn 可以有多个版本（通过 regenerate/edit 产生）
    - 每个版本可以有自己的后续对话（子树）
    - 切换版本时，显示该版本及其子树的完整对话链
    
    参数：
    - version_path: 指定要查看的版本路径
      - 不传: 返回默认路径（每个 turn 使用最新版本）
      - '1:1': Turn 1 使用 version 1（原始版本）
      - '1:2': Turn 1 使用 version 2（regenerate 后的版本）
    
    返回：
    - chat_list: 当前选中路径的扁平化对话列表（兼容旧前端）
    - chat_tree: 完整的树状结构（新前端可用于版本切换）
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
                
                # 提取 referenced_text（支持两种格式）
                referenced_text = None
                # 🆕 方法1：从 attachments.referenced_text 提取（新格式）
                attachments_match = re.search(r'"attachments":\s*\{[^}]*"referenced_text":\s*"((?:[^"\\]|\\.)*)"', turn_text)
                if attachments_match and attachments_match.group(1):
                    referenced_text = attachments_match.group(1)
                    # 处理转义字符
                    referenced_text = referenced_text.replace('\\n', '\n').replace('\\r', '\r').replace('\\"', '"')
                
                # 方法2：直接从顶层 referenced_text 提取（旧格式兼容）
                if not referenced_text:
                    ref_match = re.search(r'"referenced_text":\s*"((?:[^"\\]|\\.)*)"', turn_text)
                    if ref_match and ref_match.group(1):
                        referenced_text = ref_match.group(1)
                        referenced_text = referenced_text.replace('\\n', '\n').replace('\\r', '\r').replace('\\"', '"')
                
                # 提取 feedback（从 MD 中的 JSON）
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
                    "feedback": feedback,
                    # 🆕 支持编辑和重新生成
                    "can_edit": True,
                    "can_regenerate": True,
                    "has_versions": False  # 稍后从版本文件更新
                })
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to parse turn: {e}")
                continue
        
        # 🆕 加载版本信息（包含完整的历史版本内容）
        versions_file = md_file.parent / f"{session_id}_versions.json"
        version_turns = set()
        versions_data = []  # 🆕 保存完整的版本数据
        
        if versions_file.exists():
            try:
                versions_data = json.loads(versions_file.read_text(encoding='utf-8'))
                for v in versions_data:
                    version_turns.add(v.get("turn_id"))
                logger.info(f"📜 Loaded {len(versions_data)} versions from versions.json")
            except Exception as ver_err:
                logger.warning(f"⚠️ Failed to load versions: {ver_err}")
        
        # 🆕 从 versions.json 构建每个 turn 的版本列表
        turn_versions_map = {}  # {turn_id: [{version_id, user_message, assistant_message, timestamp}]}
        for v in versions_data:
            turn_id = v.get("turn_id")
            if turn_id not in turn_versions_map:
                turn_versions_map[turn_id] = []
            
            # 从 content 字段解析用户消息和助手回复
            content = v.get("content", "")
            user_msg = v.get("message", "")  # Edit/Regenerate 时保存的用户消息
            action = v.get("action", "original")
            
            # 🆕 根据 action 类型选择回复字段
            if action == "regenerate":
                # Regenerate: new_response 是新生成的回复，response 是旧回复
                assistant_message = v.get("new_response") or v.get("response", "")
            else:
                # Edit/Original: response 字段
                assistant_message = v.get("response") or v.get("response_preview", "")
            
            # 如果是原始版本，从 content 中解析完整内容
            if v.get("is_original") and content:
                user_match = re.search(r'### 👤 User Query\n(.*?)\n\n### 🤖', content, re.DOTALL)
                if user_match:
                    user_msg = user_match.group(1).strip()
                
                # 🆕 从 JSON 块提取完整助手消息（不截断）
                json_match = re.search(r'"text":\s*"((?:[^"\\]|\\.)*)"', content)
                if json_match:
                    # 解码 JSON 转义字符
                    raw_text = json_match.group(1)
                    try:
                        assistant_message = json.loads(f'"{raw_text}"')  # 利用 JSON 解析转义
                    except:
                        assistant_message = raw_text.replace('\\n', '\n').replace('\\"', '"')
                
                # 🆕 备选：从 Response 块解析
                if not assistant_message:
                    response_match = re.search(r'\*\*Response\*\*:\s*\n(.*?)(?:\n---|\n<details>|$)', content, re.DOTALL)
                    if response_match:
                        assistant_message = response_match.group(1).strip()
            
            turn_versions_map[turn_id].append({
                "version_id": v.get("version_id"),
                "is_original": v.get("is_original", False),
                "action": action,
                "timestamp": v.get("timestamp"),
                "user_message": user_msg,
                "assistant_message": assistant_message  # 🔄 完整内容
            })
        
        # 🌳 加载树状版本信息
        tree_file = md_file.parent / f"{session_id}_tree.json"
        tree_info = None
        active_branch = "main"
        branches = []
        branch_switched = False
        
        if tree_file.exists():
            try:
                tree = json.loads(tree_file.read_text(encoding='utf-8'))
                # 🆕 不再使用 branch 切换，改用 version_path 选择版本
                logger.info(f"📜 Loaded tree with {len(tree.get('branches', {}))} branches")
                
                # 构建分支信息列表
                for branch_name, branch_data in tree.get("branches", {}).items():
                    branches.append({
                        "name": branch_name,
                        "is_active": branch_name == active_branch,
                        "created_at": branch_data.get("created_at"),
                        "fork_from_turn": branch_data.get("fork_from_turn"),
                        "parent_branch": branch_data.get("parent_branch"),
                        "turn_count": len(branch_data.get("turns", []))
                    })
                
                # 检查哪些 turns 有多个版本
                for turn_key, turn_data in tree.get("turns", {}).items():
                    turn_num = int(turn_key)
                    versions_count = len(turn_data.get("versions", {}))
                    if versions_count > 1:
                        version_turns.add(turn_num)
                
                tree_info = {
                    "active_branch": active_branch,
                    "total_branches": len(tree.get("branches", {})),
                    "branches": branches,
                    "branch_switched": branch_switched
                }
            except Exception as tree_err:
                logger.warning(f"⚠️ Failed to load version tree: {tree_err}")
        
        # 🌳 加载反馈状态（根据分支过滤）
        if user_id:
            feedback_dir = Path("feedback")
            if not feedback_dir.exists():
                feedback_dir = Path("backend/feedback")
            if not feedback_dir.exists():
                feedback_dir = Path("/root/usr/skill_agent_demo/backend/feedback")
            
            # 🆕 定义 feedback_map 在外部，确保后续代码可访问
            feedback_map = {}
            user_feedback_file = feedback_dir / f"{user_id}_feedback.json"
            if user_feedback_file.exists():
                try:
                    all_feedback = json.loads(user_feedback_file.read_text(encoding='utf-8'))
                    # 按 turn + version_id 构建 feedback map
                    for fb in all_feedback:
                        if fb.get("session_id") == session_id:
                            turn_num = fb.get("turn_number")
                            ver_id = fb.get("version_id", 1)
                            key = f"{turn_num}_{ver_id}"
                            feedback_map[key] = {
                                "type": fb.get("feedback_type"),
                                "reason": fb.get("reason"),
                                "timestamp": fb.get("timestamp"),
                                "version_id": ver_id
                            }
                    
                    # 更新 chat_list 中的 feedback（按 turn + version 匹配）
                    for item in chat_list:
                        turn_num = item.get("turn")
                        ver_id = item.get("version_id", 1) if "version_id" in item else 1
                        key = f"{turn_num}_{ver_id}"
                        if key in feedback_map:
                            item["feedback"] = feedback_map[key]
                except Exception as fb_err:
                    logger.warning(f"⚠️ Failed to load feedback: {fb_err}")
        
        # 更新 has_versions 标记
        for item in chat_list:
            if item["turn"] in version_turns:
                item["has_versions"] = True
        
        # 🌳 构建树状版本结构
        # 分析哪些 turns 是同一个问题的不同版本（通过 user_message 匹配）
        version_groups = {}  # {user_message: [turn_indices]}
        for i, item in enumerate(chat_list):
            msg = item["user_message"]
            if msg not in version_groups:
                version_groups[msg] = []
            version_groups[msg].append(i)
        
        # 构建 version_info：标记每个 turn 的版本关系
        version_info = {}
        for msg, indices in version_groups.items():
            if len(indices) > 1:
                # 这个问题有多个版本
                first_turn = chat_list[indices[0]]["turn"]
                version_info[first_turn] = {
                    "has_versions": True,
                    "versions": []
                }
                for idx, list_idx in enumerate(indices):
                    turn_data = chat_list[list_idx]
                    # 找出这个版本之后、下一个版本之前的所有 turns（子对话）
                    next_version_turn = chat_list[indices[idx + 1]]["turn"] if idx + 1 < len(indices) else None
                    children_turns = []
                    for j in range(list_idx + 1, len(chat_list)):
                        child_turn = chat_list[j]["turn"]
                        if next_version_turn and child_turn >= next_version_turn:
                            break
                        if chat_list[j]["user_message"] != msg:  # 不是同一问题的另一个版本
                            children_turns.append(child_turn)
                    
                    version_info[first_turn]["versions"].append({
                        "version_id": idx + 1,
                        "turn_in_list": turn_data["turn"],  # 在 chat_list 中的实际 turn 号
                        "timestamp": turn_data["timestamp"],
                        "answer_preview": turn_data["assistant_message"][:100] + "..." if len(turn_data["assistant_message"]) > 100 else turn_data["assistant_message"],
                        "children_turns": children_turns
                    })
        
        # 🌳 根据 version_path 参数确定当前选中的版本
        # 解析 version_path: "1:2" 表示 Turn 1 选择 version 2
        selected_versions = {}  # {turn_id: version_id}
        if version_path:
            try:
                for part in version_path.split(","):
                    if ":" in part:
                        turn_id, ver_id = part.split(":")
                        selected_versions[int(turn_id)] = int(ver_id)
            except:
                pass
        
        # 🆕 收集所有版本的 children_turns（用于排除）
        all_children_turns = set()
        for vi in version_info.values():
            for v in vi["versions"]:
                all_children_turns.update(v["children_turns"])
        
        # 计算应该显示的 turns（基于选中的版本路径）
        display_turns = []
        processed_questions = set()
        
        for item in chat_list:
            turn_num = item["turn"]
            msg = item["user_message"]
            
            # 🆕 如果这个 turn 是某个版本的子对话，跳过（稍后由版本选择决定）
            if turn_num in all_children_turns:
                continue
            
            # 检查这个问题是否有多个版本
            if msg in processed_questions:
                continue  # 已处理过这个问题的版本
            
            first_turn_with_versions = None
            for ft, vi in version_info.items():
                if vi["versions"] and any(v["turn_in_list"] == turn_num for v in vi["versions"]):
                    first_turn_with_versions = ft
                    break
            
            if first_turn_with_versions and first_turn_with_versions in version_info:
                # 这个问题有多个版本
                vi = version_info[first_turn_with_versions]
                selected_ver = selected_versions.get(first_turn_with_versions, len(vi["versions"]))  # 默认最新版本
                
                # 找到选中版本
                for v in vi["versions"]:
                    if v["version_id"] == selected_ver:
                        display_turns.append(v["turn_in_list"])
                        display_turns.extend(v["children_turns"])
                        processed_questions.add(msg)
                        break
            else:
                # 没有版本的普通 turn
                display_turns.append(turn_num)
        
        # 过滤 chat_list，只保留 display_turns
        filtered_chat_list = [item for item in chat_list if item["turn"] in display_turns]
        
        # 为每个 turn 添加版本信息
        for item in filtered_chat_list:
            turn_num = item["turn"]
            # 检查是否是某个版本组的一部分
            for ft, vi in version_info.items():
                for v in vi["versions"]:
                    if v["turn_in_list"] == turn_num:
                        item["version_id"] = v["version_id"]
                        item["total_versions"] = len(vi["versions"])
                        item["original_turn"] = ft
                        break
        
        # 🆕 构建 turn_versions：包含每个 turn 的所有历史版本
        turn_versions = {}
        
        # 首先从 versions_map 添加有多个版本的 turns
        for turn_id, versions_list in turn_versions_map.items():
            if len(versions_list) > 0:
                turn_versions[str(turn_id)] = {
                    "total_versions": len(versions_list),
                    "versions": sorted(versions_list, key=lambda x: x.get("version_id", 0))
                }
        
        # 🆕 然后为没有版本历史的 turns 添加默认版本信息
        for item in chat_list:
            turn_num = item["turn"]
            if str(turn_num) not in turn_versions:
                turn_versions[str(turn_num)] = {
                    "total_versions": 1,
                    "versions": [{
                        "version_id": 1,
                        "is_original": True,
                        "action": "original",
                        "timestamp": item.get("timestamp"),
                        "user_message": item.get("user_message", ""),
                        "assistant_message": item.get("assistant_message", "")
                    }]
                }
        
        # 🆕 重构 chat_list：返回当前版本路径的对话（每个 turn 只显示一条）
        # 前端需要版本切换时，使用 turn_versions 获取其他版本
        current_chat_list = []
        processed_turns = set()
        
        # 确定每个 turn 显示哪个版本
        for turn_key, version_data in turn_versions.items():
            if version_data["total_versions"] > 0:
                turn_num = int(turn_key)
                processed_turns.add(turn_num)
                
                versions = version_data["versions"]
                # 选择当前版本：优先使用 selected_versions，否则使用最新版本
                selected_ver = selected_versions.get(turn_num, len(versions))  # 默认最新版本
                
                # 找到选中的版本
                selected_version = None
                for v in versions:
                    if v["version_id"] == selected_ver:
                        selected_version = v
                        break
                
                # 如果没找到，使用最后一个版本
                if not selected_version:
                    selected_version = versions[-1]
                
                # 查找原始 item 以获取额外信息
                original_item = next((item for item in chat_list if item["turn"] == turn_num), {})
                
                # 🆕 获取该版本的 feedback（严格按 version_id 匹配，不 fallback）
                ver_feedback_key = f"{turn_num}_{selected_version['version_id']}"
                ver_feedback = feedback_map.get(ver_feedback_key)  # 不 fallback，每个版本独立
                
                current_chat_list.append({
                    "turn": turn_num,
                    "version_id": selected_version["version_id"],
                    "total_versions": len(versions),
                    "timestamp": selected_version.get("timestamp", original_item.get("timestamp", "")),
                    "user_message": selected_version["user_message"],
                    "assistant_message": selected_version["assistant_message"],
                    "referenced_text": original_item.get("referenced_text"),
                    "files": original_item.get("files"),
                    "feedback": ver_feedback,
                    "can_edit": True,
                    "can_regenerate": True,
                    "has_versions": len(versions) > 1,
                    "is_original": selected_version.get("is_original", False),
                    "action": selected_version.get("action", "original")
                })
        
        # 添加没有版本历史的 turns
        for item in filtered_chat_list:
            turn_num = item["turn"]
            if turn_num not in processed_turns:
                # 检查是否是 regenerate 产生的重复
                is_duplicate = False
                for turn_key, version_data in turn_versions.items():
                    for v in version_data["versions"]:
                        if v["user_message"] == item.get("user_message"):
                            is_duplicate = True
                            break
                    if is_duplicate:
                        break
                
                if not is_duplicate:
                    # 🆕 确保字段格式一致
                    item["version_id"] = 1
                    item["total_versions"] = 1
                    item["is_original"] = True
                    item["action"] = "original"
                    # 获取该 turn 的 feedback
                    fb_key = f"{turn_num}_1"
                    item["feedback"] = feedback_map.get(fb_key) or item.get("feedback")
                    current_chat_list.append(item)
        
        # 按 turn 顺序排序
        current_chat_list.sort(key=lambda x: x.get("turn", 0))
        
        # 🆕 构建包含所有版本的完整列表（供前端版本切换使用）
        all_versions_list = []
        for turn_key, version_data in turn_versions.items():
            turn_num = int(turn_key)
            original_item = next((item for item in chat_list if item["turn"] == turn_num), {})
            
            for v in version_data["versions"]:
                # 🆕 获取该版本的 feedback
                ver_fb_key = f"{turn_num}_{v['version_id']}"
                ver_feedback = feedback_map.get(ver_fb_key)
                
                all_versions_list.append({
                    "turn": turn_num,
                    "version_id": v["version_id"],
                    "total_versions": version_data["total_versions"],
                    "timestamp": v.get("timestamp"),
                    "user_message": v["user_message"],
                    "assistant_message": v["assistant_message"],
                    "feedback": ver_feedback,
                    "is_original": v.get("is_original", False),
                    "action": v.get("action", "original")
                })
        
        # 添加无版本的 turns
        for item in filtered_chat_list:
            turn_num = item["turn"]
            if str(turn_num) not in turn_versions:
                is_duplicate = any(
                    v["user_message"] == item.get("user_message")
                    for vd in turn_versions.values()
                    for v in vd["versions"]
                )
                if not is_duplicate:
                    # 获取该 turn 的 feedback
                    fb_key = f"{turn_num}_1"
                    fb = feedback_map.get(fb_key) or item.get("feedback")
                    
                    all_versions_list.append({
                        "turn": turn_num,
                        "version_id": 1,
                        "total_versions": 1,
                        "timestamp": item.get("timestamp"),
                        "user_message": item.get("user_message"),
                        "assistant_message": item.get("assistant_message"),
                        "feedback": fb,
                        "is_original": True,
                        "action": "original"
                    })
        
        all_versions_list.sort(key=lambda x: (x.get("turn", 0), x.get("version_id", 0)))
        
        # 🆕 加载 tree.json 以支持分支过滤
        tree = await _load_version_tree(orchestrator.memory_manager, user_id, session_id)
        
        # 🆕 根据 version_path 确定要显示的分支
        target_branch = None
        if version_path and tree.get("turns"):
            # 解析 version_path（如 "1:1" -> turn=1, version=1）
            try:
                parts = version_path.split(":")
                if len(parts) == 2:
                    vp_turn = int(parts[0])
                    vp_version = int(parts[1])
                    
                    # 在 tree.turns 中查找该版本属于哪个分支
                    turn_info = tree.get("turns", {}).get(str(vp_turn), {})
                    turn_versions_in_tree = turn_info.get("versions", {})
                    
                    # 根据 version_id 确定分支
                    # version 1 通常是 main 分支，version 2+ 通常是 edit/regen 分支
                    if vp_version == 1:
                        target_branch = "main"
                    else:
                        # 查找对应的分支
                        for branch_name, branch_data in turn_versions_in_tree.items():
                            # 通过时间戳或其他方式匹配
                            # 简单策略：edit_X_vY 对应 version Y
                            if f"_v{vp_version}" in branch_name:
                                target_branch = branch_name
                                break
                        # 如果没找到，使用 edit_turn_vVersion 格式查找
                        if not target_branch:
                            candidate = f"edit_{vp_turn}_v{vp_version}"
                            if candidate in tree.get("branches", {}):
                                target_branch = candidate
                    
                    logger.info(f"🌳 [History] version_path={version_path} -> target_branch={target_branch}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to parse version_path {version_path}: {e}")
        
        # 🆕 根据分支获取该分支的 turns 列表
        branch_turns = None
        if target_branch and tree.get("branches"):
            branch_info = tree["branches"].get(target_branch, {})
            branch_turns = set(branch_info.get("turns", []))
            
            # 如果是子分支，需要包含父分支 fork_from_turn 之前的 turns
            parent_branch = branch_info.get("parent_branch")
            fork_from_turn = branch_info.get("fork_from_turn")
            
            if parent_branch and fork_from_turn:
                # 获取父分支的 turns（只取 fork 点之前的）
                parent_turns = tree["branches"].get(parent_branch, {}).get("turns", [])
                for pt in parent_turns:
                    if pt < fork_from_turn:
                        branch_turns.add(pt)
                # 同时包含 fork 点本身（但使用当前分支的版本）
                branch_turns.add(fork_from_turn)
            
            logger.info(f"🌳 [History] Branch '{target_branch}' turns: {branch_turns}")
        
        # 🆕 构建新格式的 chat_data（按 turn + user_message 分组，包含 answerList）
        # 格式: [{turn, user_message, action, answerList: [{version_id, assistant_message, feedback}], parent_version_id}, ...]
        chat_data = []
        
        # 按 turn 顺序处理
        sorted_turns = sorted(turn_versions.keys(), key=lambda x: int(x))
        
        # 用于追踪每个 turn 的最后一个版本 ID（用于计算 parent_version_id）
        last_version_by_turn = {}
        
        for turn_key in sorted_turns:
            turn_num = int(turn_key)
            
            # 🆕 如果指定了分支，跳过不属于该分支的 turns
            if branch_turns is not None and turn_num not in branch_turns:
                logger.debug(f"🌳 [History] Skipping turn {turn_num} (not in branch_turns)")
                continue
            
            version_data = turn_versions[turn_key]
            versions = version_data["versions"]
            
            # 🆕 如果指定了分支，过滤该 turn 的版本
            filtered_versions = versions
            if target_branch and tree.get("turns", {}).get(str(turn_num), {}).get("versions"):
                turn_branch_versions = tree["turns"][str(turn_num)]["versions"]
                # 只保留属于目标分支的版本
                if target_branch in turn_branch_versions:
                    # 找到该分支对应的 version_id
                    branch_user_msg = turn_branch_versions[target_branch].get("user_message")
                    if branch_user_msg:
                        filtered_versions = [v for v in versions if v.get("user_message") == branch_user_msg]
                        if not filtered_versions:
                            filtered_versions = versions  # Fallback
            
            # 按 user_message 分组（同一 turn 下可能有不同的问题版本，如 edit）
            message_groups = {}
            for v in filtered_versions:
                msg = v.get("user_message", "")
                if msg not in message_groups:
                    message_groups[msg] = {
                        "versions": [],
                        "first_action": v.get("action", "original"),
                        "first_version_id": v.get("version_id"),
                        "first_timestamp": v.get("timestamp"),
                        "is_original": v.get("is_original", False)
                    }
                message_groups[msg]["versions"].append(v)
            
            # 为每个 user_message 创建一条记录
            for msg, group in message_groups.items():
                # 构建 answerList
                answer_list = []
                for v in sorted(group["versions"], key=lambda x: x.get("version_id", 0)):
                    ver_id = v.get("version_id")
                    fb_key = f"{turn_num}_{ver_id}"
                    
                    answer_list.append({
                        "version_id": ver_id,
                        "version_path": f"{turn_num}:{ver_id}",  # 🆕 格式: "turn:version_id"
                        "feedback": feedback_map.get(fb_key),
                        "assistant_message": v.get("assistant_message", ""),
                        "action": v.get("action", "original"),
                        "timestamp": v.get("timestamp")
                    })
                
                # 计算 parent_version_id 和 parent_version_path
                parent_version_id = None
                parent_version_path = None
                if turn_num > 1:
                    # 🆕 从 tree.json 和分支信息中计算正确的 parent 关系
                    if branch_turns:
                        # 在当前分支中找上一个 turn
                        prev_turns_in_branch = [t for t in branch_turns if t < turn_num]
                        if prev_turns_in_branch:
                            prev_turn = max(prev_turns_in_branch)
                            
                            # 确定上一个 turn 的版本 ID
                            if target_branch and target_branch != "main":
                                # 子分支：检查上一个 turn 是否属于当前分支或父分支
                                branch_info = tree.get("branches", {}).get(target_branch, {})
                                fork_from_turn = branch_info.get("fork_from_turn")
                                
                                if prev_turn == fork_from_turn:
                                    # 上一个 turn 是 fork 点，使用当前分支的版本
                                    prev_turn_versions = tree.get("turns", {}).get(str(prev_turn), {}).get("versions", {})
                                    if target_branch in prev_turn_versions:
                                        # 计算版本号（基于分支名称）
                                        parent_version_id = int(target_branch.split("_v")[-1]) if "_v" in target_branch else 2
                                    else:
                                        parent_version_id = 1
                                else:
                                    # 上一个 turn 是分支独有的，版本 ID 为 1
                                    parent_version_id = 1
                            else:
                                # main 分支：版本 ID 始终为 1
                                parent_version_id = 1
                            
                            parent_version_path = f"{prev_turn}:{parent_version_id}"
                    
                    # Fallback: 使用简单的上一个 turn
                    if not parent_version_path:
                        prev_turn = str(turn_num - 1)
                        if prev_turn in last_version_by_turn:
                            parent_version_id = last_version_by_turn[prev_turn]
                            parent_version_path = f"{int(prev_turn)}:{parent_version_id}"  # 🆕 格式: "turn:version_id"
                
                # 第一个版本的 version_path 作为这条记录的默认 path
                first_version_path = f"{turn_num}:{group['first_version_id']}"
                
                chat_data.append({
                    "turn": turn_num,
                    "timestamp": group["first_timestamp"],
                    "user_message": msg,
                    "action": group["first_action"],
                    "version_path": first_version_path,  # 🆕 这条记录的第一个版本 path
                    "answerList": answer_list,
                    "is_original": group["is_original"],
                    "parent_version_id": parent_version_id,
                    "parent_version_path": parent_version_path  # 🆕 父版本的 path
                })
                
                # 更新该 turn 的最后版本 ID
                if answer_list:
                    last_version_by_turn[turn_key] = answer_list[-1]["version_id"]
        
        # 🆕 构建 version_tree（id + pid 格式，方便前端追溯父子关系）
        # 格式: [{"id": "1_v1", "pid": "0", "turn": 1, "version_id": 1, "label": "用户消息", "action": "original"}, ...]
        version_tree = []
        
        for turn_key in sorted_turns:
            turn_num = int(turn_key)
            version_data = turn_versions[turn_key]
            
            for v in version_data["versions"]:
                ver_id = v["version_id"]
                node_id = f"{turn_num}_v{ver_id}"
                
                # 计算 pid（父节点 ID）
                # 规则：
                # - Turn 1 v1 (original): pid = "0"（根节点）
                # - Turn 1 v2+ (edit/regenerate): pid = 同 turn 的前一个版本
                # - Turn N (N>1) 的 v1: pid = 上一个 turn 的最新版本
                # - Turn N 的 v2+（edit/regenerate）: pid = 同 turn 的前一个版本
                if turn_num == 1 and ver_id == 1:
                    # Turn 1 v1 是根节点
                    pid = "0"
                elif ver_id > 1:
                    # 任何 turn 的 v2+: 基于同 turn 的前一个版本
                    pid = f"{turn_num}_v{ver_id - 1}"
                else:  # turn_num > 1 and ver_id == 1
                    # Turn N 的 v1: 基于上一个 turn 的最新版本
                    prev_turn = str(turn_num - 1)
                    if prev_turn in turn_versions:
                        prev_versions = turn_versions[prev_turn]["versions"]
                        prev_latest = max(prev_versions, key=lambda x: x["version_id"])
                        pid = f"{turn_num - 1}_v{prev_latest['version_id']}"
                    else:
                        pid = "0"
                
                version_tree.append({
                    "id": node_id,
                    "pid": pid,
                    "turn": turn_num,
                    "version_id": ver_id,
                    "label": v["user_message"][:30] + "..." if len(v.get("user_message", "")) > 30 else v.get("user_message", ""),
                    "action": v.get("action", "original"),
                    "is_original": v.get("is_original", False),
                    "timestamp": v.get("timestamp")
                })
        
        return {
            "code": 0,
            "msg": "Success",
            "data": {
                "question_id": question_id,
                "answer_id": answer_id,
                "session_id": session_id,
                "user_id": user_id,
                # 🆕 新格式：按 turn + user_message 分组，包含 answerList 和 version_path
                "chat_data": chat_data,
                "total": len(chat_data),
                "has_versions": len(turn_versions) > 0
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
            
            if should_fetch_context and qid:
                # 🆕 API 支持两种格式：slug（如 4merhtg）和数字 ID（如 10040632384）
                logger.info(f"🆕 [StudyX SSE] Fetching question context (qid={qid}, action={action_type_hint}, turns={existing_turns}, env={environment})...")
                from app.api.external import fetch_question_context_from_studyx, get_question_context_error_hint
                question_context, error_type = await fetch_question_context_from_studyx(qid, token, environment)
                if question_context:
                    logger.info(f"✅ [StudyX SSE] Question context fetched: {len(question_context)} chars")
                elif error_type:
                    # 🆕 获取失败时，添加友好的错误提示到上下文
                    error_hint = get_question_context_error_hint(error_type, language)
                    question_context = error_hint
                    logger.warning(f"⚠️ [StudyX SSE] Failed to fetch question context, error_type={error_type}")
        
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


# ============= 🆕 Feedback 接口 =============

@router.post("/feedback")
async def submit_feedback(
    request: Request,
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
):
    """
    📝 提交反馈（点赞/踩）
    
    前端字段兼容:
    - turn_id 或 turn_number: 对话轮次
    - feedback_type: 1=like, 2=dislike, "like", "dislike", "cancel"
    - question_id, answer_id: 可选（从 session_id 推断）
    - branch: 🌳 分支名称（可选，用于标识反馈属于哪个分支）
    """
    from pathlib import Path
    
    # 🆕 手动解析请求体，兼容各种字段名
    body = await request.json()
    logger.info(f"📥 Feedback request body: {body}")
    
    user_id = body.get("user_id")
    if not user_id:
        return {"code": 400, "msg": "user_id is required", "data": None}
    
    # 兼容 turn_id 和 turn_number
    turn_id = body.get("turn_id") or body.get("turn_number")
    if not turn_id:
        return {"code": 400, "msg": "turn_id or turn_number is required", "data": None}
    turn_id = int(turn_id)
    
    # 🆕 版本 ID（用于区分同一 turn 的不同版本）
    version_id = body.get("version_id", 1)
    try:
        version_id = int(version_id)
    except:
        version_id = 1
    
    # 🌳 分支参数
    branch = body.get("branch", "main")
    
    # 兼容 feedback_type 数字和字符串
    raw_feedback = body.get("feedback_type")
    if isinstance(raw_feedback, int):
        # 数字转字符串: 1=like, 2=dislike, 0=cancel
        feedback_type_map = {1: "like", 2: "dislike", 0: "cancel", -1: "cancel"}
        feedback_type = feedback_type_map.get(raw_feedback, "like")
    else:
        feedback_type = str(raw_feedback) if raw_feedback else "like"
    
    # 兼容 question_id/answer_id 缺失的情况
    question_id = body.get("question_id") or body.get("aiQuestionId")
    answer_id = body.get("answer_id") or body.get("answerId")
    session_id = body.get("session_id")
    
    # 如果没有 session_id，从 question_id 和 answer_id 构造
    if not session_id:
        if question_id and answer_id:
            session_id = f"q{question_id}_a{answer_id}"
        else:
            return {"code": 400, "msg": "session_id or (question_id + answer_id) is required", "data": None}
    
    reason = body.get("reason")
    detail = body.get("detail")
    
    try:
        # 获取 feedback 存储目录
        feedback_dir = Path("feedback")
        if not feedback_dir.exists():
            feedback_dir = Path("backend/feedback")
        if not feedback_dir.exists():
            feedback_dir = Path("/root/usr/skill_agent_demo/backend/feedback")
        feedback_dir.mkdir(parents=True, exist_ok=True)
        
        user_feedback_file = feedback_dir / f"{user_id}_feedback.json"
        
        # 读取现有反馈
        existing_feedback = []
        if user_feedback_file.exists():
            try:
                existing_feedback = json.loads(user_feedback_file.read_text(encoding='utf-8'))
            except:
                existing_feedback = []
        
        # 🆕 查找是否已有该 turn + version_id 的反馈
        feedback_key = f"{session_id}_{turn_id}_v{version_id}"
        found_idx = None
        for i, fb in enumerate(existing_feedback):
            # 🆕 匹配 session + turn + version_id
            fb_version = fb.get("version_id", 1)
            if fb.get("session_id") == session_id and fb.get("turn_number") == turn_id and fb_version == version_id:
                found_idx = i
                break
        
        if feedback_type == "cancel":
            # 取消反馈：删除现有记录
            if found_idx is not None:
                existing_feedback.pop(found_idx)
                logger.info(f"🗑️ Feedback cancelled: {feedback_key}")
        else:
            # 创建/更新反馈
            feedback_data = {
                "feedback_id": f"fb_{feedback_key}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "user_id": user_id,
                "session_id": session_id,
                "branch": branch,
                "turn_number": turn_id,
                "version_id": version_id,  # 🆕 保存版本 ID
                "feedback_type": feedback_type,
                "reason": reason,
                "detail": detail,
                "timestamp": datetime.now().isoformat()
            }
            
            if found_idx is not None:
                # 更新现有反馈
                existing_feedback[found_idx] = feedback_data
                logger.info(f"🔄 Feedback updated: {feedback_key} -> {feedback_type}")
            else:
                # 新增反馈
                existing_feedback.append(feedback_data)
                logger.info(f"✅ Feedback submitted: {feedback_key} -> {feedback_type}")
        
        # 写回文件
        user_feedback_file.write_text(
            json.dumps(existing_feedback, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        
        return {
            "code": 0,
            "msg": "Success",
            "data": {
                "session_id": session_id,
                "turn_id": turn_id,
                "version_id": version_id,  # 🆕 返回版本 ID
                "branch": branch,
                "feedback_type": feedback_type,
                "action": "cancelled" if feedback_type == "cancel" else "saved"
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to submit feedback: {e}")
        return {
            "code": 500,
            "msg": f"Failed: {str(e)}",
            "data": None
        }


@router.get("/feedback")
async def get_feedback(
    user_id: str = Query(..., description="用户 ID"),
    question_id: str = Query(..., alias="aiQuestionId", description="题目 ID"),
    answer_id: str = Query(..., alias="answerId", description="答案 ID"),
    turn_id: Optional[int] = Query(None, description="指定轮次（不传则返回全部）")
):
    """
    📜 获取反馈状态
    """
    from pathlib import Path
    
    session_id = f"q{question_id}_a{answer_id}"
    
    try:
        feedback_dir = Path("feedback")
        if not feedback_dir.exists():
            feedback_dir = Path("backend/feedback")
        if not feedback_dir.exists():
            feedback_dir = Path("/root/usr/skill_agent_demo/backend/feedback")
        
        user_feedback_file = feedback_dir / f"{user_id}_feedback.json"
        
        if not user_feedback_file.exists():
            return {
                "code": 0,
                "msg": "Success",
                "data": {
                    "session_id": session_id,
                    "feedbacks": []
                }
            }
        
        all_feedback = json.loads(user_feedback_file.read_text(encoding='utf-8'))
        
        # 筛选当前 session
        session_feedback = [
            fb for fb in all_feedback 
            if fb.get("session_id") == session_id
        ]
        
        # 如果指定了 turn_id，进一步筛选
        if turn_id is not None:
            session_feedback = [
                fb for fb in session_feedback
                if fb.get("turn_number") == turn_id
            ]
        
        return {
            "code": 0,
            "msg": "Success",
            "data": {
                "session_id": session_id,
                "feedbacks": session_feedback
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get feedback: {e}")
        return {
            "code": 500,
            "msg": f"Failed: {str(e)}",
            "data": None
        }
