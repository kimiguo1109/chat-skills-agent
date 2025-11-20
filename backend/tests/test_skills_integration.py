"""
集成测试 - 验证 Skills 配置和组件集成
"""
import pytest
import os
from app.core import get_skill_registry
from app.core import SkillOrchestrator, MemoryManager
from app.services.gemini import GeminiClient


class TestSkillRegistryConfiguration:
    """测试 Skill 配置文件的正确性"""

    def test_quiz_skill_configuration(self):
        """验证 Quiz Skill 的配置完整性"""
        registry = get_skill_registry()
        skill = registry.get_skill("quiz_skill")
        
        assert skill is not None
        assert skill.display_name == "练习题生成"
        assert "quiz" in skill.intent_tags
        assert skill.prompt_file == "quiz_generation_skill.txt"
        assert skill.models["primary"] == "gemini-2.5-flash"
        
        # 验证 input_schema
        assert "properties" in skill.input_schema
        assert "topic" in skill.input_schema["properties"]
        assert "difficulty" in skill.input_schema["properties"]
        
        # 验证 output_schema
        assert "properties" in skill.output_schema
        
        print("✅ Quiz Skill 配置验证通过")

    def test_explain_skill_configuration(self):
        """验证 Explain Skill 的配置完整性"""
        registry = get_skill_registry()
        skill = registry.get_skill("explain_skill")
        
        assert skill is not None
        assert skill.display_name == "概念讲解"
        assert "explain" in skill.intent_tags
        assert skill.prompt_file == "concept_explain_skill.txt"
        assert skill.models["primary"] == "gemini-2.5-flash"
        
        # 验证 input_schema
        assert "properties" in skill.input_schema
        assert "concept_name" in skill.input_schema["properties"]
        assert "subject" in skill.input_schema["properties"]
        
        # 验证 output_schema
        assert "properties" in skill.output_schema
        
        print("✅ Explain Skill 配置验证通过")

    def test_all_skills_have_prompts(self):
        """验证所有 Skill 都有对应的 Prompt 文件"""
        registry = get_skill_registry()
        prompts_dir = "app/prompts"
        
        for skill in registry.list_all_skills():
            if skill.prompt_file:
                prompt_path = os.path.join(prompts_dir, skill.prompt_file)
                assert os.path.exists(prompt_path), f"Prompt 文件不存在: {skill.prompt_file}"
                
                # 验证文件不为空
                file_size = os.path.getsize(prompt_path)
                assert file_size > 1000, f"Prompt 文件太小 ({file_size} bytes): {skill.prompt_file}"
        
        print(f"✅ 所有 {len(registry.list_all_skills())} 个 Skills 都有对应的 Prompt 文件")

    def test_skills_have_correct_intent_mapping(self):
        """验证 Skills 的 intent 映射正确"""
        registry = get_skill_registry()
        
        # 测试 quiz intent
        quiz_skills = registry.get_skills_by_intent("quiz")
        assert len(quiz_skills) == 1
        assert quiz_skills[0].id == "quiz_skill"
        
        # 测试 explain intent
        explain_skills = registry.get_skills_by_intent("explain")
        assert len(explain_skills) == 1
        assert explain_skills[0].id == "explain_skill"
        
        print("✅ Skills intent 映射正确")

    def test_skills_have_valid_models(self):
        """验证 Skills 的模型配置有效"""
        registry = get_skill_registry()
        
        for skill in registry.list_all_skills():
            assert "primary" in skill.models
            assert skill.models["primary"]  # 不为空
            
            # 可选的 fallback 模型
            if "fallback" in skill.models:
                assert skill.models["fallback"]
        
        print("✅ Skills 模型配置有效")


class TestSkillOrchestratorIntegration:
    """测试 SkillOrchestrator 与其他组件的集成"""

    def test_orchestrator_initialization(self):
        """测试 Orchestrator 能够正常初始化"""
        memory_manager = MemoryManager(use_s3=False)
        skill_registry = get_skill_registry()
        gemini_client = GeminiClient()
        
        orchestrator = SkillOrchestrator(
            memory_manager=memory_manager,
            skill_registry=skill_registry,
            gemini_client=gemini_client
        )
        
        assert orchestrator.memory_manager is not None
        assert orchestrator.skill_registry is not None
        assert orchestrator.gemini_client is not None
        
        print("✅ Orchestrator 初始化成功")

    def test_orchestrator_can_access_skills(self):
        """测试 Orchestrator 能够访问 Skills"""
        orchestrator = SkillOrchestrator()
        
        all_skills = orchestrator.skill_registry.list_all_skills()
        assert len(all_skills) == 2
        
        quiz_skill = orchestrator.skill_registry.get_skill("quiz_skill")
        assert quiz_skill is not None
        
        explain_skill = orchestrator.skill_registry.get_skill("explain_skill")
        assert explain_skill is not None
        
        print("✅ Orchestrator 可以访问所有 Skills")


