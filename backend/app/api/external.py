"""
External API - 外部服务接口（薄封装层）

暴露 Quiz 和 Flashcard 的 API 接口给外部前端开发人员
内部调用完整的 skill 框架流程：
  Intent Router → Skill Orchestrator → Memory Manager → MD 存储

这不是独立的 API，而是对现有 /api/agent/chat 流程的简化封装，
专门为需要获取结构化 JSON 的前端开发人员设计。

支持附件上传到 GCS (gs://kimi-dev/)
"""
import logging
import time
import re
import json
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Header, Query
from pydantic import BaseModel, Field

from app.core import SkillOrchestrator, MemoryManager
from app.core.intent_router import IntentRouter
from app.core.request_context import set_user_api_token, clear_user_api_token
from app.dependencies import get_memory_manager
from app.services.token_stats_service import get_token_stats_service
from app.services.memory_token_tracker import get_memory_token_tracker

logger = logging.getLogger(__name__)


# ============= 🔒 并发控制（App 端） =============

# Per-session 锁，防止同一会话的并发修改
_session_locks: Dict[str, asyncio.Lock] = {}
_lock_manager_lock = asyncio.Lock()


async def get_session_lock(session_id: str) -> asyncio.Lock:
    """获取或创建 session 级别的锁"""
    async with _lock_manager_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = asyncio.Lock()
        return _session_locks[session_id]


async def cleanup_session_lock(session_id: str):
    """清理不再使用的锁（可选，防止内存泄漏）"""
    async with _lock_manager_lock:
        if session_id in _session_locks:
            lock = _session_locks[session_id]
            if not lock.locked():
                del _session_locks[session_id]


# ============= 🆕 环境配置 =============

# 根据 environment header 选择 API 基地址
STUDYX_API_HOSTS = {
    "dev": "https://test.istudyx.com",
    "test": "https://test.istudyx.com", 
    "prod": "https://mapp.studyxapp.com",  # 生产环境 (App 端)
}

def get_studyx_api_host(environment: str = "test") -> str:
    """根据 environment 获取 StudyX API 基地址"""
    return STUDYX_API_HOSTS.get(environment, STUDYX_API_HOSTS["test"])

def get_studyx_lang_api(environment: str = "test") -> str:
    """获取用户语言 API 地址"""
    return f"{get_studyx_api_host(environment)}/api/studyx/v5/cloud/ai/getLangByUserId"

def get_studyx_question_api(environment: str = "test") -> str:
    """获取题目详情 API 地址"""
    return f"{get_studyx_api_host(environment)}/api/studyx/v5/cloud/ai/newQueryQuestionInfo"

# ============= 🆕 用户语言设置获取 =============

# StudyX API 获取用户语言设置（默认测试环境，兼容旧代码）
STUDYX_LANG_API = "https://test.istudyx.com/api/studyx/v5/cloud/ai/getLangByUserId"

# qLang 到 language code 的映射
QLANG_TO_CODE = {
    # 自动检测
    "Detect input": "auto",
    "Automatic": "auto",
    "Auto": "auto",
    # 英语
    "English": "en",
    # 中文 - 支持多种写法
    "简体中文": "zh",
    "Simplified Chinese": "zh",
    "Chinese": "zh",
    "Chinese (Simplified)": "zh",
    "繁體中文": "zh-TW",
    "Traditional Chinese": "zh-TW",
    "Chinese (Traditional)": "zh-TW",
    # 日语
    "日本語": "ja",
    "Japanese": "ja",
    # 韩语
    "한국어": "ko",
    "Korean": "ko",
    # 法语
    "Français": "fr",
    "French": "fr",
    # 西班牙语
    "Español": "es",
    "Spanish": "es",
    # 葡萄牙语
    "Português": "pt",
    "Portuguese": "pt",
    # 德语
    "Deutsch": "de",
    "German": "de",
    # 意大利语
    "Italiano": "it",
    "Italian": "it",
    # 俄语
    "Русский": "ru",
    "Russian": "ru",
    # 越南语
    "Tiếng Việt": "vi",
    "Vietnamese": "vi",
    # 泰语
    "ภาษาไทย": "th",
    "Thai": "th",
    # 印地语
    "हिंदी": "hi",
    "Hindi": "hi",
    # 印尼语
    "Bahasa Indonesia": "id",
    "Indonesian": "id",
    # 马来语
    "Melayu": "ms",
    "Malay": "ms",
    # 土耳其语
    "Türkçe": "tr",
    "Turkish": "tr",
    # 波兰语
    "Polski": "pl",
    "Polish": "pl",
    # 荷兰语
    "Nederlands": "nl",
    "Dutch": "nl",
    # 罗马尼亚语
    "Română": "ro",
    "Romanian": "ro",
    # 捷克语
    "Čeština": "cs",
    "Czech": "cs",
    # 斯洛伐克语
    "Slovenčina": "sk",
    "Slovak": "sk",
    # 匈牙利语
    "Magyar": "hu",
    "Hungarian": "hu",
    # 菲律宾语
    "Tagalog/Filipino": "tl",
    "Filipino": "tl",
    "Tagalog": "tl",
    # 北欧语言
    "Norwegian": "no",
    "Danish/Dansk": "da",
    "Danish": "da",
    "Finnish/Suomi": "fi",
    "Finnish": "fi",
}


async def get_user_language_from_studyx(token: str, environment: str = "test") -> str:
    """
    从 StudyX API 获取用户的语言设置
    
    Args:
        token: 用户登录 token
        environment: 环境标识 (dev/test/prod)
    
    Returns:
        str: 语言代码 (en, zh, ja, auto 等)
    """
    if not token:
        logger.warning("⚠️ No token provided, using auto language detection")
        return "auto"
    
    try:
        # 🆕 根据 environment 选择 API 地址
        api_url = get_studyx_lang_api(environment)
        logger.info(f"🌐 Getting user language from: {api_url} (env={environment})")
        
        async with aiohttp.ClientSession() as session:
            headers = {"token": token}
            async with session.get(api_url, headers=headers, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"🌐 StudyX language API response: code={data.get('code')}, data={data.get('data')}, msg={data.get('msg')}")
                    
                    if data.get("code") == 0 and data.get("data"):
                        qlang = data["data"].get("qlang", "English")
                        lang_code = QLANG_TO_CODE.get(qlang, "auto")
                        logger.info(f"🌐 User language from StudyX: {qlang} → {lang_code}")
                        return lang_code
                    elif data.get("code") == -1 and "no user preferences" in data.get("msg", "").lower():
                        # 🆕 用户没有设置语言偏好（code=-1），返回默认英语
                        logger.info(f"🌐 User has no language preference set (code=-1), using default: en")
                        return "en"
                    elif data.get("code") == 0 and not data.get("data"):
                        # 用户没有设置语言偏好（data 为空），返回默认英语
                        logger.info(f"🌐 User has no language preference set (empty data), using default: en")
                        return "en"
                    else:
                        logger.warning(f"⚠️ StudyX API returned error: code={data.get('code')}, msg={data.get('msg')}")
                else:
                    logger.warning(f"⚠️ StudyX API HTTP error: {response.status}")
    except asyncio.TimeoutError:
        logger.warning("⚠️ StudyX language API timeout, using auto")
    except Exception as e:
        logger.warning(f"⚠️ Failed to get user language from StudyX: {e}")
    
    return "auto"


# ============= 🆕 题目上下文获取 =============

# StudyX API 获取题目详情（默认测试环境，兼容旧代码）
STUDYX_QUESTION_INFO_API = "https://test.istudyx.com/api/studyx/v5/cloud/ai/newQueryQuestionInfo"


async def fetch_question_context_from_studyx(qid: str, token: str, environment: str = "test") -> Optional[str]:
    """
    从 StudyX API 获取题目上下文
    
    Args:
        qid: 题目 slug (如 96rhhg4)
        token: 用户登录 token
        environment: 环境标识 (dev/test/prod)
    
    Returns:
        str: 题目上下文文本，格式为:
            Question: <题目内容>
            Answer: <答案内容>
            
        如果获取失败返回 None
    """
    if not qid or not token:
        logger.warning(f"⚠️ Missing qid or token for question context fetch")
        return None
    
    try:
        # 🆕 根据 environment 选择 API 地址
        api_url = get_studyx_question_api(environment)
        logger.info(f"📡 Fetching question context from: {api_url} (env={environment}, qid={qid})")
        
        async with aiohttp.ClientSession() as session:
            headers = {"token": token}
            params = {"id": qid, "type": "3", "routeType": "1"}
            
            async with session.get(
                api_url, 
                headers=headers, 
                params=params,
                timeout=10
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"📡 StudyX question API response: code={data.get('code')}, msg={data.get('msg')}")
                    if data.get("code") == 0 and data.get("data"):
                        qnt_info = data["data"].get("qntInfo", {})
                        
                        # 提取题目文本（优先使用 questionText，其次 imgText）
                        question_text = qnt_info.get("questionText") or qnt_info.get("imgText") or ""
                        
                        # 提取答案文本
                        answer_list = qnt_info.get("answerList", [])
                        answer_text = ""
                        if answer_list:
                            # 获取第一个答案的内容
                            first_answer = answer_list[0]
                            answer_text = first_answer.get("answerText", "")
                        
                        if question_text or answer_text:
                            context_parts = []
                            if question_text:
                                context_parts.append(f"Question:\n{question_text}")
                            if answer_text:
                                # 截取答案，避免太长（保留前2000字符）
                                if len(answer_text) > 2000:
                                    answer_text = answer_text[:2000] + "...(truncated)"
                                context_parts.append(f"Answer/Solution:\n{answer_text}")
                            
                            context = "\n\n".join(context_parts)
                            logger.info(f"✅ Fetched question context: qid={qid}, len={len(context)}")
                            return context
                        else:
                            logger.warning(f"⚠️ Empty question context for qid={qid}")
                    else:
                        logger.warning(f"⚠️ StudyX question API error: {data.get('msg')}")
                else:
                    logger.warning(f"⚠️ StudyX question API HTTP error: {response.status}")
    except asyncio.TimeoutError:
        logger.warning(f"⚠️ StudyX question API timeout for qid={qid}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to fetch question context: {e}")
    
    return None


router = APIRouter(prefix="/api/external", tags=["external"])


# ============= 数量提取逻辑 =============

CHINESE_NUMBERS = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '两': 2, '几': 3
}


def extract_quantity_from_text(text: str, skill_type: str = "quiz") -> Optional[int]:
    """从文本中提取数量"""
    if skill_type == "quiz":
        unit_pattern = r'[道个份题]'
    else:
        unit_pattern = r'[张个份卡]'
    
    # 阿拉伯数字
    arabic_match = re.search(rf'(\d+)\s*{unit_pattern}', text)
    if arabic_match:
        return int(arabic_match.group(1))
    
    # 中文数字
    chinese_match = re.search(rf'([一二三四五六七八九十两几])\s*{unit_pattern}', text)
    if chinese_match:
        return CHINESE_NUMBERS.get(chinese_match.group(1))
    
    return None


# ============= Dependency =============

def get_skill_orchestrator(
    memory_manager: MemoryManager = Depends(get_memory_manager)
) -> SkillOrchestrator:
    """获取 SkillOrchestrator 实例"""
    return SkillOrchestrator(memory_manager=memory_manager)


# ============= Request/Response Models =============

class InputItem(BaseModel):
    """输入项 - 支持文本和文件 URI"""
    text: Optional[str] = Field(None, description="输入文本内容")
    fileUri: Optional[str] = Field(None, description="GCS 文件 URI (gs://kimi-dev/...)")


class ExternalRequest(BaseModel):
    """外部 API 请求格式（Flashcard/Quiz 专用）"""
    inputList: List[InputItem] = Field(..., description="输入列表（支持 text 和 fileUri）")
    cardSize: Optional[int] = Field(None, description="闪卡数量（可选，会自动从 text 中提取）")
    questionCount: Optional[int] = Field(None, description="题目数量（可选，会自动从 text 中提取）")
    outLanguage: Optional[str] = Field(None, description="输出语言")
    user_id: Optional[str] = Field("anonymous", description="用户ID")
    session_id: Optional[str] = Field(None, description="会话ID（不传则自动生成）")


class FileInfo(BaseModel):
    """
    统一的文件信息结构 - 支持图片和文档混合上传
    
    用于请求和响应中的文件信息回显
    """
    type: str = Field(..., description="文件类型: image 或 document")
    url: Optional[str] = Field(None, description="文件的 HTTP URL（图片必填，文档可选）")
    name: Optional[str] = Field(None, description="文件名（文档必填，图片可选）")
    
    class Config:
        json_schema_extra = {
            "examples": [
                {"type": "image", "url": "https://cdn.studyx.com/img.jpg"},
                {"type": "document", "name": "数学笔记.pdf", "url": "https://cdn.studyx.com/doc.pdf"}
            ]
        }


