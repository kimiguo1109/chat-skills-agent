"""
共享依赖项
确保所有 API 端点使用相同的服务实例

🆕 已迁移到 Kimi (Moonshot AI) API
"""
from app.core.memory_manager import MemoryManager
from app.core.skill_orchestrator import SkillOrchestrator
from app.services.kimi import KimiClient  # 🆕 使用 Kimi Client
# from app.services.gemini import GeminiClient  # ⚠️ 已弃用


def get_memory_manager() -> MemoryManager:
    """获取 Memory Manager 单例"""
    if not hasattr(get_memory_manager, "_instance"):
        get_memory_manager._instance = MemoryManager(use_s3=False)
    return get_memory_manager._instance


def get_kimi_client() -> KimiClient:
    """获取 Kimi Client 单例（替代 Gemini）"""
    if not hasattr(get_kimi_client, "_instance"):
        get_kimi_client._instance = KimiClient()
    return get_kimi_client._instance


# 兼容性别名（保持向后兼容）
def get_gemini_client() -> KimiClient:
    """
    获取 LLM Client（兼容性别名）
    ⚠️ 现在返回 KimiClient，保持接口兼容
    """
    return get_kimi_client()


def get_skill_orchestrator() -> SkillOrchestrator:
    """获取 SkillOrchestrator 实例"""
    return SkillOrchestrator(
        memory_manager=get_memory_manager(),
        llm_client=get_kimi_client()  # 🆕 使用 Kimi Client
    )


# 导出单例实例供直接使用
memory_manager = get_memory_manager()
kimi_client = get_kimi_client()
gemini_client = kimi_client  # 兼容性别名

