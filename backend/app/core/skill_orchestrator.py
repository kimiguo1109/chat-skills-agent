"""
Skill Orchestrator - 技能编排器

负责：
1. 意图到技能映射
2. 技能选择策略
3. 输入参数构建  
4. 技能执行（调用 Gemini）
5. 输出封装
6. 记忆更新
"""
import json
import logging
import os
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..models.intent import IntentResult, MemorySummary
from ..models.memory import UserLearningProfile, SessionContext
from ..models.skill import SkillDefinition
from ..services.gemini import GeminiClient
from .skill_registry import SkillRegistry, get_skill_registry
from .memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class SkillOrchestrator:
    """技能编排器 - 调度核心"""
    
    def __init__(
        self,
        skill_registry: Optional[SkillRegistry] = None,
        gemini_client: Optional[GeminiClient] = None,
        memory_manager: Optional[MemoryManager] = None
    ):
        """
        初始化 Skill Orchestrator
        
        Args:
            skill_registry: Skill Registry 实例
            gemini_client: Gemini Client 实例
            memory_manager: Memory Manager 实例
        """
        self.skill_registry = skill_registry or get_skill_registry()
        self.gemini_client = gemini_client or GeminiClient()
        self.memory_manager = memory_manager or MemoryManager()
        
        # Prompt 文件目录
        self.prompts_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts"
        )
        
        logger.info("✅ SkillOrchestrator initialized")
    
    async def execute(
        self,
        intent_result: IntentResult,
        user_id: str,
        session_id: str,
        additional_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行完整的编排流程
        
        Args:
            intent_result: 意图识别结果
            user_id: 用户 ID
            session_id: 会话 ID
            additional_params: 额外参数
        
        Returns:
            技能执行结果
        """
        logger.info(f"🎯 Orchestrating: intent={intent_result.intent}, topic={intent_result.topic}")
        
        # Step 1: 选择技能
        skill = self._select_skill(intent_result)
        if not skill:
            return self._create_error_response(
                "no_skill_found",
                f"未找到匹配意图 '{intent_result.intent}' 的技能"
            )
        
        logger.info(f"📦 Selected skill: {skill.id} ({skill.display_name})")
        
        # Step 2: 获取上下文
        context = await self._build_context(skill, user_id, session_id)
        
        # Step 3: 构建输入参数
        params = self._build_input_params(skill, intent_result, context, additional_params)
        
        # Step 3.5: 特别处理 - 提取 quantity 参数（如果用户没指定，使用默认值）
        if hasattr(intent_result, 'parameters') and intent_result.parameters:
            quantity = intent_result.parameters.get('quantity', None)
            
            # 如果没有指定数量，使用默认值
            if quantity is None:
                if skill.id == 'quiz_skill':
                    quantity = 5  # Quiz 默认 5 道题
                elif skill.id == 'flashcard_skill':
                    quantity = 5  # Flashcard 默认 5 张卡
            
            # 根据不同的 skill 设置不同的参数名
            if skill.id == 'quiz_skill':
                params['num_questions'] = quantity
            elif skill.id == 'flashcard_skill':
                params['num_cards'] = quantity
            
            logger.info(f"📊 Extracted quantity: {quantity} for {skill.id}")
        
        # Step 4: 执行技能
        try:
            result_json = await self._execute_skill(skill, params, context)
            # result_json 是 JSON 字符串，需要解析为字典
            result = json.loads(result_json) if isinstance(result_json, str) else result_json
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"❌ Failed to parse skill result JSON: {e}")
            return self._create_error_response("json_parse_error", f"Invalid JSON response: {str(e)}")
        except Exception as e:
            logger.error(f"❌ Skill execution failed: {e}")
            return self._create_error_response("execution_error", str(e))
        
        # Step 5: 封装输出（传入 intent_result）
        output = self._wrap_output(skill, result, intent_result)
        
        # Step 6: 更新记忆（异步，不阻塞）
        await self._update_memory(user_id, session_id, intent_result, result)
        
        logger.info(f"✅ Orchestration complete for {skill.id}")
        return output
    
    def _select_skill(self, intent_result: IntentResult) -> Optional[SkillDefinition]:
        """
        根据意图选择合适的技能
        
        Args:
            intent_result: 意图识别结果
        
        Returns:
            选中的 Skill 定义，或 None
        """
        # 获取匹配的 skills
        intent = intent_result.intent
        if isinstance(intent, list):
            intent = intent[0]  # 取第一个意图
        
        matching_skills = self.skill_registry.get_skills_by_intent(intent)
        
        if not matching_skills:
            logger.warning(f"⚠️  No skill found for intent: {intent}")
            return None
        
        # 简单策略：取第一个
        # TODO: 可以实现更复杂的选择策略（基于上下文、用户偏好等）
        return matching_skills[0]
    
    async def _build_context(
        self,
        skill: SkillDefinition,
        user_id: str,
        session_id: str
    ) -> Dict[str, Any]:
        """
        构建技能执行所需的上下文
        
        Args:
            skill: Skill 定义
            user_id: 用户 ID
            session_id: 会话 ID
        
        Returns:
            上下文字典
        """
        context = {}
        
        # 根据 skill 的 context 配置获取必要的上下文
        if skill.context.get("need_user_memory", False):
            user_profile = await self.memory_manager.get_user_profile(user_id)
            session_context = await self.memory_manager.get_session_context(session_id)
            memory_summary = await self.memory_manager.generate_memory_summary(user_id, session_id)
            
            context["user_profile"] = user_profile.model_dump()
            context["session_context"] = session_context.model_dump()
            context["memory_summary"] = memory_summary.recent_behavior
        
        # TODO: 如果需要 content_store，从知识库检索相关内容
        if skill.context.get("need_content_store", False):
            context["content_context"] = []  # 占位符
        
        return context
    
    def _build_input_params(
        self,
        skill: SkillDefinition,
        intent_result: IntentResult,
        context: Dict[str, Any],
        additional_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        构建技能的输入参数
        
        Args:
            skill: Skill 定义
            intent_result: 意图结果
            context: 上下文
            additional_params: 额外参数
        
        Returns:
            输入参数字典
        """
        params = {}
        
        # 从 intent_result 提取基本参数
        if intent_result.topic:
            params["topic"] = intent_result.topic
        
        # 添加 memory_summary
        if "memory_summary" in context:
            params["memory_summary"] = context["memory_summary"]
        
        # 添加用户提供的额外参数
        if additional_params:
            params.update(additional_params)
        
        return params
    
    async def _execute_skill(
        self,
        skill: SkillDefinition,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行技能（调用 Gemini API）
        
        Args:
            skill: Skill 定义
            params: 输入参数
            context: 上下文
        
        Returns:
            技能执行结果
        """
        # 加载 prompt 模板
        prompt_content = self._load_prompt(skill)
        
        # 构建完整 prompt
        full_prompt = self._format_prompt(prompt_content, params, context)
        
        # 调用 Gemini
        model = skill.models.get("primary", "gemini-2.0-flash-exp")
        
        logger.debug(f"🤖 Calling Gemini model: {model}")
        result = await self.gemini_client.generate_json(full_prompt, model=model)
        
        return result
    
    def _load_prompt(self, skill: SkillDefinition) -> str:
        """
        加载 Skill 的 Prompt 模板
        
        Args:
            skill: Skill 定义
        
        Returns:
            Prompt 内容
        """
        if not skill.prompt_file:
            raise ValueError(f"Skill {skill.id} has no prompt_file configured")
        
        prompt_path = os.path.join(self.prompts_dir, skill.prompt_file)
        
        if not os.path.exists(prompt_path):
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _format_prompt(
        self,
        prompt_template: str,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> str:
        """
        格式化 Prompt（将参数填入模板）
        
        Args:
            prompt_template: Prompt 模板
            params: 输入参数
            context: 上下文
        
        Returns:
            格式化后的 prompt
        """
        # 简单实现：在 prompt 后附加参数 JSON
        import json
        
        params_json = json.dumps(params, ensure_ascii=False, indent=2)
        
        formatted = f"""{prompt_template}

## Input Parameters

```json
{params_json}
```

Please respond with valid JSON according to the output schema defined above.
"""
        return formatted
    
    def _wrap_output(
        self,
        skill: SkillDefinition,
        result: Dict[str, Any],
        intent_result: IntentResult = None
    ) -> Dict[str, Any]:
        """
        封装输出结果（统一响应格式）
        
        Args:
            skill: Skill 定义
            result: 原始结果（Gemini 返回的 JSON）
            intent_result: 意图识别结果
        
        Returns:
            封装后的结果，包含 content、content_type、intent、skill_id
        """
        # 特殊处理：如果 result 是列表（learning_bundle 可能返回列表），包装成字典
        if isinstance(result, list):
            logger.warning(f"⚠️  Skill {skill.id} returned a list instead of dict, wrapping it")
            result = {
                "bundle_id": f"bundle_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "components": result,
                "subject": intent_result.topic.split("-")[0] if intent_result and intent_result.topic else "通用",
                "topic": intent_result.topic if intent_result and intent_result.topic else "学习资料"
            }
        
        # 检测内容类型
        content_type = "unknown"
        if "quiz_set_id" in result or "questions" in result:
            content_type = "quiz_set"
        elif "concept" in result or "explanation" in result:
            content_type = "explanation"
        elif "flashcard_set_id" in result or "cards" in result:
            content_type = "flashcard_set"
        elif "bundle_id" in result or "components" in result:
            content_type = "learning_bundle"
        elif "mindmap_id" in result or "root" in result:
            content_type = "mindmap"
        elif "error" in result:
            content_type = "error"
        
        # 提取意图
        intent = "unknown"
        if intent_result:
            if isinstance(intent_result.intent, list):
                intent = intent_result.intent[0] if intent_result.intent else "unknown"
            else:
                intent = intent_result.intent
        
        return {
            "content": result,          # 实际内容（Gemini 返回的 JSON）
            "content_type": content_type,  # quiz_set, explanation, error 等
            "intent": intent,           # 原始意图
            "skill_id": skill.id,       # 使用的技能 ID
            "skill_name": skill.display_name,
            "success": True
        }
    
    async def _update_memory(
        self,
        user_id: str,
        session_id: str,
        intent_result: IntentResult,
        skill_result: Dict[str, Any]
    ):
        """
        更新用户记忆（异步，不阻塞主流程）
        
        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            intent_result: 意图结果
            skill_result: 技能结果
        """
        try:
            # 更新会话上下文
            session_context = await self.memory_manager.get_session_context(session_id)
            
            # 更新当前主题
            if intent_result.topic:
                session_context.current_topic = intent_result.topic
            
            # 添加意图到历史
            intent = intent_result.intent
            if isinstance(intent, list):
                intent = intent[0]
            
            if not session_context.recent_intents:
                session_context.recent_intents = []
            session_context.recent_intents.append(intent)
            
            # 保持最近10个
            if len(session_context.recent_intents) > 10:
                session_context.recent_intents = session_context.recent_intents[-10:]
            
            await self.memory_manager.update_session_context(session_id, session_context)
            
            logger.debug(f"📝 Memory updated for user {user_id}, session {session_id}")
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to update memory: {e}")
    
    def _create_error_response(self, error_type: str, message: str) -> Dict[str, Any]:
        """
        创建错误响应
        
        Args:
            error_type: 错误类型
            message: 错误消息
        
        Returns:
            错误响应字典
        """
        return {
            "success": False,
            "error": error_type,
            "message": message
        }

