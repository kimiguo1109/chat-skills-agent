"""
端到端测试 - Conversation Session Manager

测试完整对话流程：
1. 用户发送消息
2. IntentRouter 识别意图
3. SkillOrchestrator 执行技能
4. 自动追加到 MD 文件
5. 验证 MD 文件内容
"""

import pytest
import asyncio
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到 sys.path
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.skill_orchestrator import SkillOrchestrator
from app.core.memory_manager import MemoryManager
from app.core.intent_router import IntentRouter
from app.models.intent import IntentResult


class TestConversationE2E:
    """端到端测试"""
    
    @pytest.fixture
    def temp_storage(self):
        """创建临时存储目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def memory_manager(self, temp_storage):
        """创建 MemoryManager"""
        return MemoryManager(
            use_s3=False,
            local_storage_dir=temp_storage
        )
    
    @pytest.mark.asyncio
    async def test_single_conversation_turn(self, memory_manager, temp_storage):
        """测试单轮对话追加到 MD"""
        user_id = "user_test_e2e"
        session_id = "session_test_123"
        
        # 模拟 Intent Result
        intent_result = IntentResult(
            intent="explain_request",
            raw_text="什么是光合作用",
            topic="光合作用",
            confidence=0.95,
            parameters={"concept_name": "光合作用"}
        )
        
        # 模拟 Agent Response
        mock_result = {
            "concept": "光合作用",
            "intuition": "光合作用是植物的食物制造工厂",
            "formal_definition": "光合作用是绿色植物...",
            "examples": [{"example": "叶子为什么是绿色", "explanation": "因为..."}],
            "common_mistakes": [],
            "related_concepts": ["叶绿体"]
        }
        
        # 获取 ConversationSessionManager
        session_mgr = memory_manager.get_conversation_session_manager(user_id)
        
        # 开始 session
        session_id = await session_mgr.start_or_continue_session(
            intent_result.raw_text,
            timestamp=datetime.now()
        )
        
        assert session_id is not None
        
        # 追加 turn
        success = await session_mgr.append_turn({
            "user_query": intent_result.raw_text,
            "agent_response": {
                "skill": "explain_skill",
                "artifact_id": "test_artifact_123",
                "content": mock_result
            },
            "response_type": "explanation",
            "timestamp": datetime.now(),
            "intent": intent_result.model_dump(),
            "metadata": {
                "thinking_tokens": 500,
                "output_tokens": 300,
                "model": "kimi-k2-thinking"
            }
        })
        
        assert success is True
        
        # 验证 MD 文件
        md_file = session_mgr.current_session_file
        assert md_file.exists()
        
        content = md_file.read_text(encoding='utf-8')
        
        # 验证内容
        assert "Learning Session" in content
        assert "user_test_e2e" in content
        assert "什么是光合作用" in content
        assert "光合作用是植物的食物制造工厂" in content
        assert "Turn 1" in content
        assert "<details>" in content  # JSON 嵌入
        assert "📦" in content
    
    @pytest.mark.asyncio
    async def test_multiple_turns_same_session(self, memory_manager, temp_storage):
        """测试多轮对话（同一 session）"""
        user_id = "user_test_multi"
        
        # 创建 session manager
        session_mgr = memory_manager.get_conversation_session_manager(user_id)
        
        now = datetime.now()
        
        # Turn 1: 解释概念
        await session_mgr.start_or_continue_session("什么是光合作用", timestamp=now)
        await session_mgr.append_turn({
            "user_query": "什么是光合作用",
            "agent_response": {
                "skill": "explain_skill",
                "content": {"concept": "光合作用"}
            },
            "response_type": "explanation",
            "timestamp": now,
            "intent": {"type": "explain_request", "topic": "光合作用"},
            "metadata": {}
        })
        
        # Turn 2: 生成题目（2 分钟后）
        later = now + timedelta(minutes=2)
        await session_mgr.start_or_continue_session("给我三道题", timestamp=later)
        await session_mgr.append_turn({
            "user_query": "给我三道题",
            "agent_response": {
                "skill": "quiz_skill",
                "content": {"quiz_set_id": "test_quiz"}
            },
            "response_type": "quiz_set",
            "timestamp": later,
            "intent": {"type": "quiz_request", "topic": "光合作用"},
            "metadata": {}
        })
        
        # 验证：应该是同一个 session
        md_file = session_mgr.current_session_file
        content = md_file.read_text(encoding='utf-8')
        
        assert "Turn 1" in content
        assert "Turn 2" in content
        assert "什么是光合作用" in content
        assert "给我三道题" in content
    
    @pytest.mark.asyncio
    async def test_new_session_after_timeout(self, memory_manager, temp_storage):
        """测试 5 分钟超时后创建新 session"""
        user_id = "user_test_timeout"
        
        session_mgr = memory_manager.get_conversation_session_manager(user_id)
        
        now = datetime.now()
        
        # Session 1
        session_id_1 = await session_mgr.start_or_continue_session("什么是光合作用", timestamp=now)
        await session_mgr.append_turn({
            "user_query": "什么是光合作用",
            "agent_response": {"skill": "explain_skill", "content": {}},
            "response_type": "explanation",
            "timestamp": now,
            "intent": {},
            "metadata": {}
        })
        
        md_file_1 = session_mgr.current_session_file
        
        # 6 分钟后 - Session 2
        later = now + timedelta(minutes=6)
        session_id_2 = await session_mgr.start_or_continue_session("什么是牛顿第二定律", timestamp=later)
        await session_mgr.append_turn({
            "user_query": "什么是牛顿第二定律",
            "agent_response": {"skill": "explain_skill", "content": {}},
            "response_type": "explanation",
            "timestamp": later,
            "intent": {},
            "metadata": {}
        })
        
        md_file_2 = session_mgr.current_session_file
        
        # 验证：应该是两个不同的 session
        assert session_id_1 != session_id_2
        assert md_file_1 != md_file_2
        assert md_file_1.exists()
        assert md_file_2.exists()
        
        # 验证内容分离
        content_1 = md_file_1.read_text(encoding='utf-8')
        content_2 = md_file_2.read_text(encoding='utf-8')
        
        assert "光合作用" in content_1
        assert "光合作用" not in content_2
        assert "牛顿第二定律" in content_2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

