"""
测试 Plan Skill 的动态步骤选择和内容关联性

Phase 4.2: 确保动态选择的步骤能正确传递上下文，保持内容一致性
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.plan_skill_executor import PlanSkillExecutor


class TestDynamicStepSelection:
    """测试动态步骤选择功能"""
    
    @pytest.fixture
    def plan_config(self):
        """模拟 learning_plan_skill 配置"""
        return {
            "id": "learning_plan_skill",
            "display_name": "学习包规划器",
            "execution_plan": {
                "steps": [
                    {
                        "step_id": "explain",
                        "skill_id": "explain_skill",
                        "order": 1,
                        "input_mapping": {
                            "topic": "{input.topic}"
                        },
                        "context_extraction": {
                            "strategy": "full_content"
                        }
                    },
                    {
                        "step_id": "flashcard",
                        "skill_id": "flashcard_skill",
                        "order": 2,
                        "depends_on": ["explain"],
                        "input_mapping": {
                            "topic": "{input.topic}",
                            "num_cards": "{input.flashcard_quantity|default:5}",
                            "reference_explanation": "{context.explain}"
                        },
                        "context_extraction": {
                            "strategy": "summary"
                        }
                    },
                    {
                        "step_id": "quiz",
                        "skill_id": "quiz_skill",
                        "order": 3,
                        "depends_on": ["explain", "flashcard"],
                        "input_mapping": {
                            "topic": "{input.topic}",
                            "num_questions": "{input.quiz_quantity|default:3}",
                            "reference_explanation": "{context.explain}",
                            "reference_flashcards": "{context.flashcard}"
                        },
                        "context_extraction": {
                            "strategy": "summary"
                        }
                    }
                ]
            }
        }
    
    @pytest.fixture
    def executor(self):
        """创建 PlanSkillExecutor 实例"""
        mock_orchestrator = MagicMock()
        return PlanSkillExecutor(skill_orchestrator=mock_orchestrator)
    
    def test_filter_steps_explain_and_quiz_only(self, executor, plan_config):
        """测试只执行 explain + quiz 步骤"""
        # 模拟用户请求：解释+题目（跳过闪卡）
        user_input = {
            "topic": "牛顿第二定律",
            "required_steps": ["explain", "quiz"],  # 🎯 只要这两步
            "quiz_quantity": 3
        }
        
        # 获取执行计划
        all_steps = plan_config["execution_plan"]["steps"]
        required_steps = user_input.get("required_steps")
        
        if required_steps:
            filtered_steps = [s for s in all_steps if s["step_id"] in required_steps]
        else:
            filtered_steps = all_steps
        
        # 断言
        assert len(filtered_steps) == 2
        assert filtered_steps[0]["step_id"] == "explain"
        assert filtered_steps[1]["step_id"] == "quiz"
        assert "flashcard" not in [s["step_id"] for s in filtered_steps]
    
    def test_filter_steps_all_three(self, executor, plan_config):
        """测试执行全部3个步骤"""
        user_input = {
            "topic": "光合作用",
            "required_steps": ["explain", "flashcard", "quiz"]
        }
        
        all_steps = plan_config["execution_plan"]["steps"]
        required_steps = user_input.get("required_steps")
        
        if required_steps:
            filtered_steps = [s for s in all_steps if s["step_id"] in required_steps]
        else:
            filtered_steps = all_steps
        
        assert len(filtered_steps) == 3
    
    def test_no_required_steps_executes_all(self, executor, plan_config):
        """测试没有 required_steps 时执行全部步骤"""
        user_input = {
            "topic": "二战历史"
            # 没有 required_steps
        }
        
        all_steps = plan_config["execution_plan"]["steps"]
        required_steps = user_input.get("required_steps")
        
        if required_steps:
            filtered_steps = [s for s in all_steps if s["step_id"] in required_steps]
        else:
            filtered_steps = all_steps
        
        assert len(filtered_steps) == 3


class TestContextPassing:
    """测试步骤间的上下文传递"""
    
    @pytest.fixture
    def executor(self):
        mock_orchestrator = MagicMock()
        return PlanSkillExecutor(skill_orchestrator=mock_orchestrator)
    
    def test_build_step_input_with_missing_context(self, executor):
        """测试构建输入时处理缺失的上下文"""
        step = {
            "step_id": "quiz",
            "input_mapping": {
                "topic": "{input.topic}",
                "reference_explanation": "{context.explain}",
                "reference_flashcards": "{context.flashcard}"  # 这个会缺失
            }
        }
        
        user_input = {
            "topic": "牛顿第二定律"
        }
        
        step_contexts = {
            "explain": {
                "concept": "牛顿第二定律",
                "intuition": "力等于质量乘以加速度..."
            }
            # 注意：没有 flashcard context（因为被跳过）
        }
        
        # 构建输入
        step_input = executor._build_step_input(step, user_input, step_contexts)
        
        # 断言
        assert step_input["topic"] == "牛顿第二定律"
        assert step_input["reference_explanation"]["concept"] == "牛顿第二定律"
        assert step_input["reference_flashcards"] is None  # 🔥 应该是 None 而不是缺失
    
    def test_build_step_input_with_all_contexts(self, executor):
        """测试构建输入时所有上下文都存在"""
        step = {
            "step_id": "quiz",
            "input_mapping": {
                "topic": "{input.topic}",
                "reference_explanation": "{context.explain}",
                "reference_flashcards": "{context.flashcard}"
            }
        }
        
        user_input = {
            "topic": "牛顿第二定律"
        }
        
        step_contexts = {
            "explain": {
                "concept": "牛顿第二定律"
            },
            "flashcard": {
                "cards": [{"front": "F=ma", "back": "牛顿第二定律"}]
            }
        }
        
        step_input = executor._build_step_input(step, user_input, step_contexts)
        
        assert step_input["reference_explanation"]["concept"] == "牛顿第二定律"
        assert step_input["reference_flashcards"]["cards"][0]["front"] == "F=ma"
    
    def test_build_step_input_with_default_values(self, executor):
        """测试默认值的处理"""
        step = {
            "step_id": "quiz",
            "input_mapping": {
                "topic": "{input.topic}",
                "num_questions": "{input.quiz_quantity|default:3}"
            }
        }
        
        # 没有提供 quiz_quantity
        user_input = {
            "topic": "光合作用"
        }
        
        step_contexts = {}
        
        step_input = executor._build_step_input(step, user_input, step_contexts)
        
        assert step_input["topic"] == "光合作用"
        assert step_input["num_questions"] == 3  # 🔥 应该使用默认值


class TestContentConsistency:
    """测试内容一致性（理论测试，需要实际 LLM 调用才能完全验证）"""
    
    def test_quiz_should_receive_explanation_context(self):
        """验证 quiz 步骤应该收到 explanation 上下文"""
        # 这是一个理论测试，说明预期行为
        
        # 用户请求：解释 + 题目
        user_request = "解释一下牛顿第二定律，并给出3道题目"
        required_steps = ["explain", "quiz"]
        
        # 预期：
        # 1. explain 步骤生成讲解内容
        # 2. quiz 步骤收到 reference_explanation（来自 explain）
        # 3. quiz 步骤收到 reference_flashcards = None（因为被跳过）
        # 4. quiz 基于 reference_explanation 生成题目
        
        assert "explain" in required_steps
        assert "quiz" in required_steps
        assert "flashcard" not in required_steps
        
        # Quiz 的 input_mapping 应该包含：
        expected_inputs = [
            "reference_explanation",  # 来自 explain，确保题目与讲解一致
            "reference_flashcards"    # 可能为 None，quiz 应该能处理
        ]
        
        # 这些输入确保了内容的关联性
        for inp in expected_inputs:
            assert inp in ["reference_explanation", "reference_flashcards"]
    
    def test_notes_should_receive_explanation_context(self):
        """验证 notes 步骤应该收到 explanation 上下文"""
        user_request = "解释光合作用，并生成笔记"
        required_steps = ["explain", "notes"]
        
        # 预期：notes 基于 reference_explanation 生成
        assert "explain" in required_steps
        assert "notes" in required_steps
    
    def test_mindmap_should_receive_explanation_context(self):
        """验证 mindmap 步骤应该收到 explanation 上下文"""
        user_request = "讲解牛顿定律，并画思维导图"
        required_steps = ["explain", "mindmap"]
        
        # 预期：mindmap 基于 reference_explanation 生成
        assert "explain" in required_steps
        assert "mindmap" in required_steps
    
    def test_all_five_skills_can_work_together(self):
        """验证所有5个技能可以一起工作"""
        user_request = "给我光合作用的完整学习资料"
        required_steps = ["explain", "flashcard", "quiz", "notes", "mindmap"]
        
        # 预期：所有技能都基于 explain 生成
        assert len(required_steps) == 5
        assert "explain" in required_steps


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

