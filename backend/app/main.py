"""
Skill Agent Demo - FastAPI 主应用入口

这是一个智能学习助手系统，通过意图识别、记忆管理和技能编排，
为用户提供练习题生成和概念讲解等学习服务。
"""
import logging
import os
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from .config import settings

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def reset_storage_files():
    """
    重置存储文件（memory 和 intent router 数据）
    在开发环境中，后台重启时自动清空，保持干净状态
    """
    storage_dir = Path("memory_storage")
    
    if not storage_dir.exists():
        logger.info("📁 Creating memory_storage directory")
        storage_dir.mkdir(parents=True, exist_ok=True)
        return
    
    # 重置 intent_router_output.json
    intent_router_file = storage_dir / "intent_router_output.json"
    if intent_router_file.exists():
        initial_intent_data = {
            "description": "Intent Router 实时输出记录 (Phase 3 架构)",
            "latest": {},
            "history": [],
            "stats": {
                "total_requests": 0,
                "rule_based_success": 0,
                "llm_fallback": 0,
                "rule_success_rate": "0.0%"
            }
        }
        with open(intent_router_file, 'w', encoding='utf-8') as f:
            json.dump(initial_intent_data, f, indent=2, ensure_ascii=False)
        logger.info("🧹 Reset intent_router_output.json")
    
    # 删除所有 session JSON 文件
    session_files = list(storage_dir.glob("*-session.json"))
    for session_file in session_files:
        session_file.unlink()
        logger.info(f"🧹 Deleted {session_file.name}")
    
    # 删除所有 user profile JSON 文件
    profile_files = list(storage_dir.glob("*-profile.json"))
    for profile_file in profile_files:
        profile_file.unlink()
        logger.info(f"🧹 Deleted {profile_file.name}")
    
    total_deleted = len(session_files) + len(profile_files)
    if total_deleted > 0:
        logger.info(f"✅ Cleaned up {total_deleted} memory files")
    else:
        logger.info("✅ Memory storage already clean")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 Starting Skill Agent Demo API")
    logger.info(f"📍 Gemini Model: {settings.GEMINI_MODEL}")
    logger.info(f"💾 S3 Storage: {'Enabled' if settings.USE_S3_STORAGE else 'Disabled'}")
    
    # 🆕 重启时自动清理 memory 和 intent router 数据
    # ⚠️ 开发环境下总是清理（即使S3 enabled，本地也可能有缓存文件）
    logger.info("🧹 Resetting local storage on startup...")
    reset_storage_files()
    
    if settings.USE_S3_STORAGE:
        logger.info(f"🗂️  S3 Bucket: {settings.AWS_S3_BUCKET}")
        logger.info(f"📁 Memory Folder: {settings.S3_MEMORY_FOLDER}")
        logger.info(f"📁 Session Folder: {settings.S3_SESSION_FOLDER}")
    
    yield
    
    # 关闭时执行
    logger.info("👋 Shutting down Skill Agent Demo API")


# 创建 FastAPI 应用实例
app = FastAPI(
    title="Skill Agent Demo API",
    description="智能学习助手 - 通过意图识别和技能编排提供个性化学习服务",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS - 允许所有来源（包括 file:// 协议用于静态 HTML）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源（包括静态 HTML 文件）
    allow_credentials=False,  # 当 allow_origins=["*"] 时必须为 False
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# 健康检查端点
@app.get("/health", tags=["Health"])
async def health_check():
    """
    健康检查端点
    
    返回:
        dict: 系统健康状态信息
    """
    return {
        "status": "healthy",
        "service": "Skill Agent Demo API",
        "version": "1.0.0",
        "gemini_model": settings.GEMINI_MODEL,
        "s3_enabled": settings.USE_S3_STORAGE
    }


@app.get("/", tags=["Root"])
async def root():
    """
    根路径 - API 欢迎信息
    """
    return {
        "message": "Welcome to Skill Agent Demo API",
        "docs": "/docs",
        "health": "/health"
    }


# 在这里注册路由
from .api import intent, agent, history, auth, external, external_web, chat, studyx_agent, feedback

app.include_router(intent.router)
app.include_router(agent.router)
app.include_router(history.router)
app.include_router(auth.router)
app.include_router(external.router)  # 外部 API 接口（含 skill 框架）- App 端
app.include_router(external_web.router)  # 🆕 Web 专用 API（SSE 流式 + Edit/Regenerate）
app.include_router(external_web.studyx_router)  # 🆕 StudyX 兼容接口（newHomeChatQuestionV2/newHwRefreshAnswer）
app.include_router(chat.router)  # 🆕 纯 Chat API（简化版，不走 skill 框架）
app.include_router(studyx_agent.router)  # 🆕 StudyX Agent API（新的 createFlashcardAgent 接口）
app.include_router(feedback.router)  # 🆕 用户反馈 + 聊天历史 API

# TODO: 在后续任务中添加更多路由
# from .api import skills
# app.include_router(skills.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )

