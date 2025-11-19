"""
应用配置管理 - 使用 Pydantic Settings 管理环境变量
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """应用配置类"""
    
    # Google Gemini API 配置
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash"  # ⚠️ 使用支持 thinking 模式的模型
    
    # OpenAI API 配置（用于 MindMap Skill - 可选）
    OPENAI_API_KEY: str = ""  # 请从环境变量或 .env 文件中加载
    OPENAI_MODEL: str = "gpt-4o-2024-08-06"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_TIMEOUT: float = 30.0
    
    # AWS S3 配置（用于 demo 阶段存储数据）
    USE_S3_STORAGE: bool = False  # ⚠️ 开发环境使用本地存储
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    AWS_S3_BUCKET: str = "skill-agent-demo"
    
    # S3 文件夹结构
    S3_MEMORY_FOLDER: str = "memory_profiles"
    S3_SESSION_FOLDER: str = "session_contexts"
    S3_SKILLS_FOLDER: str = "skills"
    
    # 应用配置
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3100"
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )
    
    @property
    def cors_origins_list(self) -> List[str]:
        """将 CORS_ORIGINS 字符串转换为列表"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


# 创建全局配置实例
settings = Settings()