class ChatRequest(BaseModel):
    """
    通用聊天请求格式 - 支持多附件和引用文本
    
    两种使用场景：
    
    场景 A - 引用文本模式（点击步骤的 ? 按钮）：
        - referenced_text: 必填，用户选中的文本
        - message: 必填，用户的问题（UI 强制要求输入）
        
    场景 B - 快捷按钮模式（Explain/Make simpler/Common mistakes）：
        - action_type: 必填，快捷操作类型
        - message: 可选，不填则使用默认提示
    
    题目关联：
        - question_id: 题目 ID（aiQuestionId）
        - answer_id: 答案 ID（用户答题记录 ID）
        
    文件上传：
        - file_uris: GCS 文件 URI（AI 处理用）
        - files: 统一的文件信息数组（前端回显用，支持多图片+多文档混合）
    """
    message: str = Field("", description="用户消息（引用文本模式下必填）")
    file_uri: Optional[str] = Field(None, description="单个 GCS 文件 URI（兼容旧版）")
    file_uris: Optional[List[str]] = Field(None, description="多个 GCS 文件 URI 数组（AI 处理用）")
    # 🆕 统一的文件信息数组 - 支持多图片+多文档混合上传
    files: Optional[List[FileInfo]] = Field(None, description="文件信息数组（前端回显用）")
    # 兼容旧版单文件字段（将被 files 替代）
    file_url: Optional[str] = Field(None, description="[兼容] 单个图片 HTTP URL")
    file_name: Optional[str] = Field(None, description="[兼容] 单个文档文件名")
    user_id: Optional[str] = Field("anonymous", description="用户ID")
    session_id: Optional[str] = Field(None, description="会话ID（不传则自动生成，优先使用 question_id+answer_id）")
    # 🆕 题目关联 - 聊天历史与题目绑定
    question_id: Optional[str] = Field(None, description="题目 ID (aiQuestionId)")
    answer_id: Optional[str] = Field(None, description="答案 ID (answerId)")
    # 🆕 引用文本支持 - 用户从文档中选中的内容（点击 ? 按钮触发）
    referenced_text: Optional[str] = Field(None, description="引用的文本内容（当提供时，message 必填）")
    # 🆕 快捷操作类型 - 独立的快捷按钮功能
    action_type: Optional[str] = Field(None, description="快捷操作: explain_concept, make_simpler, common_mistakes")
    # 🆕 语言设置 - 控制回复语言（支持多语言）
    # 支持: auto(自动检测), en(英文), zh/zh-CN(简体中文), zh-TW(繁体中文), 
    # ja(日语), ko(韩语), fr(法语), es(西班牙语), pt(葡萄牙语), de(德语), 
    # it(意大利语), ru(俄语), vi(越南语), th(泰语), hi(印地语), id(印尼语),
    # ms(马来语), tr(土耳其语), pl(波兰语), nl(荷兰语), ro(罗马尼亚语),
    # cs(捷克语), sk(斯洛伐克语), hu(匈牙利语), tl(菲律宾语), no(挪威语),
    # da(丹麦语), fi(芬兰语)
    language: Optional[str] = Field(None, description="回复语言: 不传则自动从用户设置获取; 可选值: auto, en, zh, zh-TW, ja, ko, fr, es, pt, de, it, ru, vi, th 等")
    # 🆕 题目上下文 - 用于新 session 时提供题目内容
    qid: Optional[str] = Field(None, description="题目 slug（从 URL 获取，如 96rhhg4），用于自动获取题目上下文")
    resource_id: Optional[str] = Field(None, description="题目资源 ID（与 qid 作用相同，前端可用此字段）")  # 🆕 兼容前端字段名
    # 🆕 直接传入题目上下文（如果前端已有，可直接传入，避免后端再调 API）
    question_context: Optional[str] = Field(None, description="题目上下文文本（包含题目和答案，前端直接传入时优先使用）")


# ============= 核心执行函数（复用 skill 框架） =============

