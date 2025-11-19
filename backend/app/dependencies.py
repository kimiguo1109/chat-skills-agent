"""
共享依赖项
确保所有 API 端点使用相同的服务实例
"""
from app.core.memory_manager import MemoryManager
from app.core.skill_orchestrator import SkillOrchestrator
from app.services.gemini import GeminiClient


def get_memory_manager() -> MemoryManager:
    """获取 Memory Manager 单例"""
    if not hasattr(get_memory_manager, "_instance"):
        get_memory_manager._instance = MemoryManager(use_s3=False)
    return get_memory_manager._instance


def get_gemini_client() -> GeminiClient:
    """获取 Gemini Client 单例"""
    if not hasattr(get_gemini_client, "_instance"):
        get_gemini_client._instance = GeminiClient()
    return get_gemini_client._instance


def get_skill_orchestrator() -> SkillOrchestrator:
    """获取 SkillOrchestrator 实例"""
    return SkillOrchestrator(
        memory_manager=get_memory_manager(),
        llm_client=get_gemini_client()
    )


# 导出单例实例供直接使用
memory_manager = get_memory_manager()
gemini_client = get_gemini_client()

