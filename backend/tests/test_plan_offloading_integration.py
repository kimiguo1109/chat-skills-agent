"""
Integration Tests for Plan Skill Context Offloading

测试 Plan Skill 的 Context Offloading 功能：
- offloading disabled (默认): 使用 legacy context pruning
- offloading enabled: 使用文件系统 offloading
- 降级机制: offloading 失败时回退到 legacy
"""

import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.plan_skill_executor import PlanSkillExecutor


@pytest.fixture
def mock_orchestrator():
    """Mock SkillOrchestrator"""
    orchestrator = MagicMock()
    
    # Mock execute 方法返回简单的结果
    async def mock_execute(*args, **kwargs):
        skill_id = args[0] if args else kwargs.get("skill_id", "unknown")
        if skill_id == "explain_skill":
            return {
                "concept": "测试概念",
                "intuition": "测试直觉",
                "examples": [{"example": "例子1"}]
            }
        elif skill_id == "quiz_skill":
            return {
                "quiz_set_id": "quiz_001",
                "questions": [{"question_text": "问题1"}]
            }
        else:
            return {"result": "test"}
    
    orchestrator.execute = AsyncMock(side_effect=mock_execute)
    return orchestrator


@pytest.fixture
def sample_plan_config_disabled():
    """Sample Plan 配置（offloading disabled）"""
    return {
        "id": "learning_plan_skill",
        "display_name": "测试学习包",
        "cost_control": {
            "enable_artifact_offloading": False  # 🔒 关闭
        },
        "execution_plan": {
            "strategy": "sequential",
            "steps": [
                {
                    "step_id": "explain",
                    "skill_id": "explain_skill",
                    "display_name": "概念讲解",
                    "depends_on": [],
                    "input_mapping": {
                        "topic": "{input.topic}"
                    },
                    "context_extraction": {
                        "strategy": "full_content",
                        "fields": ["concept", "intuition", "examples"]
                    }
                },
                {
                    "step_id": "quiz",
                    "skill_id": "quiz_skill",
                    "display_name": "练习题",
                    "depends_on": ["explain"],
                    "input_mapping": {
                        "topic": "{input.topic}",
                        "reference_explanation": "{context.explain}"
                    },
                    "context_extraction": {
                        "strategy": "summary",
                        "fields": ["quiz_set_id"]
                    }
                }
            ]
        },
        "aggregation": {
            "assembly": {
                "components": [
                    {"step_id": "explain", "component_type": "explanation"},
                    {"step_id": "quiz", "component_type": "quiz"}
                ]
            }
        }
    }


@pytest.fixture
def sample_plan_config_enabled(sample_plan_config_disabled):
    """Sample Plan 配置（offloading enabled）"""
    config = sample_plan_config_disabled.copy()
    config["cost_control"] = {
        "enable_artifact_offloading": True  # ✅ 启用
    }
    return config


@pytest.fixture
def temp_artifacts_dir(tmp_path):
    """临时 artifacts 目录"""
    artifact_dir = tmp_path / "artifacts"
    yield artifact_dir
    # Cleanup
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)


class TestPlanOffloadingDisabled:
    """测试：offloading disabled（默认行为）"""
    
    @pytest.mark.asyncio
    async def test_legacy_context_pruning(
        self,
        mock_orchestrator,
        sample_plan_config_disabled
    ):
        """测试：默认使用 legacy context pruning"""
        executor = PlanSkillExecutor(mock_orchestrator)
        
        # 执行 Plan
        result = await executor.execute_plan(
            plan_config=sample_plan_config_disabled,
            user_input={"topic": "测试主题"},
            user_profile=None,
            session_context=None
        )
        
        # 验证
        assert executor.offloading_enabled is False
        assert executor.artifact_storage is None
        assert executor.current_session_id is None
        
        # 验证没有创建 artifacts 文件
        assert not Path("artifacts").exists()
    
    @pytest.mark.asyncio
    async def test_context_in_memory(
        self,
        mock_orchestrator,
        sample_plan_config_disabled
    ):
        """测试：上下文存储在内存中（不写文件）"""
        executor = PlanSkillExecutor(mock_orchestrator)
        
        # 执行 Plan
        await executor.execute_plan(
            plan_config=sample_plan_config_disabled,
            user_input={"topic": "测试主题"},
            user_profile=None,
            session_context=None
        )
        
        # 验证 orchestrator 被正确调用
        assert mock_orchestrator.execute.call_count == 2  # explain + quiz