async def execute_skill_pipeline(
    message: str,
    user_id: str,
    session_id: str,
    orchestrator: SkillOrchestrator,
    quantity_override: Optional[int] = None,
    skill_hint: Optional[str] = None,
    file_uris: Optional[List[str]] = None,
    referenced_text: Optional[str] = None,  # 🆕 引用文本
    action_type: Optional[str] = None,  # 🆕 快捷操作类型
    files: Optional[List[Dict[str, Any]]] = None,  # 🆕 统一的文件信息数组
    # 兼容旧版单文件字段
    file_url: Optional[str] = None,
    file_name: Optional[str] = None,
    # 🆕 语言设置
    language: str = "en",
    # 🆕 题目上下文（从 StudyX 获取的原始题目和答案）
    question_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    执行完整的 skill 框架流程
    
    这是对 /api/agent/chat 核心逻辑的复用，包括：
    1. Memory 检索
    2. Intent Router 解析
    3. Skill 执行
    4. Memory 更新 & MD 存储
    
    Args:
        message: 用户消息
        user_id: 用户 ID
        session_id: 会话 ID
        orchestrator: SkillOrchestrator 实例
        quantity_override: 覆盖数量（如果用户显式传了参数）
        skill_hint: 技能提示（"quiz" 或 "flashcard"）
        file_uris: GCS 文件 URI 列表（可选，支持多文件）
        files: 统一的文件信息数组（用于前端回显）
        file_url: [兼容] 单个图片 HTTP URL
        file_name: [兼容] 单个文档文件名
    
    Returns:
        执行结果（包含 token_usage 统计）
    """
    start_time = time.time()
    
    # 🆕 保存原始消息用于 Intent Router（不被 referenced_text 干扰）
    original_message = message
    enhanced_message = message
    context_prefix = ""
    
    # 🆕 处理快捷操作 - 将 UI 按钮映射到具体指令（支持多语言）
    if action_type:
        # 多语言 action 映射
        action_mapping_en = {
            "explain_concept": "Please explain this concept in detail",
            "make_simpler": "Please explain this in a simpler way that's easier to understand",
            "common_mistakes": "What are the common mistakes or misconceptions about this topic? Please list and explain them",
        }
        action_mapping_zh = {
            "explain_concept": "请详细解释这个概念",
            "make_simpler": "请用更简单易懂的方式解释这个内容",
            "common_mistakes": "这个知识点有哪些常见错误或误区？请列举说明",
        }
        
        # 根据语言选择 action 映射
        if language == "zh":
            action_mapping = action_mapping_zh
            default_action = "请帮我理解这个内容"
        else:
            action_mapping = action_mapping_en
            default_action = "Please help me understand this content"
        
        action_prompt = action_mapping.get(action_type, default_action)
        if not message.strip():
            enhanced_message = action_prompt
            original_message = action_prompt  # 快捷操作也需要更新原始消息
        else:
            enhanced_message = f"{message}, {action_prompt}" if language == "en" else f"{message}，{action_prompt}"
        logger.info(f"⚡ Quick action: {action_type} (lang={language})")
    
    # 🆕 处理题目上下文 - 新 session 时从 StudyX 获取的原始题目和答案
    # 这个上下文帮助 AI 理解 "here" "this question" 等指代词
    if question_context:
        context_prefix = f"[Current Question Context]\n{question_context}\n\n[User Message]\n"
        logger.info(f"📚 Question context attached: {len(question_context)} chars")
    
    # 🆕 处理引用文本 - 将用户选中的文本作为上下文
    # 注意：referenced_text 只添加到最终执行消息，不影响 Intent Router
    if referenced_text:
        ref_prefix = f"Based on this content:\n\"\"\"\n{referenced_text}\n\"\"\"\n\n"
        context_prefix = context_prefix + ref_prefix if context_prefix else ref_prefix
        logger.info(f"📎 Referenced text attached: {len(referenced_text)} chars")
    
    # 组合最终执行消息（用于 Skill 执行）
    execution_message = context_prefix + enhanced_message if context_prefix else enhanced_message
    
    # Intent Router 使用原始消息，Skill 执行使用增强消息
    intent_parse_message = original_message  # 🔥 关键：Intent Router 不被 referenced_text 干扰
    logger.info(f"📝 Intent parse message: {intent_parse_message[:50]}...")
    logger.info(f"📝 Execution message: {execution_message[:80]}...")
    
    # 🆕 初始化 Token 使用统计（暴露给外部）
    token_usage = {
        "intent_router": {
            "method": "skill_registry",  # "skill_registry" = 0 tokens, "llm_fallback" = 有 tokens
            "tokens": 0
        },
        "skill_execution": {
            "source": "pending",  # "external_api" / "llm"
            "model": "pending",   # 具体模型名称
            "thinking_mode": False,  # 是否使用思考模式
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "thinking_tokens": 0,  # 思考 token（仅思考模型）
            "content_tokens": 0,   # 内容 token
            "generation_time": 0,  # 生成耗时（秒）
            "data_source": "pending"  # "api" 精确 / "estimated" 估算
        },
        "memory_operations": {
            "compression_tokens": 0,      # 压缩总 token
            "compression_input": 0,       # 压缩 input token（发送给 LLM）
            "compression_output": 0,      # 压缩 output token（LLM 生成）
            "summary_tokens": 0           # Memory summary 生成消耗
        },
        "total_internal_tokens": 0  # 总计（不含外部 API）
    }
    
    logger.info("="*60)
    logger.info(f"🔄 External API -> Skill Pipeline")
    logger.info(f"   • User: {user_id}")
    logger.info(f"   • Session: {session_id}")
    logger.info(f"   • Message: {message}")
    logger.info(f"   • Quantity Override: {quantity_override}")
    logger.info(f"   • Skill Hint: {skill_hint}")
    logger.info(f"   • File URIs: {file_uris if file_uris else 'N/A'}")
    logger.info("="*60)
    
    # ============= STEP 1: Memory 检索 =============
    logger.info("🔍 STEP 1: Retrieving Memory Context...")
    
    memory_summary = await orchestrator.memory_manager.generate_memory_summary(
        user_id, session_id
    )
    
    # 获取 session context
    session_context = await orchestrator.memory_manager.get_session_context(
        session_id=session_id,
        user_id=user_id
    )
    
    last_artifact_summary = "No previous interaction."
    current_topic = None
    session_topics = None
    
    if session_context:
        if hasattr(session_context, 'current_topic'):
            current_topic = session_context.current_topic
        if hasattr(session_context, 'artifact_history'):
            session_topics = [a.topic for a in session_context.artifact_history if a.topic]
        if session_context.last_artifact and session_context.last_artifact_content:
            last_artifact_summary = f"Previous: {session_context.last_artifact} about {current_topic or 'unknown'}"
    
    # 🔥 如果 session_context 没有 current_topic，尝试从 MD metadata 加载
    artifact_contents = []
    if not current_topic:
        loaded_context = await _load_session_context_from_md(
            memory_manager=orchestrator.memory_manager,
            user_id=user_id,
            session_id=session_id
        )
        if loaded_context:
            current_topic = loaded_context.get("current_topic")
            session_topics = loaded_context.get("session_topics", [])
            artifact_contents = loaded_context.get("artifact_contents", [])
            if loaded_context.get("last_artifact"):
                last_artifact_summary = f"Previous: {loaded_context['last_artifact']} about {current_topic or 'unknown'}"
            logger.info(f"📂 Loaded context from MD: current_topic={current_topic}, topics={session_topics}, artifacts={len(artifact_contents)}")
    
    # 🆕 如果从 MD 加载了 artifact_contents，注入到 session_context 供引用解析使用
    if artifact_contents:
        await _inject_artifacts_to_session(
            memory_manager=orchestrator.memory_manager,
            session_id=session_id,
            artifact_contents=artifact_contents
        )
    
    logger.info(f"✅ Memory retrieved, current_topic: {current_topic}")
    
    # ============= STEP 2: Intent Router 解析 =============
    logger.info("🧭 STEP 2: Parsing User Intent...")
    
    # 🆕 检测是否有文件附件
    has_files = file_uris and len(file_uris) > 0
    
    intent_router = IntentRouter()
    intent_results = await intent_router.parse(
        message=intent_parse_message,  # 🔥 使用原始消息，不被 referenced_text 干扰
        memory_summary=memory_summary,
        last_artifact_summary=last_artifact_summary,
        current_topic=current_topic,
        session_topics=session_topics,
        has_files=has_files  # 🆕 传递文件附件信息
    )
    
    if not intent_results:
        return {
            "success": False,
            "error": "intent_parse_failed",
            "message": "无法解析用户意图",
            "token_usage": token_usage
        }
    
    # 取第一个 intent
    intent_result = intent_results[0]
    logger.info(f"✅ Intent parsed: {intent_result.intent}, topic: {intent_result.topic}")
    
    # 🆕 收集 Intent Router 的 token 统计
    # 简单方案：如果 confidence < 0.5，说明可能使用了 LLM fallback
    if intent_result.confidence < 0.5:
        # 低置信度可能使用了 LLM fallback（Gemini）
        token_usage["intent_router"]["method"] = "llm_fallback"
        token_usage["intent_router"]["tokens"] = 150  # 估算 Gemini 使用
    else:
        # 高置信度说明使用了 0-token 的 Skill Registry
        token_usage["intent_router"]["method"] = "skill_registry"
        token_usage["intent_router"]["tokens"] = 0
    
    # ============= STEP 2.4: 🆕 处理 file_uris 的特殊情况 =============
    # 当有文件附件时，根据意图类型决定是否 override
    has_files = file_uris and len(file_uris) > 0
    if has_files:
        # 🆕 询问类/解释类 intent 不应该被 override 为 quiz/flashcard
        # 这些 intent 表示用户在询问/讨论文件内容，而不是要求生成学习内容
        non_generation_intents = {
            "contextual", "explain", "other", "help",  # 询问/解释类
            "explain_request",  # 解释请求也可能只是讨论
        }
        
        if intent_result.intent in non_generation_intents:
            # 🆕 用户在询问文件内容，转换为 "other" 让 Gemini 直接回答
            # 而不是调用 explain_skill 生成结构化解释
            logger.info(f"📎 File URIs provided ({len(file_uris)} files) with inquiry intent '{intent_result.intent}'")
            logger.info(f"📎 Converting '{intent_result.intent}' → 'other' for direct chat response")
            intent_result.intent = "other"  # 让 Gemini 直接回答
            intent_result.parameters['from_file'] = True
            intent_result.parameters['file_uris'] = file_uris
        else:
            # 🆕 如果 intent 是 other（对话/解答类），不要强制覆盖为生成类
            # "solve this question" 应该保持为 other，让 LLM 直接解答
            if intent_result.intent == "other":
                logger.info(f"📎 File URIs provided ({len(file_uris)} files) with 'other' intent, keeping as chat")
                # 保持 other intent，不覆盖
            else:
                # 生成类 intent（quiz/flashcard/notes 等）或 clarification
                needs_override = (
                    intent_result.intent == "clarification" or
                    intent_result.intent == "clarification_needed" or
                    intent_result.parameters.get('needs_clarification') or
                    not intent_result.topic
                )
                
                if needs_override:
                    # 根据 skill_hint 确定 intent，默认为 quiz
                    if skill_hint == "quiz":
                        intent_result.intent = "quiz_request"
                    elif skill_hint == "flashcard":
                        intent_result.intent = "flashcard_request"
                    else:
                        # 没有 skill_hint 时，根据消息内容推断
                        if any(kw in message for kw in ['闪卡', '卡片', 'flashcard']):
                            intent_result.intent = "flashcard_request"
                        else:
                            intent_result.intent = "quiz_request"  # 默认为 quiz
                    
                    # 🔥 关键：topic 设为空字符串，让外部 API 从文件中提取
                    intent_result.topic = ""  
                    intent_result.parameters['topic'] = ""
                    intent_result.parameters['needs_clarification'] = False
                    intent_result.parameters['from_file'] = True  # 标记来自文件
                    
                    logger.info(f"📎 File URIs provided ({len(file_uris)} files), bypassing topic check")
                    logger.info(f"📎 Override intent to: {intent_result.intent} (topic will be extracted by external API)")
    
    # ============= STEP 2.5: 检查是否需要澄清 =============
    # 当以下情况时触发澄清机制：
    # 1. confidence 较低且有多个 topics
    # 2. 检测到模糊引用（如 "那道题" 但有多个 quiz）
    # 3. intent 是 clarification（但有文件时已在上面处理）
    # 🆕 有 file_uris 时跳过澄清
    
    if not has_files and (intent_result.intent == "clarification" or (
        intent_result.confidence < 0.7 and 
        len(session_topics) > 1 and 
        intent_result.has_reference
    )):
        logger.info(f"🤔 Clarification needed: confidence={intent_result.confidence}, topics={len(session_topics)}")
        
        # 构建压缩上下文并调用 LLM 生成澄清问题
        clarification_response = await _generate_clarification(
            message=message,
            artifact_contents=artifact_contents,
            session_topics=session_topics,
            current_topic=current_topic
        )
        
        if clarification_response:
            # 保存到 MD
            await _save_chat_to_session(
                memory_manager=orchestrator.memory_manager,
                user_id=user_id,
                session_id=session_id,
                message=message,
                response_text=clarification_response,
                intent="clarification",
                current_topic=current_topic,
                files=files,
                referenced_text=referenced_text,
                file_url=file_url,
                file_name=file_name
            )
            
            # 🆕 Clarification 使用 Gemini（估算 ~200 tokens）
            token_usage["skill_execution"]["source"] = "llm_gemini"
            token_usage["skill_execution"]["total_tokens"] = 200  # 估算
            token_usage["total_internal_tokens"] = token_usage["intent_router"]["tokens"] + 200
            
            return {
                "content_type": "clarification",
                "intent": "clarification",
                "topic": current_topic or "",
                "content": {"text": clarification_response},
                "token_usage": token_usage
            }
    
    # ============= STEP 2.6: 处理特殊 intent =============
    
    # 处理 help intent
    if intent_result.intent == "help":
        help_text = """你好！我是 StudyX Agent，你的智能学习助手 🎓

我支持以下学习功能：
• 📝 练习题：「给我5道微积分的题」
• 📖 概念讲解：「解释一下什么是光合作用」
• 🎴 学习闪卡：「给我一些光合作用的闪卡」
• 📝 学习笔记：「帮我整理物理知识点」
• 🗺️ 思维导图：「画个化学反应的思维导图」

试试问我一个学习相关的问题吧！😊"""
        
        # 🔥 保存到 MD
        await _save_chat_to_session(
            memory_manager=orchestrator.memory_manager,
            user_id=user_id,
            session_id=session_id,
            message=message,
            response_text=help_text,
            intent="help",
            files=files,
            referenced_text=referenced_text,
            file_url=file_url,
            file_name=file_name
        )
        
        # 🆕 Help 不消耗 token（静态文本）
        token_usage["total_internal_tokens"] = token_usage["intent_router"]["tokens"]
        
        return {
            "content_type": "text",
            "intent": "help",
            "content": {"text": help_text},
            "token_usage": token_usage
        }
    
    # 🆕 处理 clarification / clarification_needed intent（需要澄清）- 返回引导性问题
    # 🔥 但如果有 referenced_text、question_context 或有 conversation history，跳过 clarification
    if intent_result.intent in ["clarification", "clarification_needed"]:
        # 🆕 如果有 question_context（从 StudyX 获取的题目上下文），直接跳过 clarification
        if question_context:
            logger.info(f"📚 Has question_context, bypassing clarification and using 'other' intent for chat...")
            intent_result.intent = 'other'
            intent_result.parameters['has_question_context'] = True
            # 跳过后续的 clarification 处理
        else:
            # 🆕 检查是否是 follow-up 问题（引用之前的上下文）
            followup_indicators_en = [
                'this', 'here', 'it', 'the solution', 'the problem', 'the concept',
                'the answer', 'this type', 'this kind', 'above', 'that'
            ]
            followup_indicators_zh = [
                '这个', '这道', '这里', '上面', '前面', '刚才', '这题', '这类', '那个'
            ]
            
            msg_lower = intent_parse_message.lower()
            is_followup = any(ind in msg_lower for ind in followup_indicators_en) or \
                          any(ind in intent_parse_message for ind in followup_indicators_zh)
            
            # 🆕 如果是 follow-up 问题，先加载对话历史检查是否有上下文
            has_conversation_context = False
            if is_followup and not referenced_text:
                try:
                    prev_history = await _load_conversation_history(
                        memory_manager=orchestrator.memory_manager,
                        user_id=user_id,
                        session_id=session_id,
                        max_turns=3  # 只需检查最近几轮
                    )
                    if prev_history and len(prev_history) > 0:
                        has_conversation_context = True
                        logger.info(f"📎 Follow-up question detected with {len(prev_history)//2} previous turns, bypassing clarification")
                        # 将 intent 改为 other，让 Gemini 使用上下文回答
                        intent_result.intent = 'other'
                        intent_result.parameters['is_followup'] = True
                        intent_result.parameters['context_turns'] = len(prev_history) // 2
                except Exception as e:
                    logger.warning(f"⚠️ Failed to check conversation history: {e}")
            
            if referenced_text:
                # 有引用文本时，根据原始消息重新判断 skill 意图
                logger.info(f"📎 Has referenced_text, bypassing clarification...")
                original_skill_keywords = {
                    'quiz': ['题', '出题', '道题', '选择题', '判断题', '练习', '测验', 'quiz'],
                    'flashcard': ['闪卡', '卡片', '做卡', 'flashcard', 'card'],
                    'explain': ['讲解', '解释', '说明', '详细', 'explain'],
                }
                
                # 检测原始消息中的 skill 类型
                detected_skill = None
                for skill, keywords in original_skill_keywords.items():
                    if any(kw in intent_parse_message for kw in keywords):
                        detected_skill = skill
                        break
                
                if detected_skill:
                    logger.info(f"📎 Detected skill from original message: {detected_skill}")
                    # 重写 intent_result，跳过 clarification
                    if detected_skill == 'quiz':
                        intent_result.intent = 'quiz_request'
                        intent_result.topic = "引用内容"  # 使用引用文本作为主题来源
                        intent_result.parameters['needs_clarification'] = False
                        intent_result.parameters['topic_from_reference'] = True
                    elif detected_skill == 'flashcard':
                        intent_result.intent = 'flashcard_request'
                        intent_result.topic = "引用内容"
                        intent_result.parameters['needs_clarification'] = False
                        intent_result.parameters['topic_from_reference'] = True
                    elif detected_skill == 'explain':
                        # explain 直接用 other intent + Gemini 对话
                        intent_result.intent = 'other'
                        intent_result.parameters['from_reference'] = True
                else:
                    # 无法检测到明确 skill，使用 "other" 让 Gemini 处理
                    logger.info(f"📎 No clear skill detected, using 'other' for direct chat")
                    intent_result.intent = 'other'
                    intent_result.parameters['from_reference'] = True
                # 🔥 跳过 clarification 处理，继续执行后续逻辑
            elif has_conversation_context:
                # 🆕 有对话历史上下文，已在上面将 intent 改为 'other'，跳过 clarification
                logger.info(f"📎 Follow-up with conversation context, skipping clarification")
                pass  # intent 已改为 'other'，会在后续处理
            else:
                # 没有 referenced_text，也没有对话历史，正常进入 clarification 流程
                logger.info(f"❓ Detected '{intent_result.intent}' intent, generating clarification question...")
                
                missing = intent_result.parameters.get("missing", [])
                clarification_reason = intent_result.parameters.get("clarification_reason", "")
                
                # 🆕 更丰富的引导性问题模板（支持多语言）
                if language == "en":
                    clarification_responses = {
                        "topic": "What topic would you like to learn?\n• Physics (Newton's laws, optics)\n• Chemistry (chemical bonds, reactions)\n• History (WWII, US History)\n• Biology (cells, DNA)\n\nTell me the specific topic, and I'll help you! 😊",
                        "topic_missing": "What topic would you like to learn? Tell me the specific subject or concept, such as 'photosynthesis' or 'Newton's second law', and I can help you create learning materials.",
                        "subject": "Which subject would you like to make a plan for?\n• Physics\n• Chemistry\n• Math\n• English\n\nTell me the specific subject or topic!",
                        "action": "What would you like me to help you with?\n\n• 📚 **Explain concepts** - 'Explain photosynthesis'\n• ❓ **Generate practice questions** - 'Give me 5 questions about WWII'\n• 🃏 **Create flashcards** - 'Make 3 flashcards about chemical bonds'\n• 📋 **Create study plan** - 'Help me plan physics study'\n• 🗺️ **Draw mind map** - 'Draw a mind map of Newton's laws'\n\nJust tell me what you need!",
                        "multi_topic_insufficient": "Which topics would you like to include? Please tell me the specific topic names.",
                    }
                    default_clarification = "I'm not sure what you need."
                else:
                    clarification_responses = {
                        "topic": "你想学习什么主题呢？比如：\n• 物理（牛顿定律、光学）\n• 化学（化学键、化学反应）\n• 历史（二战、中国历史）\n• 生物（细胞、DNA）\n\n告诉我具体的主题，我来帮你！😊",
                        "topic_missing": "你想学习什么主题呢？告诉我具体的学科或知识点，例如「光合作用」「牛顿第二定律」等，我可以帮你生成学习材料。",
                        "subject": "你想针对哪个学科制定计划呢？比如：\n• 物理\n• 化学\n• 数学\n• 英语\n\n告诉我具体的科目或主题吧！",
                        "action": "你希望我帮你做什么呢？我可以：\n\n• 📚 **讲解概念** - 「解释一下光合作用」\n• ❓ **生成练习题** - 「给我5道二战的题」\n• 🃏 **制作闪卡** - 「做3张化学键的闪卡」\n• 📋 **制定学习计划** - 「帮我制定物理学习计划」\n• 🗺️ **画思维导图** - 「画个牛顿定律的导图」\n\n直接告诉我你的需求！",
                        "multi_topic_insufficient": "你想要哪些主题的内容呢？请告诉我具体的主题名称。",
                    }
                    default_clarification = "我不太确定你的需求。"
                
                # 🆕 根据原因选择合适的引导问题
                clarification_text = default_clarification
                
                if clarification_reason:
                    clarification_text = clarification_responses.get(clarification_reason, clarification_text)
                elif missing:
                    # 兼容旧的 missing 参数
                    if isinstance(missing, list) and len(missing) > 0:
                        clarification_text = clarification_responses.get(missing[0], clarification_text)
                    else:
                        clarification_text = clarification_responses.get(str(missing), clarification_text)
                else:
                    # 🆕 智能默认澄清（基于用户消息内容，支持多语言）
                    if language == "en":
                        if any(kw in intent_parse_message.lower() for kw in ['learn', 'study', 'review', 'teach']):
                            clarification_text = "What would you like to learn? Tell me the specific topic, like 'physics', 'Newton's laws', or 'World War II', and I'll help you create learning materials!"
                        elif any(kw in intent_parse_message.lower() for kw in ['organize', 'summarize', 'notes']):
                            clarification_text = "What topic would you like to organize? Tell me the specific subject or content, and I'll help!"
                        elif any(kw in intent_parse_message.lower() for kw in ['plan', 'schedule', 'arrange']):
                            clarification_text = "Which subject would you like to make a study plan for? Tell me the specific subject and I'll help you plan!"
                        else:
                            clarification_text = "Hi! I'm your learning assistant. What would you like to learn?\n\nYou can:\n• Ask me questions like 'What is photosynthesis?'\n• Request quiz questions like 'Give me 3 questions about Newton's laws'\n• Create flashcards like 'Make 5 flashcards about chemical bonds'\n\nTell me what you need! 😊"
                    else:
                        if any(kw in intent_parse_message for kw in ['学习', '复习', '预习']):
                            clarification_text = "你想学习什么呢？告诉我具体的主题，比如「物理」「牛顿定律」「二战历史」等，我来帮你生成学习材料！"
                        elif any(kw in intent_parse_message for kw in ['整理', '总结', '笔记']):
                            clarification_text = "你想整理哪个主题的知识点呢？告诉我具体的学科或内容，我来帮你整理！"
                        elif any(kw in intent_parse_message for kw in ['计划', '规划', '安排']):
                            clarification_text = "你想制定哪个学科的学习计划呢？告诉我具体的科目，我来帮你规划！"
                        else:
                            clarification_text = "你好！我是学习助手。你想学习什么呢？\n\n你可以：\n• 直接问我问题，如「什么是光合作用」\n• 让我出题，如「给我3道牛顿定律的题」\n• 让我做闪卡，如「做5张化学键的闪卡」\n\n告诉我你的需求！😊"
                
                # 🔥 保存 clarification 到 MD 文件
                await _save_chat_to_session(
                    memory_manager=orchestrator.memory_manager,
                    user_id=user_id,
                    session_id=session_id,
                    message=message,
                    response_text=clarification_text,
                    intent="clarification",
                    current_topic=current_topic,
                    files=files,
                    referenced_text=referenced_text,
                    file_url=file_url,
                    file_name=file_name
                )
                
                token_usage["total_internal_tokens"] = token_usage["intent_router"]["tokens"]
                
                return {
                    "content_type": "clarification_needed",
                    "intent": "clarification",
                    "content": {"text": clarification_text},
                    "token_usage": token_usage
                }
    
    # 处理 other intent（闲聊/未识别）- 使用 Gemini 对话
    if intent_result.intent == "other":
        logger.info("💬 Detected 'other' intent, using Gemini for conversation...")
        
        try:
            # 🆕 加载对话历史（实现上下文关联）
            conversation_history = await _load_conversation_history(
                memory_manager=orchestrator.memory_manager,
                user_id=user_id,
                session_id=session_id,
                max_turns=6  # 加载最近6轮对话
            )
            
            chat_response = await _handle_chat_conversation(
                message=execution_message,  # 🔥 使用增强消息（包含 referenced_text）
                current_topic=current_topic,
                session_topics=session_topics,
                file_uris=file_uris,
                conversation_history=conversation_history,  # 🆕 传递对话历史
                language=language  # 🆕 传递语言设置
            )
            
            # 🔥 保存到 MD（使用原始消息便于阅读）
            await _save_chat_to_session(
                memory_manager=orchestrator.memory_manager,
                user_id=user_id,
                session_id=session_id,
                message=intent_parse_message,  # 保存原始消息
                response_text=chat_response,
                intent="other",
                current_topic=current_topic,
                files=files,
                referenced_text=referenced_text,
                file_url=file_url,
                file_name=file_name
            )
            
            # 🆕 Other intent 使用 Gemini（估算 ~500 tokens）
            token_usage["skill_execution"]["source"] = "llm_gemini"
            token_usage["skill_execution"]["total_tokens"] = 500  # 估算对话 token
            token_usage["total_internal_tokens"] = token_usage["intent_router"]["tokens"] + 500
            
            # 🆕 构建上下文统计信息
            context_stats = {
                "loaded_turns": len(conversation_history) // 2 if conversation_history else 0,
                "retrieved_turns": 0,
                "session_turns": len(conversation_history) // 2 if conversation_history else 0,
                "context_source": "conversation_history"
            }
            
            return {
                "content_type": "text",
                "intent": "other",
                "content": {"text": chat_response},
                "token_usage": token_usage,
                "context_stats": context_stats  # 🆕 添加上下文统计
            }
        except Exception as e:
            logger.error(f"❌ Chat conversation failed: {e}")
            fallback_text = "抱歉，我目前专注于学习辅助功能。试试问我一个学习相关的问题吧！😊"
            
            # 🔥 保存到 MD（即使失败也记录，使用原始消息）
            await _save_chat_to_session(
                memory_manager=orchestrator.memory_manager,
                user_id=user_id,
                session_id=session_id,
                message=intent_parse_message,  # 保存原始消息
                response_text=fallback_text,
                intent="other",
                current_topic=current_topic,
                files=files,
                referenced_text=referenced_text,
                file_url=file_url,
                file_name=file_name
            )
            
            # 🆕 Fallback 不消耗 token（静态文本）
            token_usage["total_internal_tokens"] = token_usage["intent_router"]["tokens"]
            
            return {
                "content_type": "text",
                "intent": "other",
                "content": {"text": fallback_text},
                "token_usage": token_usage
            }
    
    # 如果用户显式传了数量，覆盖 intent 中的参数
    if quantity_override is not None:
        if skill_hint == "quiz":
            intent_result.parameters['num_questions'] = quantity_override
        elif skill_hint == "flashcard":
            intent_result.parameters['num_cards'] = quantity_override
        logger.info(f"📊 Quantity override applied: {quantity_override}")
    
    # 🆕 添加 file_uris 到参数中（如果提供了附件）
    if file_uris:
        intent_result.parameters['file_uris'] = file_uris
        # 保持向后兼容：第一个文件也存到 file_uri
        intent_result.parameters['file_uri'] = file_uris[0]
        logger.info(f"📎 File URIs attached: {file_uris} ({len(file_uris)} files)")
    
    # 🆕 添加 referenced_text 到参数中（如果有引用文本）
    if referenced_text:
        intent_result.parameters['referenced_text'] = referenced_text
        intent_result.parameters['execution_message'] = execution_message
        logger.info(f"📎 Referenced text attached to intent_result: {len(referenced_text)} chars")
    
    # ============= STEP 3: Skill 执行 =============
    logger.info(f"🎯 STEP 3: Executing Skill ({intent_result.intent})...")
    
    orchestrator_response = await orchestrator.execute(
        intent_result=intent_result,
        user_id=user_id,
        session_id=session_id,
        additional_params={"language": language}  # 🆕 传递语言设置
    )
    
    # 🆕 保存 attachments 到 session metadata（orchestrator 内部保存 turn，这里补充 attachments）
    if files or referenced_text:
        await _update_last_turn_attachments(
            memory_manager=orchestrator.memory_manager,
            user_id=user_id,
            session_id=session_id,
            files=files,
            referenced_text=referenced_text,
            file_url=file_url,
            file_name=file_name
        )
    
    # 🆕 检查是否需要重定向到 "other" 处理
    # 当 contextual intent 中检测到询问/解释请求时，orchestrator 会返回 redirect
    if orchestrator_response.get("redirect"):
        logger.info("🔄 Redirecting contextual explain request to 'other' intent handler...")
        original_message = orchestrator_response.get("original_message", message)
        redirect_topic = orchestrator_response.get("topic", current_topic)
        
        try:
            # 🆕 加载对话历史
            conversation_history = await _load_conversation_history(
                memory_manager=orchestrator.memory_manager,
                user_id=user_id,
                session_id=session_id,
                max_turns=6
            )
            
            chat_response = await _handle_chat_conversation(
                message=original_message,
                current_topic=redirect_topic,
                session_topics=session_topics,
                file_uris=file_uris,
                conversation_history=conversation_history,  # 🆕 传递对话历史
                language=language  # 🆕 传递语言设置
            )
            
            # 保存到 MD
            await _save_chat_to_session(
                memory_manager=orchestrator.memory_manager,
                user_id=user_id,
                session_id=session_id,
                message=original_message,
                response_text=chat_response,
                intent="other",
                current_topic=redirect_topic,
                files=files,
                referenced_text=referenced_text,
                file_url=file_url,
                file_name=file_name
            )
            
            # Token 统计（LLM 对话）
            token_usage["skill_execution"] = {
                "source": "llm_gemini",
                "model": "gemini-2.5-flash",
                "thinking_mode": False,
                "total_tokens": 500  # 估算
            }
            token_usage["total_internal_tokens"] = token_usage["intent_router"]["tokens"] + 500
            
            return {
                "content_type": "text",
                "intent": "other",
                "topic": redirect_topic,
                "content": {"text": chat_response},
                "token_usage": token_usage
            }
        except Exception as chat_error:
            logger.error(f"❌ Redirect chat failed: {chat_error}")
            # 继续原来的流程
    
    processing_time = time.time() - start_time
    logger.info(f"✅ Skill executed in {processing_time:.2f}s")
    
    # 🆕 收集 Skill 执行的 token 统计
    usage_summary = orchestrator_response.get("usage_summary", {})
    if usage_summary:
        # 检查是否是外部 API 调用（不计 token）
        if usage_summary.get("external_api"):
            token_usage["skill_execution"] = {
                "source": "external_api",
                "model": "studyx_api",
                "thinking_mode": False,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "generation_time": 0
            }
        else:
            # 内部 LLM 调用（计 token）- 详细记录模型信息
            model_name = usage_summary.get("model", "unknown")
            is_thinking_model = "thinking" in model_name.lower() or "kimi-k2" in model_name.lower()
            
            # Token 计算说明：
            # - total_tokens = prompt_tokens + completion_tokens
            # - thinking_tokens 是 completion_tokens 的子集（估算值）
            # - content_tokens = completion_tokens - thinking_tokens（估算）
            prompt_tokens = usage_summary.get("prompt_tokens", 0)
            completion_tokens = usage_summary.get("completion_tokens", 0)
            total_tokens = usage_summary.get("total_tokens", 0)
            thinking_tokens = usage_summary.get("thinking_tokens", 0)
            
            # 🆕 计算 content_tokens（从 thinking_chars 和 content_chars 估算）
            thinking_chars = usage_summary.get("thinking_chars", 0)
            content_chars = usage_summary.get("content_chars", 0)
            # 如果有 thinking_tokens，content_tokens = completion - thinking
            content_tokens = max(0, completion_tokens - thinking_tokens) if thinking_tokens > 0 else completion_tokens
            
            token_usage["skill_execution"] = {
                "source": "llm",
                "model": model_name,
                "thinking_mode": is_thinking_model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,  # 包含 thinking + content
                "total_tokens": total_tokens,            # = prompt + completion
                # 🆕 Completion 细分（thinking_tokens + content_tokens ≈ completion_tokens）
                "completion_breakdown": {
                    "thinking_tokens": thinking_tokens,  # 思考部分（估算）
                    "content_tokens": content_tokens,    # 内容部分（估算）
                    "thinking_chars": thinking_chars,    # 思考字符数
                    "content_chars": content_chars       # 内容字符数
                },
                "generation_time": usage_summary.get("generation_time", 0),
                "data_source": usage_summary.get("source", "unknown")  # "api" 精确 or "estimated" 估算
            }
    
    # 🆕 获取 Memory Operations 的 token 统计（来自后台异步压缩任务）
    # 注意：这些是上一次请求触发的压缩任务的 token，因为压缩是异步的
    try:
        memory_tracker = get_memory_token_tracker()
        memory_tokens = memory_tracker.get_and_clear_tokens(user_id, session_id)
        token_usage["memory_operations"]["compression_tokens"] = memory_tokens.get("compression_tokens", 0)
        token_usage["memory_operations"]["compression_input"] = memory_tokens.get("compression_input", 0)
        token_usage["memory_operations"]["compression_output"] = memory_tokens.get("compression_output", 0)
        token_usage["memory_operations"]["summary_tokens"] = memory_tokens.get("summary_tokens", 0)
        if memory_tokens.get("total_memory_tokens", 0) > 0:
            comp_in = memory_tokens.get("compression_input", 0)
            comp_out = memory_tokens.get("compression_output", 0)
            logger.info(f"📊 Memory operations tokens: input={comp_in:,}, output={comp_out:,}, total={memory_tokens.get('total_memory_tokens', 0):,}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to get memory tokens: {e}")
    
    # 🆕 计算总内部 token 消耗
    token_usage["total_internal_tokens"] = (
        token_usage["intent_router"]["tokens"] +
        token_usage["skill_execution"]["total_tokens"] +
        token_usage["memory_operations"]["compression_tokens"] +
        token_usage["memory_operations"]["summary_tokens"]
    )
    
    # 🆕 记录 token 统计日志
    model_info = token_usage['skill_execution'].get('model', 'unknown')
    thinking_info = " (thinking)" if token_usage['skill_execution'].get('thinking_mode') else ""
    logger.info(f"📊 Token Usage Summary:")
    logger.info(f"   • Intent Router: {token_usage['intent_router']['tokens']} tokens ({token_usage['intent_router']['method']})")
    logger.info(f"   • Skill Execution: {token_usage['skill_execution']['total_tokens']} tokens ({model_info}{thinking_info})")
    logger.info(f"   • Memory Ops: {token_usage['memory_operations']['compression_tokens'] + token_usage['memory_operations']['summary_tokens']} tokens")
    logger.info(f"   • Total Internal: {token_usage['total_internal_tokens']} tokens")
    
    # 🆕 将 token_usage 添加到返回结果
    orchestrator_response["token_usage"] = token_usage
    
    # 🆕 确保所有 skill 执行都返回 context_stats
    if "context_stats" not in orchestrator_response:
        # 获取对话历史长度
        try:
            conversation_history = await _load_conversation_history(
                orchestrator.memory_manager,
                user_id,
                session_id,
                max_turns=6
            )
            orchestrator_response["context_stats"] = {
                "loaded_turns": len(conversation_history) // 2 if conversation_history else 0,
                "retrieved_turns": 0,
                "session_turns": len(conversation_history) // 2 if conversation_history else 0,
                "context_source": "conversation_history"
            }
        except Exception as e:
            logger.warning(f"⚠️ Failed to get context_stats: {e}")
            orchestrator_response["context_stats"] = {}
    
    # 🆕 保存附件信息到 session metadata（用于历史记录回显）
    if file_url or file_name or referenced_text:
        try:
            attachments_data = {}
            if file_url:
                attachments_data["file_url"] = file_url
            if file_name:
                attachments_data["file_name"] = file_name
            if referenced_text:
                attachments_data["referenced_text"] = referenced_text
            
            # 保存到 session metadata
            session_mgr = orchestrator.memory_manager.get_conversation_session_manager(user_id)
            await session_mgr.start_or_continue_session(original_message, session_id=session_id)
            
            # 更新最后一轮的 attachments
            if hasattr(session_mgr, 'session_metadata') and session_mgr.session_metadata:
                if 'last_turn_attachments' not in session_mgr.session_metadata:
                    session_mgr.session_metadata['last_turn_attachments'] = {}
                
                turn_key = str(session_mgr.turn_counter)
                session_mgr.session_metadata['last_turn_attachments'][turn_key] = attachments_data
                
                # 保存更新后的 metadata
                metadata_file = session_mgr.storage_path / f"{session_id}_metadata.json"
                import json
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(session_mgr.session_metadata, f, ensure_ascii=False, indent=2, default=str)
                
                logger.info(f"📎 Saved attachments to metadata: turn={turn_key}, data={attachments_data}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to save attachments metadata: {e}")
    
    return orchestrator_response


async def _handle_chat_conversation(
    message: str,
    current_topic: Optional[str] = None,
    session_topics: Optional[List[str]] = None,
    file_uris: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    language: str = "en"  # 🆕 语言设置
) -> str:
    """
    使用 Gemini 2.0 Flash Exp 处理闲聊/对话（支持多轮对话上下文）
    
    Args:
        message: 用户消息
        current_topic: 当前学习主题
        session_topics: 历史学习主题
        file_uris: 附件文件列表
        conversation_history: 对话历史列表 [{"role": "user/assistant", "content": "..."}]
        language: 回复语言 (en/zh/auto)
    
    Returns:
        对话响应文本
    """
    from app.services.gemini import GeminiClient
    
    gemini = GeminiClient()
    
    # 🆕 语言代码映射到语言名称（用于 prompt 指令）
    LANGUAGE_NAMES = {
        "auto": None,  # 自动检测
        "en": "English",
        "zh": "Simplified Chinese (简体中文)",
        "zh-CN": "Simplified Chinese (简体中文)",
        "zh-TW": "Traditional Chinese (繁體中文)",
        "ja": "Japanese (日本語)",
        "ko": "Korean (한국어)",
        "fr": "French (Français)",
        "es": "Spanish (Español)",
        "pt": "Portuguese (Português)",
        "de": "German (Deutsch)",
        "it": "Italian (Italiano)",
        "ru": "Russian (Русский)",
        "vi": "Vietnamese (Tiếng Việt)",
        "th": "Thai (ภาษาไทย)",
        "hi": "Hindi (हिंदी)",
        "id": "Indonesian (Bahasa Indonesia)",
        "ms": "Malay (Melayu)",
        "tr": "Turkish (Türkçe)",
        "pl": "Polish (Polski)",
        "nl": "Dutch (Nederlands)",
        "ro": "Romanian (Română)",
        "cs": "Czech (Čeština)",
        "sk": "Slovak (Slovenčina)",
        "hu": "Hungarian (Magyar)",
        "tl": "Tagalog/Filipino",
        "no": "Norwegian (Norsk)",
        "da": "Danish (Dansk)",
        "fi": "Finnish (Suomi)",
    }
    
    # 🆕 获取语言名称
    target_language = LANGUAGE_NAMES.get(language, None)
    is_chinese = language in ["zh", "zh-CN", "zh-TW"]
    
    # 构建上下文提示（使用中性格式）
    context_info = ""
    if current_topic:
        context_info = f"\nCurrent topic: {current_topic}"
    if session_topics:
        recent = session_topics[-3:]  # 最近3个主题
        context_info += f"\nRecent topics: {', '.join(recent)}"
    
    # 🆕 构建对话历史上下文
    history_context = ""
    if conversation_history and len(conversation_history) > 0:
        history_context = "\n\n## Previous conversation:\n"
        for turn in conversation_history[-6:]:  # 最近6轮对话
            role = turn.get("role", "user")
            content = turn.get("content", "")[:200]  # 限制每轮长度
            if role == "user":
                history_context += f"User: {content}\n"
            else:
                history_context += f"Assistant: {content}\n"
        history_context += "\n---\n"
        logger.info(f"📜 Loaded {len(conversation_history[-6:])} turns of conversation history")
    
    # 🆕 处理文件附件
    file_context = ""
    if file_uris:
        file_names = []
        for uri in file_uris:
            # 提取文件名（去掉 gs://kimi-dev/ 前缀）
            name = uri.split('/')[-1] if '/' in uri else uri
            file_names.append(name)
        file_context = f"\nUploaded files: {', '.join(file_names)}"
        logger.info(f"📎 Chat with files: {file_names}")
    
    # 🆕 检查是否有图片文件（图片可以被 Gemini 直接识别）
    image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
    has_images = file_uris and any(uri.lower().endswith(image_extensions) for uri in file_uris)
    
    # 🆕 语言指令（支持 30+ 语言 + 自动检测）
    lang_instruction = ""
    if language == "auto" or target_language is None:
        # 自动检测：根据用户输入语言回复
        # 🆕 增强：明确强调根据用户消息语言回复，不受文件内容语言影响
        lang_instruction = "\n\n**CRITICAL LANGUAGE RULE: You MUST respond in THE SAME LANGUAGE as the user's message (the 'User message:' field above), NOT the language of any uploaded files or documents. If the user writes in English (e.g., 'Please help me analyze...'), you MUST respond in English, even if the uploaded file is in Chinese/Japanese/other languages. Match the user's message language exactly.**"
    else:
        # 指定语言
        lang_instruction = f"\n\n**IMPORTANT: You MUST respond in {target_language} only. This is critical - do not use any other language, regardless of the content in uploaded files.**"
    
    # 根据是否有文件选择不同的 prompt（统一使用英文模板 + 语言指令）
    if file_uris:
        # 有文件时的 prompt
        prompt = f"""You are StudyX Agent, an intelligent learning assistant.

The user has uploaded files (images/documents) and asked a question.
{file_context}
{context_info}
{history_context}
User message: {message}

Please answer the user's question based on the uploaded images/files.
- If it's an image, describe the content and answer the question
- If it's a document, analyze its content and provide a detailed answer
- If it's a math/physics problem, provide a **COMPLETE step-by-step solution with all calculations**
- Be friendly, clear, and helpful
- **DO NOT truncate or cut off your response. Complete all steps.**
{lang_instruction}
Please respond directly and completely (no length limit for math problems, otherwise within 800 words)."""
    else:
        # 无文件时的 prompt
        if history_context:
            # 有对话历史
            prompt = f"""You are StudyX Agent, an intelligent learning assistant. You are having a continuous conversation with the user.

**IMPORTANT** You MUST base your response on the previous conversation history, maintaining context continuity. If the user asks about something discussed earlier, refer to the previous responses.

Your main functions include:
- Generating practice questions (when user explicitly asks)
- Explaining concepts (when user asks "what is X" or "explain X")
- Creating flashcards (when user explicitly asks)
- Organizing notes
- Drawing mind maps
- Creating study plans (when user explicitly asks)

{context_info}
{history_context}

Current user message: {message}

Please respond based on conversation history.
- If user follows up on previous content, reference and explain in detail
- If user asks about "what we discussed earlier", find relevant content from history
- If it's a math/physics problem, provide a **COMPLETE step-by-step solution**
- Be friendly, clear, and helpful
- Don't proactively recommend generating quizzes/flashcards unless explicitly asked
- **DO NOT truncate or cut off your response. Complete all explanations.**
{lang_instruction}
Please respond directly and completely (within 800 words, no limit for math problems)."""
        else:
            # 无对话历史
            prompt = f"""You are StudyX Agent, an intelligent learning assistant.

Your main functions include:
- Generating practice questions (when user explicitly asks for "quiz/test/questions")
- Explaining concepts (when user asks "what is X" or "explain X")
- Creating flashcards (when user explicitly asks)
- Organizing notes
- Drawing mind maps
- Creating study plans (when user explicitly asks)

When user sends a message, you should:
1. Respond friendly and directly answer their question
2. If user asks about a concept, explain it directly
3. Don't proactively recommend generating quizzes/flashcards unless explicitly asked

{context_info}

User message: {message}
{lang_instruction}
Please respond directly and completely (within 500 words)."""
    
    try:
        # 🆕 传递 file_uris 给 Gemini（支持多模态识别）
        # 🆕 增加 max_tokens 到 8192，确保复杂数学题解答有足够空间
        # 🆕 禁用 thinking 模式（thinking_budget=0），让更多 tokens 留给实际输出
        response = await gemini.generate(
            prompt=prompt,
            model="gemini-2.5-flash",
            response_format="text",
            temperature=0.7,
            max_tokens=8192,  # 🆕 增加到 8192，避免复杂数学题回答被截断
            thinking_budget=0,  # 🆕 禁用 thinking，避免思考 tokens 消耗输出配额
            file_uris=file_uris if file_uris else None  # 传递文件 URI
        )
        
        # 处理响应
        if isinstance(response, dict):
            return response.get("content", "抱歉，我无法回复。")
        return str(response)
        
    except Exception as e:
        logger.error(f"❌ Gemini chat failed: {e}")
        
        # 构建基于上下文的默认回复
        if current_topic:
            return f"我看到你正在学习「{current_topic}」，有什么我可以帮你解答的吗？😊"
        else:
            return "你好！我是学习助手，有什么学习问题我可以帮你解答吗？"


async def _generate_clarification(
    message: str,
    artifact_contents: List[Dict[str, Any]],
    session_topics: List[str],
    current_topic: Optional[str] = None
) -> Optional[str]:
    """
    🆕 基于压缩上下文生成澄清问题
    
    当用户的请求模糊时（如"那道题"但有多个 quiz），
    使用 LLM 生成友好的澄清问题帮助用户明确需求
    """
    from app.services.gemini import GeminiClient
    
    if not artifact_contents:
        return None
    
    try:
        gemini = GeminiClient()
        
        # 构建压缩的上下文摘要
        context_summary = _build_compressed_context_summary(artifact_contents, session_topics)
        
        prompt = f"""你是 StudyX Agent 的澄清助手。用户发送了一条消息，但意图不够明确。

## 用户消息
{message}

## 学习历史摘要
{context_summary}

## 当前主题
{current_topic or "无"}

## 任务
请生成一个友好、简洁的澄清问题，帮助用户明确他们想要的内容。

澄清问题应该：
1. 友好且不打断用户思路
2. 列出可能的选项（如果有多个 topic 或 artifact）
3. 使用编号让用户方便回复
4. 不超过 150 字

示例格式：
"您好！我注意到您之前学习了多个主题。请问您想要的是：
1. 关于「凡尔赛条约」的第一道题的解释
2. 关于「经济大萧条」的第二道题的解释
请回复数字选择，或直接告诉我具体需求 😊"

请直接输出澄清问题，不需要其他解释。"""

        response = await gemini.generate(
            prompt=prompt,
            model="gemini-2.5-flash",
            response_format="text",
            temperature=0.5
        )
        
        if isinstance(response, dict):
            return response.get("content", None)
        return str(response)
        
    except Exception as e:
        logger.error(f"❌ Failed to generate clarification: {e}")
        return None


def _build_compressed_context_summary(
    artifact_contents: List[Dict[str, Any]],
    session_topics: List[str]
) -> str:
    """
    🆕 构建压缩的上下文摘要，用于 LLM 澄清
    """
    lines = []
    
    # 主题摘要
    if session_topics:
        unique_topics = list(dict.fromkeys(session_topics))
        lines.append(f"📚 学习过的主题：{', '.join(unique_topics[:5])}")
    
    # Artifacts 摘要（按 turn_number 排序）
    sorted_artifacts = sorted(artifact_contents, key=lambda x: x.get('turn_number', 0))
    
    for artifact in sorted_artifacts[-5:]:  # 只取最近 5 个
        turn = artifact.get('turn_number', '?')
        a_type = artifact.get('artifact_type', 'unknown')
        topic = artifact.get('topic', 'unknown')
        content = artifact.get('content', {})
        
        # 根据类型生成摘要
        if a_type == 'quiz_set' or 'questions' in content:
            q_count = len(content.get('questions', []))
            questions_preview = []
            for i, q in enumerate(content.get('questions', [])[:3], 1):
                q_text = q.get('question', q.get('question_text', ''))[:30]
                questions_preview.append(f"Q{i}: {q_text}...")
            lines.append(f"Turn {turn} - 📝 练习题 ({topic}): {q_count}道题")
            if questions_preview:
                lines.append(f"   预览: {'; '.join(questions_preview)}")
                
        elif a_type == 'flashcard_set' or 'cardList' in content:
            cards = content.get('cardList', content.get('cards', []))
            lines.append(f"Turn {turn} - 🎴 闪卡 ({topic}): {len(cards)}张")
            
        elif a_type == 'explanation' or 'examples' in content:
            examples = content.get('examples', [])
            examples_preview = []
            for i, ex in enumerate(examples[:3], 1):
                ex_text = ex.get('example', '')[:25]
                examples_preview.append(f"例{i}: {ex_text}...")
            lines.append(f"Turn {turn} - 📖 讲解 ({topic}): {len(examples)}个例子")
            if examples_preview:
                lines.append(f"   预览: {'; '.join(examples_preview)}")
        else:
            lines.append(f"Turn {turn} - {a_type} ({topic})")
    
    return "\n".join(lines) if lines else "无历史记录"


async def _update_last_turn_attachments(
    memory_manager,
    user_id: str,
    session_id: str,
    files: Optional[List[Dict[str, Any]]] = None,
    referenced_text: Optional[str] = None,
    file_url: Optional[str] = None,
    file_name: Optional[str] = None
):
    """
    更新最后一轮对话的 attachments（用于 orchestrator 执行后补充附件信息）
    
    Args:
        memory_manager: MemoryManager 实例
        user_id: 用户 ID
        session_id: 会话 ID
        files: 统一的文件信息数组
        referenced_text: 引用文本
        file_url: [兼容] 单个图片 URL
        file_name: [兼容] 单个文档名
    """
    try:
        session_mgr = memory_manager.get_conversation_session_manager(user_id)
        
        # 构建 attachments
        attachments = {}
        
        # 优先使用统一的 files 数组
        if files:
            attachments["files"] = files
        else:
            # 兼容旧版单文件字段
            legacy_files = []
            if file_url:
                legacy_files.append({"type": "image", "url": file_url})
            if file_name:
                legacy_files.append({"type": "document", "name": file_name})
            if legacy_files:
                attachments["files"] = legacy_files
        
        if referenced_text:
            attachments["referenced_text"] = referenced_text
        
        if not attachments:
            return  # 无附件信息，跳过
        
        # 获取当前 turn 数
        turn_key = str(session_mgr.turn_counter) if hasattr(session_mgr, 'turn_counter') else "1"
        
        # 更新 session metadata
        if hasattr(session_mgr, 'session_metadata') and session_mgr.session_metadata:
            if 'last_turn_attachments' not in session_mgr.session_metadata:
                session_mgr.session_metadata['last_turn_attachments'] = {}
            
            session_mgr.session_metadata['last_turn_attachments'][turn_key] = attachments
            
            # 保存更新后的 metadata
            from pathlib import Path
            metadata_file = session_mgr.storage_path / f"{session_id}_metadata.json"
            import json as json_module
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json_module.dump(session_mgr.session_metadata, f, ensure_ascii=False, indent=2, default=str)
            
            logger.info(f"📎 Updated attachments for turn {turn_key}: {list(attachments.keys())}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to update turn attachments: {e}")


async def _save_chat_to_session(
    memory_manager,
    user_id: str,
    session_id: str,
    message: str,
    response_text: str,
    intent: str,
    current_topic: Optional[str] = None,
    files: Optional[List[Dict[str, Any]]] = None,  # 🆕 统一的文件信息数组
    referenced_text: Optional[str] = None,
    # 兼容旧版单文件字段
    file_url: Optional[str] = None,
    file_name: Optional[str] = None
):
    """
    保存聊天对话到会话 MD 文件
    
    Args:
        memory_manager: MemoryManager 实例
        user_id: 用户 ID
        session_id: 会话 ID
        message: 用户消息
        response_text: AI 回复
        intent: 意图类型（help/other）
        current_topic: 当前主题（可选）
        files: 统一的文件信息数组 [{"type": "image", "url": "..."}, {"type": "document", "name": "..."}]
        referenced_text: 引用文本内容
        file_url: [兼容] 单个图片 HTTP URL
        file_name: [兼容] 单个文档文件名
    """
    try:
        session_mgr = memory_manager.get_conversation_session_manager(user_id)
        await session_mgr.start_or_continue_session(message, session_id=session_id)
        
        # 🆕 构建附件信息（用于历史记录回显）
        attachments = {}
        
        # 优先使用统一的 files 数组
        if files:
            attachments["files"] = files
        else:
            # 兼容旧版单文件字段 - 转换为统一格式
            legacy_files = []
            if file_url:
                legacy_files.append({"type": "image", "url": file_url})
            if file_name:
                legacy_files.append({"type": "document", "name": file_name})
            if legacy_files:
                attachments["files"] = legacy_files
        
        if referenced_text:
            attachments["referenced_text"] = referenced_text
        
        await session_mgr.append_turn({
            "user_query": message,
            "agent_response": {
                "skill": "chat",
                "artifact_id": "",
                "content": {"text": response_text}
            },
            "response_type": "text",
            "timestamp": datetime.now(),
            "intent": {
                "intent": intent,
                "topic": current_topic,
                "raw_text": message
            },
            "metadata": {
                "model": "gemini-2.5-flash",
                "source": "/api/external/chat"
            },
            "attachments": attachments if attachments else None  # 🆕 附件信息
        })
        
        # 🆕 保存附件信息到 session metadata（用于历史记录回显）
        if attachments:
            try:
                if hasattr(session_mgr, 'session_metadata') and session_mgr.session_metadata:
                    if 'last_turn_attachments' not in session_mgr.session_metadata:
                        session_mgr.session_metadata['last_turn_attachments'] = {}
                    
                    turn_key = str(session_mgr.turn_counter)
                    session_mgr.session_metadata['last_turn_attachments'][turn_key] = attachments
                    
                    # 保存更新后的 metadata
                    metadata_file = session_mgr.storage_path / f"{session_id}_metadata.json"
                    import json as json_module
                    with open(metadata_file, 'w', encoding='utf-8') as f:
                        json_module.dump(session_mgr.session_metadata, f, ensure_ascii=False, indent=2, default=str)
                    
                    logger.info(f"📎 Saved attachments to metadata: turn={turn_key}")
            except Exception as attach_err:
                logger.warning(f"⚠️ Failed to save attachments metadata: {attach_err}")
        
        logger.info(f"✅ Saved chat to MD: intent={intent}, user={user_id}, attachments={bool(attachments)}")
    except Exception as e:
        logger.error(f"❌ Failed to save chat to MD: {e}")


async def _load_session_context_from_md(
    memory_manager,
    user_id: str,
    session_id: str
) -> Optional[Dict[str, Any]]:
    """
    从 MD metadata 文件加载 session 上下文
    
    Args:
        memory_manager: MemoryManager 实例
        user_id: 用户 ID
        session_id: 会话 ID
    
    Returns:
        Dict with current_topic, session_topics, last_artifact, etc.
    """
    from pathlib import Path
    
    try:
        # 构建 metadata 文件路径
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        metadata_file = artifacts_dir / f"{session_id}_metadata.json"
        
        if not metadata_file.exists():
            logger.debug(f"📂 No metadata file found: {metadata_file}")
            return None
        
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        # 提取上下文信息 - 优先使用 last_topic，其次是 current_topic
        current_topic = metadata.get("last_topic") or metadata.get("current_topic")
        topics = metadata.get("topics", [])
        
        # 从 artifact_history 构建 session_topics
        artifact_history = metadata.get("artifact_history", [])
        session_topics = [a.get("topic") for a in artifact_history if a.get("topic")]
        
        # 如果 topics 列表不为空，合并到 session_topics
        if topics:
            for t in topics:
                if t not in session_topics:
                    session_topics.append(t)
        
        # 获取最后一个 artifact
        last_artifact = None
        if artifact_history:
            last = artifact_history[-1]
            last_artifact = last.get("artifact_type")
        
        logger.info(f"📂 Loaded session metadata: topic={current_topic}, artifacts={len(artifact_history)}")
        
        # 🆕 尝试从 MD 文件加载 artifact contents（用于引用解析）
        artifact_contents = await _load_artifacts_from_md(
            artifacts_dir / f"{session_id}.md"
        )
        
        return {
            "current_topic": current_topic,
            "session_topics": session_topics,
            "last_artifact": last_artifact,
            "artifact_contents": artifact_contents  # 🆕 添加完整内容
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to load session context from MD: {e}")
        return None


async def _load_artifacts_from_md(md_file_path) -> List[Dict[str, Any]]:
    """
    🆕 从 MD 文件中提取 artifact contents（用于引用解析）
    
    解析 MD 文件中的 JSON 代码块，提取 agent_response.content
    """
    from pathlib import Path
    
    artifacts = []
    
    try:
        md_path = Path(md_file_path)
        if not md_path.exists():
            return artifacts
        
        content = md_path.read_text(encoding='utf-8')
        
        # 查找所有 JSON 代码块
        json_pattern = r'```json\s*\n(.*?)\n```'
        matches = re.findall(json_pattern, content, re.DOTALL)
        
        for json_str in matches:
            try:
                data = json.loads(json_str)
                
                # 检查是否包含 agent_response
                if 'agent_response' in data and 'content' in data['agent_response']:
                    topic = data.get('intent', {}).get('topic', '')
                    artifact_content = data['agent_response']['content']
                    turn_number = data.get('turn_number', 0)
                    skill = data['agent_response'].get('skill', '')
                    
                    # 🔥 从 skill 推断 artifact_type
                    # skill: explain_skill → explanation
                    # skill: quiz_skill → quiz_set
                    # skill: flashcard_skill → flashcard_set
                    skill_to_type = {
                        'explain_skill': 'explanation',
                        'quiz_skill': 'quiz_set',
                        'flashcard_skill': 'flashcard_set',
                        'notes_skill': 'notes',
                        'mindmap_skill': 'mindmap',
                        'learning_plan_skill': 'learning_bundle'
                    }
                    artifact_type = skill_to_type.get(skill, 'unknown')
                    
                    # 🔥 也可以从 content 结构推断
                    if artifact_type == 'unknown':
                        if 'questions' in artifact_content:
                            artifact_type = 'quiz_set'
                        elif 'cardList' in artifact_content or 'cards' in artifact_content:
                            artifact_type = 'flashcard_set'
                        elif 'examples' in artifact_content or 'intuition' in artifact_content:
                            artifact_type = 'explanation'
                    
                    artifacts.append({
                        'artifact_type': artifact_type,
                        'topic': topic,
                        'content': artifact_content,
                        'turn_number': turn_number
                    })
                    
                    logger.debug(f"📄 Loaded artifact: turn={turn_number}, type={artifact_type}, skill={skill}")
                    
            except json.JSONDecodeError:
                continue
        
        logger.info(f"📦 Loaded {len(artifacts)} artifacts from MD file")
        return artifacts
        
    except Exception as e:
        logger.error(f"❌ Failed to load artifacts from MD: {e}")
        return []


async def _inject_artifacts_to_session(
    memory_manager,
    session_id: str,
    artifact_contents: List[Dict[str, Any]]
):
    """
    🆕 将从 MD 加载的 artifact contents 注入到 session_context
    
    用于引用解析时获取历史 artifact 内容
    """
    from app.models.memory import ArtifactRecord
    from datetime import datetime
    
    try:
        session_context = await memory_manager.get_session_context(session_id)
        
        # 如果 artifact_history 已经有内容，跳过
        if session_context.artifact_history:
            logger.debug(f"📦 Session already has {len(session_context.artifact_history)} artifacts, skipping injection")
            return
        
        # 注入 artifacts
        for artifact in artifact_contents:
            turn_num = artifact.get('turn_number', 0)
            record = ArtifactRecord(
                artifact_id=f"loaded_{turn_num}_{artifact.get('artifact_type', 'unknown')}",
                artifact_type=artifact.get('artifact_type', 'unknown'),
                topic=artifact.get('topic', ''),
                content=artifact.get('content', {}),
                summary=str(artifact.get('content', {}))[:100],
                storage_type='inline',
                content_reference=None,
                timestamp=datetime.now(),
                turn_number=turn_num  # 🔥 添加 turn_number
            )
            session_context.artifact_history.append(record)
        
        logger.info(f"📦 Injected {len(artifact_contents)} artifacts to session_context")
        
    except Exception as e:
        logger.error(f"❌ Failed to inject artifacts to session: {e}")


async def _load_conversation_history(
    memory_manager,
    user_id: str,
    session_id: str,
    max_turns: int = 6
) -> List[Dict[str, str]]:
    """
    🆕 从 MD 文件加载对话历史（用于多轮对话上下文）
    
    Args:
        memory_manager: MemoryManager 实例
        user_id: 用户 ID
        session_id: 会话 ID
        max_turns: 最大返回轮数
    
    Returns:
        对话历史列表 [{"role": "user/assistant", "content": "..."}]
    """
    from pathlib import Path
    
    history = []
    
    try:
        # 构建 MD 文件路径
        artifacts_dir = memory_manager.artifact_storage.base_dir / user_id
        md_file = artifacts_dir / f"{session_id}.md"
        
        if not md_file.exists():
            logger.debug(f"📂 No MD file found: {md_file}")
            return history
        
        content = md_file.read_text(encoding='utf-8')
        
        # 查找所有 JSON 代码块，提取对话内容
        json_pattern = r'```json\s*\n(.*?)\n```'
        matches = re.findall(json_pattern, content, re.DOTALL)
        
        for json_str in matches:
            try:
                data = json.loads(json_str)
                
                # 提取用户消息和助手回复
                user_query = data.get('user_query', '')
                agent_response = data.get('agent_response', {})
                
                if user_query:
                    history.append({
                        "role": "user",
                        "content": user_query
                    })
                
                # 提取助手回复内容
                response_content = agent_response.get('content', {})
                if isinstance(response_content, dict):
                    # 尝试提取文本内容
                    if 'text' in response_content:
                        history.append({
                            "role": "assistant",
                            "content": response_content['text']
                        })
                    elif 'concept' in response_content:
                        # Explain 类型的响应
                        concept = response_content.get('concept', '')
                        intuition = response_content.get('intuition', '')
                        history.append({
                            "role": "assistant",
                            "content": f"关于 {concept}：{intuition[:200]}..."
                        })
                    elif 'questions' in response_content:
                        # Quiz 类型
                        q_count = len(response_content.get('questions', []))
                        history.append({
                            "role": "assistant",
                            "content": f"[生成了 {q_count} 道练习题]"
                        })
                    elif 'cardList' in response_content:
                        # Flashcard 类型
                        c_count = len(response_content.get('cardList', []))
                        history.append({
                            "role": "assistant",
                            "content": f"[生成了 {c_count} 张闪卡]"
                        })
                elif isinstance(response_content, str):
                    history.append({
                        "role": "assistant",
                        "content": response_content
                    })
                    
            except json.JSONDecodeError:
                continue
        
        # 只返回最近的 N 轮
        if len(history) > max_turns * 2:
            history = history[-(max_turns * 2):]
        
        logger.info(f"📜 Loaded {len(history)//2} turns of conversation history from {session_id}")
        return history
        
    except Exception as e:
        logger.error(f"❌ Failed to load conversation history: {e}")
        return []


# ============= 响应格式转换（临时限制：只输出文本） =============


def _convert_to_text_format(content_type: str, content: Any, topic: str = "") -> tuple:
    """
    🔥 临时限制：将所有非文本格式转换为纯文本输出
    
    前端目前只支持文本渲染，后续支持 Quiz/Flashcard 等格式后可移除此函数
    
    Args:
        content_type: 原始内容类型 (quiz_set, flashcard_set, explanation, etc.)
        content: 原始内容
        topic: 主题
    
    Returns:
        (new_content_type, new_content): 转换后的类型和内容
    """
    # 已经是文本格式，直接返回
    if content_type in ["text", "clarification_needed", "onboarding"]:
        return content_type, content
    
    # 如果 content 不是 dict，直接返回
    if not isinstance(content, dict):
        return "text", {"text": str(content)}
    
    # 转换 Quiz 为文本
    if content_type == "quiz_set":
        text_lines = []
        title = content.get("title", topic or "测验")
        text_lines.append(f"📝 **{title}**\n")
        
        questions = content.get("questions", [])
        for i, q in enumerate(questions, 1):
            text_lines.append(f"**第 {i} 题：** {q.get('question', '')}\n")
            
            options = q.get("answer_options", [])
            for j, opt in enumerate(options):
                letter = chr(65 + j)  # A, B, C, D
                is_correct = "✓" if opt.get("is_correct") else ""
                text_lines.append(f"  {letter}. {opt.get('text', '')} {is_correct}")
            
            # 找出正确答案
            correct_opts = [chr(65 + j) for j, opt in enumerate(options) if opt.get("is_correct")]
            if correct_opts:
                text_lines.append(f"\n  **答案：{', '.join(correct_opts)}**")
            
            # 添加解析
            for j, opt in enumerate(options):
                if opt.get("is_correct") and opt.get("rationale"):
                    text_lines.append(f"  **解析：** {opt.get('rationale')}")
                    break
            
            text_lines.append("")
        
        return "text", {"text": "\n".join(text_lines)}
    
    # 转换 Flashcard 为文本
    if content_type == "flashcard_set":
        text_lines = []
        title = content.get("title", topic or "闪卡")
        text_lines.append(f"🗂️ **{title}**\n")
        
        cards = content.get("cardList", [])
        for i, card in enumerate(cards, 1):
            text_lines.append(f"**卡片 {i}**")
            text_lines.append(f"  📌 正面：{card.get('front', '')}")
            text_lines.append(f"  📝 背面：{card.get('back', '')}")
            text_lines.append("")
        
        return "text", {"text": "\n".join(text_lines)}
    
    # 转换 Explanation 为文本
    if content_type == "explanation":
        text_lines = []
        concept = content.get("concept", topic or "概念讲解")
        text_lines.append(f"📖 **{concept}**\n")
        
        if content.get("intuition"):
            text_lines.append(f"**直观理解：** {content['intuition']}\n")
        
        if content.get("formal_definition"):
            text_lines.append(f"**定义：** {content['formal_definition']}\n")
        
        if content.get("why_it_matters"):
            text_lines.append(f"**重要性：** {content['why_it_matters']}\n")
        
        examples = content.get("examples", [])
        if examples:
            text_lines.append("**例子：**")
            for ex in examples:
                if isinstance(ex, dict):
                    text_lines.append(f"  • {ex.get('description', ex)}")
                else:
                    text_lines.append(f"  • {ex}")
            text_lines.append("")
        
        mistakes = content.get("common_mistakes", [])
        if mistakes:
            text_lines.append("**常见错误：**")
            for m in mistakes:
                if isinstance(m, dict):
                    text_lines.append(f"  ⚠️ {m.get('mistake', m)}")
                else:
                    text_lines.append(f"  ⚠️ {m}")
            text_lines.append("")
        
        return "text", {"text": "\n".join(text_lines)}
    
    # 转换 Learning Bundle 为文本
    if content_type == "learning_bundle":
        text_lines = []
        text_lines.append(f"📚 **学习包：{topic or '综合学习'}**\n")
        
        components = content.get("components", [])
        for comp in components:
            comp_type = comp.get("type", "unknown")
            comp_content = comp.get("content", {})
            
            if comp_type == "explanation":
                text_lines.append("📖 **讲解部分**")
                text_lines.append(comp_content.get("text", str(comp_content)[:200]))
            elif comp_type == "quiz_set":
                text_lines.append("📝 **练习题**")
                # 递归转换
                _, quiz_text = _convert_to_text_format("quiz_set", comp_content, "")
                text_lines.append(quiz_text.get("text", ""))
            elif comp_type == "flashcard_set":
                text_lines.append("🗂️ **闪卡**")
                _, card_text = _convert_to_text_format("flashcard_set", comp_content, "")
                text_lines.append(card_text.get("text", ""))
            
            text_lines.append("")
        
        return "text", {"text": "\n".join(text_lines)}
    
    # 其他未知格式，尝试提取 text 字段或转为字符串
    if "text" in content:
        return "text", {"text": content["text"]}
    
    # 最后兜底：JSON 转字符串
    import json
    return "text", {"text": json.dumps(content, ensure_ascii=False, indent=2)}


# ============= API Endpoints =============


@router.post("/chat", response_model=Dict[str, Any])
async def chat(
    request: ChatRequest,
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator),
    token: Optional[str] = Header(None, description="用户认证 Token（用于外部 API 调用）"),
    environment: Optional[str] = Header("test", description="环境标识 (dev/test/prod)")
):
    """
    通用聊天接口 - 支持所有 skill 和附件上传
    
    内部流程：
    1. Intent Router 自动识别意图（quiz/flashcard/explain/notes/mindmap 等）
    2. Skill Orchestrator 执行对应 skill
    3. Memory Manager 更新上下文 & 存储 MD
    
    输入格式:
    ```json
    {
        "message": "帮我出5道题",
        "file_uri": "gs://kimi-dev/user_xxx/xxx.txt",  // 可选，附件
        "user_id": "user_kimi",  // 可选
        "session_id": "session_123"  // 可选
    }
    ```
    
    输出格式:
    ```json
    {
        "code": 0,
        "msg": "Request succeeded",
        "data": {
            "content_type": "quiz_set",
            "intent": "quiz_request",
            "topic": "光合作用",
            "content": {...}
        }
    }
    ```
    
    附件使用流程：
    1. 先调用 /api/external/upload 上传文件，获取 file_uri
    2. 将 file_uri 传入此接口
    
    支持的意图类型：
    - quiz_request: 生成测验题目
    - flashcard_request: 生成闪卡
    - explain_request: 概念讲解
    - notes: 生成笔记
    - mindmap: 生成思维导图
    - learning_bundle: 生成学习包
    - help: 帮助信息
    - other: 其他对话
    """
    try:
        # 🆕 设置用户 token 到请求上下文（用于外部 API 调用）
        if token:
            set_user_api_token(token)
            logger.info(f"🔑 User token set from headers")
        
        message = request.message.strip()
        
        # ============= 检查是否有文件上传 =============
        has_files = bool(request.file_uri or request.file_uris)
        
        # ============= 🆕 获取用户语言设置 =============
        # 优先级: 1. 请求参数 → 2. StudyX 用户设置 → 3. auto
        env = environment or "test"  # 默认测试环境
        logger.info(f"🌍 Environment: {env}")
        
        if request.language:
            language = request.language
            logger.info(f"🌐 Using language from request: {language}")
        elif token:
            # 从 StudyX API 获取用户语言设置（根据环境选择 API）
            language = await get_user_language_from_studyx(token, env)
        else:
            language = "auto"
            logger.info(f"🌐 No token, using auto language detection")
        
        # 场景 A: 快捷按钮模式（action_type）- 不需要输入文字
        if not message and request.action_type:
            # 根据语言设置选择默认提示（简化为中英双语，其他语言用英语）
            if language in ["zh", "zh-CN", "zh-TW"]:
                action_default_messages = {
                    "explain_concept": "请详细解释这个概念",
                    "make_simpler": "请用更简单的方式解释",
                    "common_mistakes": "这个知识点有哪些常见错误",
                }
                default_msg = "请帮我理解这个内容"
            else:
                action_default_messages = {
                    "explain_concept": "Please explain this concept in detail",
                    "make_simpler": "Please explain this in a simpler way",
                    "common_mistakes": "What are the common mistakes for this topic",
                }
                default_msg = "Please help me understand this content"
            message = action_default_messages.get(request.action_type, default_msg)
        
        # 场景 B: 文件上传模式（图片/文档）- 不需要输入文字
        # 🆕 允许只上传图片/文件，不输入文字
        if not message and has_files:
            # 根据语言设置默认提示
            if language in ["zh", "zh-CN", "zh-TW"]:
                message = "请帮我分析这个图片/文件的内容"
            else:
                message = "Please help me analyze this image/file"
            logger.info(f"📎 File upload without message, using default: {message}")
        
        # 场景 C: 引用文本模式（无 action_type 且无文件）- 必须输入文字
        if request.referenced_text and not message and not request.action_type and not has_files:
            return {
                "code": 400, 
                "msg": "Message is required when referenced_text is provided (unless using action_type or file upload)", 
                "data": None
            }
        
        # 场景 D: 普通聊天（无文件、无 action_type）- 必须有消息
        if not message and not has_files:
            return {"code": 400, "msg": "Message is empty", "data": None}
        
        # 使用传入的 session_id，或生成与登录接口一致的格式
        user_id = request.user_id or "anonymous"
        
        # 🆕 优先使用 question_id + answer_id 作为 session_id（题目关联模式）
        if request.question_id and request.answer_id:
            session_id = f"q{request.question_id}_a{request.answer_id}"
            logger.info(f"📎 Using question-bound session: {session_id}")
        elif request.question_id:
            session_id = f"q{request.question_id}"
            logger.info(f"📎 Using question session: {session_id}")
        elif request.session_id:
            session_id = request.session_id
        else:
            session_id = f"{user_id}_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        logger.info("="*60)
        
        # 🆕 支持多文件：合并 file_uri 和 file_uris
        file_uris = []
        if request.file_uri:
            file_uris.append(request.file_uri)
        if request.file_uris:
            file_uris.extend(request.file_uris)
        
        # 去重
        file_uris = list(dict.fromkeys(file_uris))
        
        # 🆕 构建统一的 files 数组（优先使用 request.files，其次转换旧版字段）
        files = None
        if request.files:
            # 使用新版统一的 files 数组
            files = [f.model_dump() for f in request.files]
        else:
            # 兼容旧版单文件字段 - 转换为统一格式
            legacy_files = []
            if request.file_url:
                legacy_files.append({"type": "image", "url": request.file_url})
            if request.file_name:
                legacy_files.append({"type": "document", "name": request.file_name})
            if legacy_files:
                files = legacy_files
        
        logger.info(f"📥 /api/external/chat")
        logger.info(f"   • User: {user_id}")
        logger.info(f"   • Session: {session_id}")
        logger.info(f"   • Question ID: {request.question_id or 'N/A'}")
        logger.info(f"   • Answer ID: {request.answer_id or 'N/A'}")
        logger.info(f"   • Message: {message[:100]}...")
        logger.info(f"   • File URIs: {file_uris if file_uris else 'N/A'} ({len(file_uris)} files)")
        logger.info(f"   • Files: {files if files else 'N/A'}")
        logger.info(f"   • Referenced Text: {'Yes (' + str(len(request.referenced_text)) + ' chars)' if request.referenced_text else 'N/A'}")
        logger.info(f"   • Action Type: {request.action_type or 'N/A'}")
        # 🆕 支持 qid 和 resource_id 两种字段名
        effective_qid = request.qid or request.resource_id
        logger.info(f"   • QID/Resource ID: {effective_qid or 'N/A'}")
        logger.info("="*60)
        
        # 🆕 检查是否需要获取题目上下文
        # 优先级: 1. request.question_context (前端直接传入) → 2. 从 StudyX API 获取 (需要 qid/resource_id)
        question_context = None
        
        # 检查 session 文件是否存在（判断是否为新 session）
        from pathlib import Path
        artifacts_dir = Path("artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("backend/artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("/root/usr/skill_agent_demo/backend/artifacts")
        
        session_file = artifacts_dir / user_id / f"{session_id}.md"
        is_new_session = not session_file.exists()
        
        # 🆕 快捷问答（action_type）也需要 question_context，即使 session 已存在
        # 这样 AI 才能理解 "this solution"、"this concept" 等指代词
        needs_question_context = is_new_session or request.action_type
        
        if needs_question_context:
            # 方式 1: 前端直接传入 question_context
            if request.question_context:
                question_context = request.question_context
                logger.info(f"✅ Using question context from request: {len(question_context)} chars")
            # 方式 2: 通过 qid/resource_id 从 StudyX 获取
            elif effective_qid and token:
                # 🆕 检查 qid 格式：StudyX API 需要 slug 格式（如 4merhtg），不能是纯数字
                if effective_qid.isdigit():
                    logger.warning(f"⚠️ qid '{effective_qid}' is numeric format (question_id), not slug format. Skipping API call.")
                    logger.warning(f"💡 Frontend should pass slug format qid/resource_id (e.g., '4merhtg'), not question_id")
                else:
                    reason = "new session" if is_new_session else f"quick action '{request.action_type}'"
                    logger.info(f"📡 Fetching question context ({reason}) from StudyX (qid={effective_qid}, env={env})...")
                    question_context = await fetch_question_context_from_studyx(effective_qid, token, env)
                    if question_context:
                        logger.info(f"✅ Question context fetched: {len(question_context)} chars")
                    else:
                        logger.warning(f"⚠️ Failed to fetch question context for qid={effective_qid} (API permission issue?)")
        else:
            logger.info(f"📂 Existing session without action_type, skipping question context fetch")
        
        # 🔒 获取 session 锁（防止同一会话的并发修改）
        lock = await get_session_lock(session_id)
        
        async with lock:
            logger.info(f"🔒 Acquired lock for session: {session_id}")
            
            # 🔥 调用完整的 skill 框架流程（传递完整的 file_uris 数组）
            result = await execute_skill_pipeline(
                message=message,
                user_id=user_id,
                session_id=session_id,
                orchestrator=orchestrator,
                quantity_override=None,
                skill_hint=None,
                file_uris=file_uris if file_uris else None,  # 🆕 传递多文件 URI 列表
                referenced_text=request.referenced_text,  # 🆕 传递引用文本
                action_type=request.action_type,  # 🆕 传递快捷操作类型
                files=files,  # 🆕 统一的文件信息数组（用于回显）
                file_url=request.file_url,  # 兼容旧版
                file_name=request.file_name,  # 兼容旧版
                language=language,  # 🆕 传递语言设置
                question_context=question_context  # 🆕 传递题目上下文
            )
            
            logger.info(f"🔓 Released lock for session: {session_id}")
        
        # 检查执行结果
        if result.get("success") == False:
            return {
                "code": 500,
                "msg": result.get("message", "Skill execution failed"),
                "data": None
            }
        
        # 构建响应
        original_content_type = result.get("content_type", "unknown")
        intent = result.get("intent", "unknown")
        # 🆕 兼容 content 和 response_content（Plan Skill 使用 response_content）
        original_content = result.get("content") or result.get("response_content") or {}
        
        # 🆕 提取 topic（优先从 result 直接获取，其次从 content 中）
        # orchestrator 已经将 actual_topic 放入 result["topic"]
        topic = result.get("topic") or ""
        if not topic and isinstance(original_content, dict):
            topic = original_content.get("title") or original_content.get("topic") or original_content.get("concept") or ""
        
        # 🔥 临时限制：将所有非文本格式转换为纯文本输出
        # 前端目前只支持文本渲染，后续支持其他格式后可移除此限制
        content_type, content = _convert_to_text_format(original_content_type, original_content, topic)
        
        # 🆕 提取 token_usage
        token_usage = result.get("token_usage", {})
        
        # 🆕 记录 token 使用到文件（按天切分）
        try:
            token_stats = get_token_stats_service()
            token_stats.record_usage(
                user_id=user_id,
                session_id=session_id,
                message=message,
                intent=intent,
                content_type=content_type,
                token_usage=token_usage,
                file_uris=file_uris if file_uris else None
            )
        except Exception as stats_error:
            logger.warning(f"⚠️ Failed to record token stats: {stats_error}")
        
        # 🆕 提取 context_stats（如果有的话）
        context_stats = result.get("context_stats", {})
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "data": {
                "session_id": session_id,  # 🆕 返回 session_id 供前端使用
                "content_type": content_type,
                "intent": intent,
                "topic": topic,
                "content": content,
                "token_usage": token_usage,  # 🆕 暴露 token 统计
                "context_stats": context_stats  # 🆕 暴露上下文统计
            }
        }
        
    except Exception as e:
        logger.error(f"❌ chat error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}
    finally:
        # 🆕 清除请求上下文中的用户 token
        clear_user_api_token()


# ============= Token 统计接口 =============

@router.get("/token-stats/today", response_model=Dict[str, Any])
async def get_today_token_stats():
    """
    获取今天的 Token 使用汇总
    
    返回格式:
    ```json
    {
        "code": 0,
        "msg": "Request succeeded",
        "data": {
            "date": "2025-11-27",
            "summary": {
                "total_requests": 100,
                "total_internal_tokens": 50000,
                "intent_router_tokens": 1500,
                "skill_execution_tokens": 48000,
                "memory_operation_tokens": 500,
                "external_api_calls": 30,
                "llm_calls": 70
            }
        }
    }
    ```
    """
    try:
        token_stats = get_token_stats_service()
        summary = token_stats.get_today_summary()
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "data": summary
        }
    except Exception as e:
        logger.error(f"❌ get_today_token_stats error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


@router.get("/token-stats/records", response_model=Dict[str, Any])
async def get_token_stats_records(limit: int = 100):
    """
    获取今天的 Token 使用详细记录
    
    Args:
        limit: 返回记录数量限制（默认100）
    
    返回格式:
    ```json
    {
        "code": 0,
        "msg": "Request succeeded",
        "data": {
            "records": [
                {
                    "timestamp": "2025-11-27T10:30:00",
                    "user_id": "user_kimi",
                    "session_id": "session_xxx",
                    "message": "给我3道题...",
                    "intent": "quiz_request",
                    "content_type": "quiz_set",
                    "token_usage": {...}
                }
            ]
        }
    }
    ```
    """
    try:
        token_stats = get_token_stats_service()
        records = token_stats.get_today_records(limit=limit)
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "data": {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "count": len(records),
                "records": records
            }
        }
    except Exception as e:
        logger.error(f"❌ get_token_stats_records error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


@router.get("/token-stats/dates", response_model=Dict[str, Any])
async def list_token_stats_dates():
    """
    列出所有有统计数据的日期
    
    返回格式:
    ```json
    {
        "code": 0,
        "msg": "Request succeeded",
        "data": {
            "dates": ["2025-11-27", "2025-11-26", "2025-11-25"]
        }
    }
    ```
    """
    try:
        token_stats = get_token_stats_service()
        dates = token_stats.list_available_dates()
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "data": {
                "dates": dates
            }
        }
    except Exception as e:
        logger.error(f"❌ list_token_stats_dates error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


@router.get("/token-stats/{target_date}", response_model=Dict[str, Any])
async def get_token_stats_by_date(target_date: str):
    """
    获取指定日期的 Token 统计
    
    Args:
        target_date: 日期字符串，格式 YYYY-MM-DD
    
    返回格式:
    ```json
    {
        "code": 0,
        "msg": "Request succeeded",
        "data": {
            "date": "2025-11-26",
            "summary": {...},
            "records": [...]
        }
    }
    ```
    """
    try:
        token_stats = get_token_stats_service()
        stats = token_stats.get_stats_by_date(target_date)
        
        if stats is None:
            return {
                "code": 404,
                "msg": f"No stats found for {target_date}",
                "data": None
            }
        
        return {
            "code": 0,
            "msg": "Request succeeded",
            "data": stats
        }
    except Exception as e:
        logger.error(f"❌ get_token_stats_by_date error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}


# ============= 题目聊天历史接口（兼容旧接口） =============


@router.get("/chat/history", response_model=Dict[str, Any])
async def get_homework_chat_history(
    question_id: str = Query(..., alias="aiQuestionId", description="题目 ID"),
    answer_id: str = Query(..., alias="answerId", description="答案 ID")
):
    """
    获取题目下的聊天历史（兼容旧接口 /chat/getHomeworkChatListV2）
    
    参数:
    - aiQuestionId: 题目 ID
    - answerId: 答案 ID
    
    返回:
    ```json
    {
        "code": 0,
        "msg": "success",
        "data": {
            "question_id": "Q123",
            "answer_id": "A456",
            "chat_list": [
                {
                    "turn": 1,
                    "timestamp": "2025-12-15T10:30:00",
                    "user_message": "这步怎么理解",
                    "assistant_message": "这一步是...",
                    "referenced_text": "8x-31=-29"
                }
            ],
            "total": 5
        }
    }
    ```
    """
    import os
    import re
    from pathlib import Path
    
    try:
        # 根据 question_id 和 answer_id 构建 session_id
        session_id = f"q{question_id}_a{answer_id}"
        
        logger.info(f"📜 Getting chat history for question={question_id}, answer={answer_id}")
        
        # 查找对应的 MD 文件（从项目根目录的 backend/artifacts）
        # 支持从 backend 目录运行或从项目根目录运行
        artifacts_dir = Path("artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("backend/artifacts")
        if not artifacts_dir.exists():
            artifacts_dir = Path("/root/usr/skill_agent_demo/backend/artifacts")
        
        chat_list = []
        
        # 🆕 遍历所有用户目录，找最近修改的 session 文件
        session_file = None
        latest_mtime = 0
        selected_user_dir = None
        
        for user_dir in artifacts_dir.iterdir():
            if not user_dir.is_dir():
                continue
            
            potential_file = user_dir / f"{session_id}.md"
            if potential_file.exists():
                mtime = potential_file.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    session_file = potential_file
                    selected_user_dir = user_dir
        
        # 处理找到的文件
        if session_file and selected_user_dir:
            user_dir = selected_user_dir
            logger.info(f"📄 Found session file: {session_file} (user={user_dir.name})")
            
            # 解析 MD 文件
            content = session_file.read_text(encoding='utf-8')
            
            # 使用正则解析每一轮对话
            # 格式: ## Turn 1 - 07:25:17
            #       ### 👤 User Query
            #       用户消息
            #       ### 🤖 Agent Response
            #       ...
            turn_pattern = r'## Turn (\d+) - (\d{2}:\d{2}:\d{2})\s*\n+### 👤 User Query\s*\n(.*?)### 🤖 Agent Response\s*\n(.*?)(?=## Turn |\Z)'
            matches = re.findall(turn_pattern, content, re.DOTALL)
            
            logger.info(f"📊 Found {len(matches)} turns in MD file")
            
            # 🆕 加载反馈数据
            feedback_map = {}
            feedback_dir = Path("feedback")
            if not feedback_dir.exists():
                feedback_dir = Path("backend/feedback")
            if not feedback_dir.exists():
                feedback_dir = Path("/root/usr/skill_agent_demo/backend/feedback")
            
            # 查找该用户的反馈文件
            user_id = user_dir.name
            user_feedback_file = feedback_dir / f"{user_id}_feedback.json"
            if user_feedback_file.exists():
                try:
                    with open(user_feedback_file, 'r', encoding='utf-8') as f:
                        feedback_list = json.load(f)
                        for fb in feedback_list:
                            if fb.get("session_id") == session_id:
                                turn_key = fb.get("turn_number")
                                feedback_map[turn_key] = {
                                    "type": fb.get("feedback_type"),
                                    "reason": fb.get("report_reason"),
                                    "timestamp": fb.get("timestamp")
                                }
                except Exception as fb_err:
                    logger.warning(f"⚠️ Failed to load feedback: {fb_err}")
            
            # 🆕 加载附件数据（从 session metadata）
            attachments_map = {}
            metadata_file = user_dir / f"{session_id}_metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        last_turn_attachments = metadata.get("last_turn_attachments", {})
                        for turn_key, attach_data in last_turn_attachments.items():
                            attachments_map[int(turn_key)] = attach_data
                except Exception as meta_err:
                    logger.warning(f"⚠️ Failed to load attachments metadata: {meta_err}")
                
            for match in matches:
                turn_num = int(match[0])
                timestamp = match[1]
                user_section = match[2].strip()
                assistant_section = match[3].strip()
                
                # 用户消息就是 User Query 下面的内容
                user_message = user_section.split('\n')[0] if user_section else ""
                
                # 🆕 提取附件信息（从 JSON attachments 字段提取）
                files = None
                referenced_text = None
                
                # 尝试从 attachments 字段提取 files 数组
                attachments_match = re.search(r'"attachments":\s*(\{[^}]*\})', assistant_section)
                if attachments_match:
                    try:
                        attachments_data = json.loads(attachments_match.group(1))
                        files = attachments_data.get("files")
                        referenced_text = attachments_data.get("referenced_text")
                    except json.JSONDecodeError:
                        # 旧格式兼容：使用正则提取
                        attachments_str = attachments_match.group(1)
                        # 提取 file_url（旧格式）
                        file_url_match = re.search(r'"file_url":\s*"([^"]*)"', attachments_str)
                        # 提取 file_name（旧格式）
                        file_name_match = re.search(r'"file_name":\s*"([^"]*)"', attachments_str)
                        # 转换为新的 files 格式
                        if file_url_match or file_name_match:
                            files = []
                            if file_url_match:
                                files.append({"type": "image", "url": file_url_match.group(1)})
                            if file_name_match:
                                files.append({"type": "document", "name": file_name_match.group(1)})
                        # 提取 referenced_text
                        ref_text_match = re.search(r'"referenced_text":\s*"([^"]*)"', attachments_str)
                        if ref_text_match:
                            referenced_text = ref_text_match.group(1)
                
                # 兼容旧格式：直接从 assistant_section 提取 referenced_text
                if not referenced_text:
                    ref_text_match = re.search(r'"referenced_text":\s*"([^"]*)"', assistant_section)
                    referenced_text = ref_text_match.group(1) if ref_text_match else None
                
                # 提取助手回复的摘要（从 JSON 代码块或 text 字段提取）
                assistant_message = ""
                
                # 方法1: 尝试从 JSON 代码块中解析 text 字段
                json_block_match = re.search(r'```json\s*\n(\{[\s\S]*?\})\s*\n```', assistant_section)
                if json_block_match:
                    try:
                        json_content = json.loads(json_block_match.group(1))
                        if isinstance(json_content, dict) and "text" in json_content:
                            assistant_message = json_content["text"]
                            logger.debug(f"📝 Method 1 succeeded for turn {turn_num}, text length: {len(assistant_message)}")
                    except json.JSONDecodeError as e:
                        logger.debug(f"📝 Method 1 JSON parse failed for turn {turn_num}: {e}")
                    
                # 方法2: 从 details 块中的 JSON 解析（结构化数据）
                if not assistant_message:
                    # 使用更可靠的正则：匹配到 \n} 结尾的完整 JSON 对象
                    details_match = re.search(r'<details>[\s\S]*?```json\s*\n(\{[\s\S]+?\n\})\s*\n```', assistant_section)
                    if details_match:
                        try:
                            structured_json = json.loads(details_match.group(1))
                            # 优先从 agent_response.content.text 获取
                            agent_resp = structured_json.get("agent_response", {})
                            content = agent_resp.get("content", {})
                            skill = agent_resp.get("skill", "")
                            
                            if isinstance(content, dict):
                                if "text" in content:
                                    # 普通 chat 响应
                                    assistant_message = content["text"]
                                    logger.debug(f"📝 Method 2 (details.text) succeeded for turn {turn_num}")
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
                                    logger.debug(f"📝 Method 2 (details.explain_skill) succeeded for turn {turn_num}")
                                elif "flashcards" in content:
                                    # flashcard_skill 响应
                                    flashcards = content.get("flashcards", [])
                                    assistant_message = f"已生成 {len(flashcards)} 张闪卡"
                                    if flashcards and isinstance(flashcards[0], dict):
                                        first_card = flashcards[0]
                                        front = first_card.get("front", first_card.get("question", ""))
                                        assistant_message += f"\n\n**第1张**: {front[:100]}..."
                                    logger.debug(f"📝 Method 2 (details.flashcard_skill) succeeded for turn {turn_num}")
                                elif "questions" in content:
                                    # quiz_skill 响应
                                    questions = content.get("questions", [])
                                    assistant_message = f"已生成 {len(questions)} 道练习题"
                                    if questions and isinstance(questions[0], dict):
                                        first_q = questions[0]
                                        q_text = first_q.get("question", first_q.get("text", ""))
                                        assistant_message += f"\n\n**第1题**: {q_text[:100]}..."
                                    logger.debug(f"📝 Method 2 (details.quiz_skill) succeeded for turn {turn_num}")
                        except json.JSONDecodeError as e:
                            logger.debug(f"📝 Method 2 (details) JSON parse failed for turn {turn_num}: {e}")
                    
                # 方法3: 使用改进的正则（支持转义字符）
                if not assistant_message:
                    # 匹配 "text": "..." 包括转义字符
                    text_match = re.search(r'"text":\s*"((?:[^"\\]|\\.)*)"', assistant_section)
                    if text_match:
                        assistant_message = text_match.group(1)
                        # 只处理常见的 JSON 转义字符，保留 LaTeX 反斜杠
                        assistant_message = assistant_message.replace('\\n', '\n').replace('\\r', '\r').replace('\\"', '"')
                
                # 方法4: 提取 直觉理解
                if not assistant_message:
                    intuition_match = re.search(r'#### 📚 直觉理解\s*\n(.+?)(?=\n####|\n##|\Z)', assistant_section, re.DOTALL)
                    if intuition_match:
                        assistant_message = intuition_match.group(1).strip()
                
                # 方法5: 取前 500 字符作为摘要
                if not assistant_message:
                    assistant_message = assistant_section[:500].replace('\n', ' ')
                
                # 🆕 获取该轮的反馈状态
                feedback = feedback_map.get(turn_num)
                
                # 🆕 从 attachments_map 获取附件信息（优先级高于 MD 文件解析）
                turn_attachments = attachments_map.get(turn_num, {})
                if turn_attachments:
                    # 优先使用 metadata 中的 files 数组
                    if turn_attachments.get("files"):
                        files = turn_attachments.get("files")
                    # 兼容旧格式
                    elif turn_attachments.get("file_url") or turn_attachments.get("file_name"):
                        files = []
                        if turn_attachments.get("file_url"):
                            files.append({"type": "image", "url": turn_attachments.get("file_url")})
                        if turn_attachments.get("file_name"):
                            files.append({"type": "document", "name": turn_attachments.get("file_name")})
                    
                    referenced_text = turn_attachments.get("referenced_text") or referenced_text
                
                chat_list.append({
                    "turn": turn_num,
                    "timestamp": timestamp,
                    "user_message": user_message,
                    "assistant_message": assistant_message,  # JSON 解析已处理转义
                    "referenced_text": referenced_text,
                    "files": files,  # 🆕 统一的文件信息数组
                    "feedback": feedback  # 🆕 反馈状态
                })
            
            logger.info(f"📋 Parsed {len(chat_list)} chat entries")
        
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "question_id": question_id,
                "answer_id": answer_id,
                "session_id": session_id,
                "chat_list": chat_list,
                "total": len(chat_list)
            }
        }
        
    except Exception as e:
        logger.error(f"❌ get_homework_chat_history error: {e}", exc_info=True)
        return {"code": 500, "msg": str(e), "data": None}

