"""
Feedback API - 用户反馈接口

支持功能：
1. 点赞/取消点赞（Like/Dislike）
2. 反馈报告（Feedback Report）
3. 聊天历史记录（Chat History）
"""
import os
import re
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["feedback"])

# ============= 数据模型 =============

class FeedbackRequest(BaseModel):
    """反馈请求"""
    user_id: str = Field(..., description="用户 ID")
    session_id: str = Field(..., description="会话 ID")
    turn_number: int = Field(..., description="对话轮次")
    feedback_type: str = Field(..., description="反馈类型: like, dislike, report")
    report_reason: Optional[str] = Field(None, description="报告原因（当 feedback_type=report 时）")
    report_detail: Optional[str] = Field(None, description="报告详情")


class FeedbackResponse(BaseModel):
    """反馈响应"""
    success: bool
    message: str
    feedback_id: Optional[str] = None


class ChatMessage(BaseModel):
    """单条聊天消息"""
    turn_number: int
    timestamp: str
    role: str  # "user" or "assistant"
    content: str
    intent: Optional[str] = None
    content_type: Optional[str] = None
    topic: Optional[str] = None
    feedback: Optional[Dict[str, Any]] = None  # 用户反馈信息


class ChatHistoryResponse(BaseModel):
    """聊天历史响应"""
    user_id: str
    session_id: str
    messages: List[ChatMessage]
    total_turns: int
    has_more: bool
    session_started: Optional[str] = None
    last_updated: Optional[str] = None


class SessionListItem(BaseModel):
    """会话列表项"""
    session_id: str
    started: str
    last_updated: str
    turn_count: int
    topics: List[str]


class SessionListResponse(BaseModel):
    """会话列表响应"""
    user_id: str
    sessions: List[SessionListItem]
    total: int


# ============= 存储路径 =============

def get_artifacts_path() -> Path:
    """获取 artifacts 存储路径"""
    return Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / "artifacts"


def get_feedback_path() -> Path:
    """获取反馈存储路径"""
    feedback_path = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / "feedback"
    feedback_path.mkdir(parents=True, exist_ok=True)
    return feedback_path


# ============= 反馈接口 =============

@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest):
    """
    提交用户反馈（点赞/取消点赞/报告问题）
    
    feedback_type 支持:
    - like: 点赞
    - dislike: 取消点赞/踩
    - report: 报告问题
    
    report_reason 支持（当 feedback_type=report 时）:
    - calculation_error: 计算有错误
    - steps_confusing: 步骤混乱或不正确
    - wrong_answer: 最终答案错误
    - other: 其他问题
    """
    try:
        feedback_path = get_feedback_path()
        
        # 生成反馈 ID
        feedback_id = f"fb_{request.user_id}_{request.session_id}_{request.turn_number}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # 构建反馈数据
        feedback_data = {
            "feedback_id": feedback_id,
            "user_id": request.user_id,
            "session_id": request.session_id,
            "turn_number": request.turn_number,
            "feedback_type": request.feedback_type,
            "report_reason": request.report_reason,
            "report_detail": request.report_detail,
            "timestamp": datetime.now().isoformat(),
        }
        
        # 存储到 JSON 文件
        user_feedback_file = feedback_path / f"{request.user_id}_feedback.json"
        
        # 读取现有反馈
        existing_feedback = []
        if user_feedback_file.exists():
            with open(user_feedback_file, "r", encoding="utf-8") as f:
                existing_feedback = json.load(f)
        
        # 检查是否已存在相同 turn 的反馈（更新而非新增）
        updated = False
        for i, fb in enumerate(existing_feedback):
            if (fb["session_id"] == request.session_id and 
                fb["turn_number"] == request.turn_number):
                existing_feedback[i] = feedback_data
                updated = True
                break
        
        if not updated:
            existing_feedback.append(feedback_data)
        
        # 写回文件
        with open(user_feedback_file, "w", encoding="utf-8") as f:
            json.dump(existing_feedback, f, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ Feedback submitted: {feedback_id} ({request.feedback_type})")
        
        return FeedbackResponse(
            success=True,
            message="Thanks for your feedback!",
            feedback_id=feedback_id
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to submit feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit feedback: {str(e)}")


@router.get("/feedback/{user_id}", response_model=List[Dict[str, Any]])
async def get_user_feedback(
    user_id: str,
    session_id: Optional[str] = Query(None, description="筛选特定会话")
):
    """
    获取用户的反馈记录
    """
    try:
        feedback_path = get_feedback_path()
        user_feedback_file = feedback_path / f"{user_id}_feedback.json"
        
        if not user_feedback_file.exists():
            return []
        
        with open(user_feedback_file, "r", encoding="utf-8") as f:
            feedback_list = json.load(f)
        
        # 筛选特定会话
        if session_id:
            feedback_list = [fb for fb in feedback_list if fb["session_id"] == session_id]
        
        return feedback_list
        
    except Exception as e:
        logger.error(f"❌ Failed to get feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get feedback: {str(e)}")


# ============= 聊天历史接口 =============

def parse_md_to_messages(md_content: str) -> List[Dict[str, Any]]:
    """
    解析 MD 文件内容为消息列表
    """
    messages = []
    
    # 匹配 Turn 块
    turn_pattern = r'## Turn (\d+) - ([\d:]+)\s*\n\n### 👤 User Query\s*\n(.+?)\n\n### 🤖 Agent Response\s*\n\*\*Type\*\*: (\w+).*?\| \*\*Topic\*\*: ([^\|]+?)(?:\||\n)'
    
    # 更宽松的匹配模式
    turn_blocks = re.split(r'(?=## Turn \d+)', md_content)
    
    for block in turn_blocks:
        if not block.strip() or not block.startswith('## Turn'):
            continue
        
        try:
            # 提取 Turn 号和时间
            header_match = re.match(r'## Turn (\d+) - ([\d:]+)', block)
            if not header_match:
                continue
            
            turn_number = int(header_match.group(1))
            timestamp = header_match.group(2)
            
            # 提取用户查询
            user_query_match = re.search(r'### 👤 User Query\s*\n(.+?)(?=\n\n### 🤖|$)', block, re.DOTALL)
            user_query = user_query_match.group(1).strip() if user_query_match else ""
            
            # 提取 Agent 响应信息
            response_match = re.search(r'\*\*Type\*\*: (\w+).*?\| \*\*Topic\*\*: ([^\|]+)', block)
            content_type = response_match.group(1) if response_match else "text"
            topic = response_match.group(2).strip() if response_match else ""
            
            # 提取 intent（从 JSON 块中）
            intent = "other"
            json_match = re.search(r'```json\s*\n(\{[\s\S]*?\})\s*\n```', block)
            if json_match:
                try:
                    json_data = json.loads(json_match.group(1))
                    if "intent" in json_data:
                        intent_data = json_data.get("intent", {})
                        if isinstance(intent_data, dict):
                            intent = intent_data.get("intent", "other")
                        else:
                            intent = str(intent_data)
                except:
                    pass
            
            # 提取响应文本（简化版）
            response_text = ""
            if content_type == "text":
                text_match = re.search(r'"text":\s*"([^"]+)"', block)
                if text_match:
                    response_text = text_match.group(1)[:200] + "..."
            
            # 添加用户消息
            messages.append({
                "turn_number": turn_number,
                "timestamp": timestamp,
                "role": "user",
                "content": user_query,
                "intent": None,
                "content_type": None,
                "topic": None
            })
            
            # 添加助手消息
            messages.append({
                "turn_number": turn_number,
                "timestamp": timestamp,
                "role": "assistant",
                "content": response_text or f"[{content_type}]",
                "intent": intent,
                "content_type": content_type,
                "topic": topic
            })
            
        except Exception as e:
            logger.warning(f"⚠️  Failed to parse turn block: {e}")
            continue
    
    return messages


@router.get("/history/{user_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    user_id: str,
    session_id: Optional[str] = Query(None, description="会话 ID（不传则返回最新会话）"),
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(50, ge=1, le=100, description="每页消息数")
):
    """
    获取聊天历史记录
    
    - 如果不传 session_id，返回用户最新的会话
    - 支持分页
    - 返回结构化的消息列表
    """
    try:
        artifacts_path = get_artifacts_path()
        user_path = artifacts_path / user_id
        
        if not user_path.exists():
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        
        # 查找 session 文件
        if session_id:
            session_file = user_path / f"{session_id}.md"
            if not session_file.exists():
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        else:
            # 获取最新的 session 文件
            md_files = list(user_path.glob("*.md"))
            if not md_files:
                raise HTTPException(status_code=404, detail=f"No sessions found for user {user_id}")
            
            # 按修改时间排序，取最新的
            md_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            session_file = md_files[0]
            session_id = session_file.stem
        
        # 读取并解析 MD 文件
        with open(session_file, "r", encoding="utf-8") as f:
            md_content = f.read()
        
        # 解析消息
        messages = parse_md_to_messages(md_content)
        
        # 加载用户反馈
        feedback_path = get_feedback_path()
        user_feedback_file = feedback_path / f"{user_id}_feedback.json"
        feedback_map = {}
        if user_feedback_file.exists():
            with open(user_feedback_file, "r", encoding="utf-8") as f:
                feedback_list = json.load(f)
                for fb in feedback_list:
                    if fb["session_id"] == session_id:
                        key = fb["turn_number"]
                        feedback_map[key] = {
                            "type": fb["feedback_type"],
                            "reason": fb.get("report_reason"),
                            "timestamp": fb["timestamp"]
                        }
        
        # 添加反馈信息到消息
        for msg in messages:
            if msg["turn_number"] in feedback_map:
                msg["feedback"] = feedback_map[msg["turn_number"]]
        
        # 获取 session 元数据
        session_started = None
        last_updated = None
        started_match = re.search(r'\*\*Started\*\*: (.+)', md_content)
        updated_match = re.search(r'\*\*Last Updated\*\*: (.+)', md_content)
        if started_match:
            session_started = started_match.group(1)
        if updated_match:
            last_updated = updated_match.group(1)
        
        # 分页
        total = len(messages)
        start = (page - 1) * limit
        end = start + limit
        paginated = messages[start:end]
        
        return ChatHistoryResponse(
            user_id=user_id,
            session_id=session_id,
            messages=[ChatMessage(**m) for m in paginated],
            total_turns=total // 2,  # 每个 turn 有 2 条消息（user + assistant）
            has_more=end < total,
            session_started=session_started,
            last_updated=last_updated
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get chat history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get chat history: {str(e)}")


@router.get("/sessions/{user_id}", response_model=SessionListResponse)
async def get_user_sessions(
    user_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50)
):
    """
    获取用户的所有会话列表
    """
    try:
        artifacts_path = get_artifacts_path()
        user_path = artifacts_path / user_id
        
        if not user_path.exists():
            return SessionListResponse(user_id=user_id, sessions=[], total=0)
        
        # 获取所有 session 文件
        md_files = list(user_path.glob("*.md"))
        
        sessions = []
        for md_file in md_files:
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read(2000)  # 只读取头部
                
                session_id = md_file.stem
                
                # 提取元数据
                started = ""
                last_updated = ""
                topics = []
                
                started_match = re.search(r'\*\*Started\*\*: (.+)', content)
                updated_match = re.search(r'\*\*Last Updated\*\*: (.+)', content)
                topics_match = re.search(r'📖 \*\*学习主题\*\*: (.+)', content)
                
                if started_match:
                    started = started_match.group(1)
                if updated_match:
                    last_updated = updated_match.group(1)
                if topics_match:
                    topics = [t.strip() for t in topics_match.group(1).split('、')]
                
                # 统计 turn 数量
                turn_count = len(re.findall(r'## Turn \d+', content))
                
                sessions.append(SessionListItem(
                    session_id=session_id,
                    started=started or md_file.stat().st_ctime.__str__(),
                    last_updated=last_updated or md_file.stat().st_mtime.__str__(),
                    turn_count=turn_count,
                    topics=topics[:5]  # 最多显示 5 个主题
                ))
            except Exception as e:
                logger.warning(f"⚠️  Failed to parse session file {md_file}: {e}")
                continue
        
        # 按最后更新时间排序
        sessions.sort(key=lambda s: s.last_updated, reverse=True)
        
        # 分页
        total = len(sessions)
        start = (page - 1) * limit
        end = start + limit
        paginated = sessions[start:end]
        
        return SessionListResponse(
            user_id=user_id,
            sessions=paginated,
            total=total
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to get sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get sessions: {str(e)}")