class TestPromptSystem:
    """测试 Prompt 系统完整性"""

    def test_all_required_prompts_exist(self):
        """验证所有必需的 Prompt 文件都存在"""
        prompts_dir = "app/prompts"
        
        # Phase 4: 清理后只保留实际使用的 prompt 文件
        required_prompts = [
            "intent_router.txt",
            "memory_summary.txt",
            "quiz_generation_skill.txt",
            "concept_explain_skill.txt",
            "flashcard_skill.txt",
            "notes_skill.txt",
            "mindmap_skill.txt",
            "learning_bundle_skill.txt"
        ]
        
        for prompt_file in required_prompts:
            prompt_path = os.path.join(prompts_dir, prompt_file)
            assert os.path.exists(prompt_path), f"必需的 Prompt 文件缺失: {prompt_file}"
            
            file_size = os.path.getsize(prompt_path)
            assert file_size > 100, f"Prompt 文件太小 ({file_size} bytes): {prompt_file}"
        
        print(f"✅ 所有 {len(required_prompts)} 个必需的 Prompt 文件都存在")

    def test_prompt_files_are_readable(self):
        """验证所有 Prompt 文件可以正常读取"""
        prompts_dir = "app/prompts"
        
        for filename in os.listdir(prompts_dir):
            if filename.endswith('.txt'):
                filepath = os.path.join(prompts_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    assert len(content) > 0, f"Prompt 文件为空: {filename}"
        
        print("✅ 所有 Prompt 文件可以正常读取")


class TestSkillConfigurationYAML:
    """测试 Skill YAML 配置文件"""

    def test_yaml_files_exist(self):
        """验证 YAML 配置文件存在"""
        config_dir = "skills_config"
        
        expected_files = [
            "quiz_skill.yaml",
            "explain_skill.yaml"
        ]
        
        for yaml_file in expected_files:
            yaml_path = os.path.join(config_dir, yaml_file)
            assert os.path.exists(yaml_path), f"YAML 配置文件缺失: {yaml_file}"
        
        print("✅ 所有 YAML 配置文件存在")

    def test_yaml_files_are_valid(self):
        """验证 YAML 文件格式正确"""
        import yaml
        config_dir = "skills_config"
        
        for filename in os.listdir(config_dir):
            if filename.endswith('.yaml') or filename.endswith('.yml'):
                filepath = os.path.join(config_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    
                    # 验证必需字段
                    assert 'id' in data, f"{filename}: 缺少 'id' 字段"
                    assert 'display_name' in data, f"{filename}: 缺少 'display_name' 字段"
                    assert 'intent_tags' in data, f"{filename}: 缺少 'intent_tags' 字段"
                    assert 'input_schema' in data, f"{filename}: 缺少 'input_schema' 字段"
                    assert 'output_schema' in data, f"{filename}: 缺少 'output_schema' 字段"
                    assert 'models' in data, f"{filename}: 缺少 'models' 字段"
        
        print("✅ 所有 YAML 文件格式正确")


class TestPhase1And2Integration:
    """验证 Phase 1 和 Phase 2 的集成"""

    @pytest.mark.asyncio
    async def test_memory_manager_integration(self):
        """测试 Memory Manager 集成"""
        memory_manager = MemoryManager(use_s3=False)
        
        # 创建用户画像
        profile = await memory_manager.get_user_profile("test_user")
        assert profile.user_id == "test_user"
        
        # 创建会话上下文
        session = await memory_manager.get_session_context("test_session")
        assert session.session_id == "test_session"
        
        # 生成记忆摘要
        summary = await memory_manager.generate_memory_summary("test_user", "test_session")
        assert summary.recent_behavior is not None
        assert isinstance(summary.recent_behavior, str)
        
        print("✅ Memory Manager 集成正常")

    def test_skill_registry_integration(self):
        """测试 Skill Registry 集成"""
        registry = get_skill_registry()
        
        # 测试技能检索
        all_skills = registry.list_all_skills()
        assert len(all_skills) > 0
        
        # 测试意图映射
        all_intents = registry.get_all_intents()
        assert len(all_intents) > 0
        assert "quiz" in all_intents
        assert "explain" in all_intents
        
        print("✅ Skill Registry 集成正常")
