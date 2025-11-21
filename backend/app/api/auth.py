"""
用户认证 API
提供简单的登录、登出和获取当前用户功能
"""

from fastapi import APIRouter, HTTPException, Response, Cookie
from pydantic import BaseModel, Field
from typing import Optional, Dict
import logging
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

# 示例用户数据库（实际应用中应该用真实数据库）
USERS_DB = {
    "user_kimi": {
        "user_id": "user_kimi",
        "username": "Kimi",
        "display_name": "Kimi",
        "avatar": "🤖",
        "created_at": "2025-11-20T00:00:00Z"
    },
    "user_alex": {
        "user_id": "user_alex",
        "username": "Alex",
        "display_name": "Alex",
        "avatar": "👨‍💻",
        "created_at": "2025-11-20T00:00:00Z"
    }
}

# 存储活跃会话（实际应用中应该用 Redis）
ACTIVE_SESSIONS: Dict[str, dict] = {}


class LoginRequest(BaseModel):
    """登录请求"""
    user_id: str = Field(..., description="用户 ID", examples=["user_kimi", "user_alex"])


class LoginResponse(BaseModel):
    """登录响应"""
    user_id: str = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    display_name: str = Field(..., description="显示名称")
    avatar: str = Field(..., description="头像（emoji）")
    session_token: str = Field(..., description="会话令牌")
    session_id: str = Field(..., description="会话 ID")


class UserInfo(BaseModel):
    """用户信息"""
    user_id: str = Field(..., description="用户 ID")
    username: str = Field(..., description="用户名")
    display_name: str = Field(..., description="显示名称")
    avatar: str = Field(..., description="头像（emoji）")
    session_id: str = Field(..., description="当前会话 ID")


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, response: Response):
    """
    用户登录
    
    示例用户：
    - user_kimi (Kimi 小助手 🤖)
    - user_alex (Alex Chen 👨‍💻)
    """
    user_id = request.user_id
    
    # 验证用户是否存在
    if user_id not in USERS_DB:
        logger.warning(f"❌ Login failed: user {user_id} not found")
        raise HTTPException(
            status_code=404,
            detail=f"User '{user_id}' not found. Available users: {list(USERS_DB.keys())}"
        )
    
    user = USERS_DB[user_id]
    
    # 生成会话令牌和会话 ID
    session_token = str(uuid.uuid4())
    session_id = f"{user_id}_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # 存储会话
    ACTIVE_SESSIONS[session_token] = {
        "user_id": user_id,
        "session_id": session_id,
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=7)).isoformat()
    }
    
    # 设置 Cookie（可选，前端也可以用 localStorage）
    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=7 * 24 * 60 * 60,  # 7 days
        httponly=False,  # 允许 JS 访问（演示用）
        samesite="lax"
    )
    
    logger.info(f"✅ User {user_id} logged in. Session: {session_id}")
    
    return LoginResponse(
        user_id=user["user_id"],
        username=user["username"],
        display_name=user["display_name"],
        avatar=user["avatar"],
        session_token=session_token,
        session_id=session_id
    )


@router.post("/logout")
async def logout(session_token: Optional[str] = Cookie(None)):
    """用户登出"""
    if not session_token or session_token not in ACTIVE_SESSIONS:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    user_id = ACTIVE_SESSIONS[session_token]["user_id"]
    del ACTIVE_SESSIONS[session_token]
    
    logger.info(f"✅ User {user_id} logged out")
    
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserInfo)
async def get_current_user(session_token: Optional[str] = Cookie(None)):
    """获取当前登录用户信息"""
    if not session_token or session_token not in ACTIVE_SESSIONS:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please login first."
        )
    
    session = ACTIVE_SESSIONS[session_token]
    user_id = session["user_id"]
    
    if user_id not in USERS_DB:
        raise HTTPException(status_code=404, detail="User not found")
    
    user = USERS_DB[user_id]
    
    return UserInfo(
        user_id=user["user_id"],
        username=user["username"],
        display_name=user["display_name"],
        avatar=user["avatar"],
        session_id=session["session_id"]
    )


@router.get("/users")
async def list_users():
    """列出所有可用用户（演示用）"""
    return {
        "users": [
            {
                "user_id": user["user_id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "avatar": user["avatar"]
            }
            for user in USERS_DB.values()
        ]
    }

