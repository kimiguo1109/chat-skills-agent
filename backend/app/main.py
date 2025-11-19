"""
Skill Agent Demo - FastAPI 主应用入口

这是一个智能学习助手系统，通过意图识别、记忆管理和技能编排，
为用户提供练习题生成和概念讲解等学习服务。
"""
import logging
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info("🚀 Starting Skill Agent Demo API")
    logger.info(f"📍 Gemini Model: {settings.GEMINI_MODEL}")
    logger.info(f"💾 S3 Storage: {'Enabled' if settings.USE_S3_STORAGE else 'Disabled'}")
    
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
from .api import intent, agent, history

app.include_router(intent.router)
app.include_router(agent.router)
app.include_router(history.router)

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

