"""
外部服务封装
"""
try:
    from .gemini import GeminiClient
except ImportError:
    GeminiClient = None  # Gemini 依赖未安装

__all__ = ["GeminiClient"]