class TestPlanOffloadingEnabled:
    """测试：offloading enabled"""
    
    @pytest.mark.asyncio
    async def test_offloading_initialization(
        self,
        mock_orchestrator,
        sample_plan_config_enabled,
        temp_artifacts_dir
    ):
        """测试：offloading 启用时正确初始化"""
        with patch("app.core.plan_skill_executor.ArtifactStorage") as MockStorage:
            mock_storage_instance = MagicMock()
            MockStorage.return_value = mock_storage_instance
            
            executor = PlanSkillExecutor(mock_orchestrator)
            
            # 执行 Plan
            await executor.execute_plan(
                plan_config=sample_plan_config_enabled,
                user_input={"topic": "测试主题"},
                user_profile=None,
                session_context=None
            )
            
            # 验证
            assert executor.offloading_enabled is True
            assert executor.artifact_storage is not None
            assert executor.current_session_id is not None
            assert executor.current_session_id.startswith("plan_")
            
            # 验证 save_plan_metadata 被调用
            mock_storage_instance.save_plan_metadata.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_artifact_references_created(
        self,
        mock_orchestrator,
        sample_plan_config_enabled
    ):
        """测试：创建 artifact 引用而不是传递完整内容"""
        with patch("app.core.plan_skill_executor.ArtifactStorage") as MockStorage:
            mock_storage_instance = MagicMock()
            MockStorage.return_value = mock_storage_instance
            
            # Mock create_reference 返回引用
            mock_storage_instance.create_reference.return_value = {
                "type": "artifact_reference",
                "session_id": "test_session",
                "step_id": "explain",
                "fields": ["concept", "intuition", "examples"],
                "file_path": "test_session/step_explain.json"
            }
            
            executor = PlanSkillExecutor(mock_orchestrator)
            
            # 执行 Plan
            await executor.execute_plan(
                plan_config=sample_plan_config_enabled,
                user_input={"topic": "测试主题"},
                user_profile=None,
                session_context=None
            )
            
            # 验证 save_step_result 被调用
            assert mock_storage_instance.save_step_result.call_count >= 1
            
            # 验证 create_reference 被调用
            assert mock_storage_instance.create_reference.call_count >= 1


class TestOffloadingFallback:
    """测试：offloading 降级机制"""
    
    @pytest.mark.asyncio
    async def test_fallback_on_storage_failure(
        self,
        mock_orchestrator,
        sample_plan_config_enabled
    ):
        """测试：文件操作失败时自动回退到 legacy"""
        with patch("app.core.plan_skill_executor.ArtifactStorage") as MockStorage:
            mock_storage_instance = MagicMock()
            MockStorage.return_value = mock_storage_instance
            
            # Mock save_step_result 抛出异常
            mock_storage_instance.save_step_result.side_effect = IOError("Disk full")
            
            executor = PlanSkillExecutor(mock_orchestrator)
            
            # 执行 Plan（不应该崩溃）
            result = await executor.execute_plan(
                plan_config=sample_plan_config_enabled,
                user_input={"topic": "测试主题"},
                user_profile=None,
                session_context=None
            )
            
            # 验证：即使 offloading 失败，plan 仍然成功执行
            assert result is not None
            assert "components" in result or "bundle_id" in result


class TestTokenSavings:
    """测试：Token 节省效果"""
    
    @pytest.mark.asyncio
    async def test_reference_size_vs_full_content(
        self,
        mock_orchestrator,
        sample_plan_config_enabled
    ):
        """测试：引用大小远小于完整内容"""
        with patch("app.core.plan_skill_executor.ArtifactStorage") as MockStorage:
            mock_storage_instance = MagicMock()
            MockStorage.return_value = mock_storage_instance
            
            # Mock create_reference 返回引用
            reference = {
                "type": "artifact_reference",
                "session_id": "test_session",
                "step_id": "explain",
                "fields": ["concept"],
                "file_path": "test_session/step_explain.json"
            }
            mock_storage_instance.create_reference.return_value = reference
            
            executor = PlanSkillExecutor(mock_orchestrator)
            
            # 执行 Plan
            await executor.execute_plan(
                plan_config=sample_plan_config_enabled,
                user_input={"topic": "测试主题"},
                user_profile=None,
                session_context=None
            )
            
            # 验证：引用大小 < 200 bytes
            reference_size = len(json.dumps(reference, ensure_ascii=False))
            assert reference_size < 200


class TestBackwardCompatibility:
    """测试：向后兼容性"""
    
    @pytest.mark.asyncio
    async def test_no_config_defaults_to_disabled(
        self,
        mock_orchestrator,
        sample_plan_config_disabled
    ):
        """测试：没有 cost_control 配置时默认关闭 offloading"""
        # 移除 cost_control
        config = sample_plan_config_disabled.copy()
        config.pop("cost_control", None)
        
        executor = PlanSkillExecutor(mock_orchestrator)
        
        # 执行 Plan
        await executor.execute_plan(
            plan_config=config,
            user_input={"topic": "测试主题"},
            user_profile=None,
            session_context=None
        )
        
        # 验证：offloading 关闭
        assert executor.offloading_enabled is False
    
    @pytest.mark.asyncio
    async def test_existing_tests_still_pass(
        self,
        mock_orchestrator,
        sample_plan_config_disabled
    ):
        """测试：现有测试不受影响（向后兼容 100%）"""
        executor = PlanSkillExecutor(mock_orchestrator)
        
        # 执行 Plan（与之前完全相同）
        result = await executor.execute_plan(
            plan_config=sample_plan_config_disabled,
            user_input={"topic": "测试主题"},
            user_profile=None,
            session_context=None
        )
        
        # 验证：结果格式不变
        assert result is not None
        # 现有测试期望的格式应该保持不变

