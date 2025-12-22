"""
应用配置管理 - 使用 Pydantic Settings 管理环境变量
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """应用配置类"""
    
    # Google Gemini API 配置（已弃用，迁移到 Kimi）
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    
    # Kimi (Moonshot AI) API 配置（通过 Novita AI）
    KIMI_API_KEY: str = "sk_RVzD0ExdrmLuQIcvC-UbUekNsbft0dVPiOq5Nh-1Xro"  # Novita AI API Key
    KIMI_BASE_URL: str = "https://api.novita.ai/openai"
    KIMI_MODEL: str = "moonshotai/kimi-k2-thinking"  # 支持 reasoning 模式
    
    # OpenAI API 配置（用于 MindMap Skill - 可选）
    OPENAI_API_KEY: str = ""  # 请从环境变量或 .env 文件中加载
    OPENAI_MODEL: str = "gpt-4o-2024-08-06"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_TIMEOUT: float = 30.0
    
    # 外部 API 配置（Flashcard / Quiz）
    EXTERNAL_API_TOKEN: str = ""
    EXTERNAL_FLASHCARD_API_URL: str = "https://test.istudyx.com/api/studyx/v5/cloud/note/flashcardsAndQuiz/createFlashcards"
    EXTERNAL_QUIZ_API_URL: str = "https://test.istudyx.com/api/studyx/v5/cloud/note/flashcardsAndQuiz/createQuizs"
    
    # 🆕 StudyX Agent API 配置（新的 createFlashcardAgent 接口）
    STUDYX_AGENT_API_URL: str = "https://test.istudyx.com/api/studyx/v5/cloud/note/flashcardsAndQuiz/createFlashcardAgent"
    STUDYX_AGENT_API_TOKEN: str = "eyJ0eXBlIjoiSldUIiwiZXhwIjoxNzY1MjY1NjQzLCJhbGciOiJIUzI1NiIsImlhdCI6MTc2Mzk2OTY0M30.eyJyb2xlY29kZSI6IjMwIiwidXNlcmd1aWQiOiIxNjU1NDg1NTY4NDYyNzUzNzkyIn0.99a6038d1303ff9b14b25b7c85248dfa"
    
    # AWS S3 配置（用于 demo 阶段存储数据）
    USE_S3_STORAGE: bool = True  # 启用 S3 存储（.env 文件中可以覆盖）
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

