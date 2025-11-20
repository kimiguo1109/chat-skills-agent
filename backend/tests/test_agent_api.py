"""
Agent API 端点测试
"""
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class TestAgentHealthEndpoint:
    """测试 Agent Health 端点"""

    def test_agent_health_check(self):
        """测试健康检查端点"""
        response = client.get("/api/agent/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "components" in data
        assert data["components"]["memory_manager"] == "ok"
        assert data["components"]["gemini_client"] == "ok"
        print("✅ Agent health check passed")


class TestAgentInfoEndpoint:
    """测试 Agent Info 端点"""

    def test_agent_info(self):
        """测试系统信息端点"""
        response = client.get("/api/agent/info")
        
        assert response.status_code == 200
        data = response.json()
        assert "total_skills" in data
        assert data["total_skills"] == 7  # Phase 4: 包含所有 skill.md 技能
        assert "available_intents" in data
        assert "quiz" in data["available_intents"]
        assert "explain" in data["available_intents"]
        assert "skills" in data
        assert len(data["skills"]) == 2
        print("✅ Agent info endpoint passed")


class TestAgentChatRequest:
    """测试 Agent Chat 请求验证"""

    def test_empty_message_rejected(self):
        """测试空消息被拒绝"""
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": "test_user",
                "session_id": "test_session",
                "message": ""
            }
        )
        
        assert response.status_code == 422
        print("✅ Empty message rejected")

    def test_whitespace_only_message_rejected(self):
        """测试只有空格的消息被拒绝"""
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "   "
            }
        )
        
        assert response.status_code == 422
        print("✅ Whitespace-only message rejected")

    def test_missing_fields_rejected(self):
        """测试缺少字段的请求被拒绝"""
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": "test_user",
                "message": "给我几道题"
            }
        )
        
        assert response.status_code == 422
        print("✅ Missing fields rejected")


class TestAgentChatWithMockedOrchestrator:
    """测试 Agent Chat 与 Mock 的 Orchestrator"""

    @patch('app.api.agent.SkillOrchestrator.execute')
    @pytest.mark.asyncio
    async def test_quiz_request_success(self, mock_execute):
        """测试成功的 Quiz 请求"""
        # Mock Orchestrator 返回
        mock_execute.return_value = {
            "content": {
                "quiz_set": {
                    "title": "微积分练习",
                    "questions": [
                        {
                            "question_number": 1,
                            "question_text": "求极限：lim(x→0) (sin x) / x",
                            "question_type": "multiple_choice",
                            "options": [
                                {"key": "A", "text": "0"},
                                {"key": "B", "text": "1"},
                                {"key": "C", "text": "∞"},
                                {"key": "D", "text": "不存在"}
                            ],
                            "correct_answer": "B",
                            "explanation": "这是重要的极限公式。"
                        }
                    ]
                }
            },
            "content_type": "quiz_set",
            "intent": "quiz",
            "skill_id": "quiz_skill"
        }
        
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "给我几道微积分极限的练习题"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "test_user"
        assert data["session_id"] == "test_session"
        assert data["intent"] == "quiz"
        assert data["skill_id"] == "quiz_skill"
        assert data["content_type"] == "quiz_set"
        assert "response_content" in data
        assert "processing_time_ms" in data
        assert data["processing_time_ms"] >= 0
        print("✅ Quiz request processed successfully")

    @patch('app.api.agent.SkillOrchestrator.execute')
    @pytest.mark.asyncio
    async def test_explain_request_success(self, mock_execute):
        """测试成功的 Explain 请求"""
        # Mock Orchestrator 返回
        mock_execute.return_value = {
            "content": {
                "explanation_artifact": {
                    "concept": "光合作用",
                    "subject": "生物",
                    "summary": "光合作用是植物利用光能制造有机物的过程。",
                    "sections": [],
                    "related_concepts": [],
                    "difficulty_level": "medium"
                }
            },
            "content_type": "explanation",
            "intent": "explain",
            "skill_id": "explain_skill"
        }
        
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "什么是光合作用？"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "explain"
        assert data["skill_id"] == "explain_skill"
        assert data["content_type"] == "explanation"
        print("✅ Explain request processed successfully")


class TestAgentChatErrorHandling:
    """测试 Agent Chat 错误处理"""

    @patch('app.api.agent.SkillOrchestrator.execute')
    @pytest.mark.asyncio
    async def test_orchestrator_value_error(self, mock_execute):
        """测试 Orchestrator 抛出 ValueError"""
        mock_execute.side_effect = ValueError("意图不明确")
        
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "我很无聊"
            }
        )
        
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        print("✅ ValueError handled correctly")

    @patch('app.api.agent.SkillOrchestrator.execute')
    @pytest.mark.asyncio
    async def test_orchestrator_file_not_found(self, mock_execute):
        """测试 Orchestrator 抛出 FileNotFoundError"""
        mock_execute.side_effect = FileNotFoundError("Prompt 文件不存在")
        
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "给我几道题"
            }
        )
        
        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        print("✅ FileNotFoundError handled correctly")

    @patch('app.api.agent.SkillOrchestrator.execute')
    @pytest.mark.asyncio
    async def test_orchestrator_unexpected_error(self, mock_execute):
        """测试 Orchestrator 抛出未预期的异常"""
        mock_execute.side_effect = RuntimeError("意外错误")
        
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": "test_user",
                "session_id": "test_session",
                "message": "给我几道题"
            }
        )
        
        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        print("✅ Unexpected error handled correctly")


class TestAgentAPIDocumentation:
    """测试 Agent API 文档"""

    def test_openapi_includes_agent_endpoints(self):
        """测试 OpenAPI 文档包含 Agent 端点"""
        response = client.get("/openapi.json")
        
        assert response.status_code == 200
        openapi_schema = response.json()
        
        # 检查路径存在
        assert "/api/agent/chat" in openapi_schema["paths"]
        assert "/api/agent/health" in openapi_schema["paths"]
        assert "/api/agent/info" in openapi_schema["paths"]
        
        # 检查方法
        assert "post" in openapi_schema["paths"]["/api/agent/chat"]
        assert "get" in openapi_schema["paths"]["/api/agent/health"]
        assert "get" in openapi_schema["paths"]["/api/agent/info"]
        
        print("✅ OpenAPI documentation includes Agent endpoints")

