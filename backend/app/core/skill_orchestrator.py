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
    
    async def execute_stream(
        self,
        intent_result: IntentResult,
        user_id: str,
        session_id: str,
        additional_params: Optional[Dict[str, Any]] = None
    ):
        """
        🆕 流式执行技能（实时展示思考过程和生成内容）
        
        Args:
            intent_result: 意图识别结果
            user_id: 用户 ID
            session_id: 会话 ID
            additional_params: 额外参数
        
        Yields:
            Dict: 流式事件 {"type": "status|thinking|content|done", ...}
        """
        try:
            logger.info(f"🌊 Stream orchestrating: intent={intent_result.intent}, topic={intent_result.topic}")
            
            # Step 1: 选择技能
            skill = self._select_skill(intent_result)  # 🔧 修复：传递IntentResult对象
            if not skill:
                yield {
                    "type": "error",
                    "message": f"No skill found for intent: {intent_result.intent}"
                }
                return
            
            yield {
                "type": "status",
                "message": f"使用 {skill.display_name}"
            }
            
            # Step 2: 构建上下文
            context = await self._build_context(skill, user_id, session_id)
            
            # Step 3: 构建输入参数
            params = self._build_input_params(
                skill, intent_result, context, additional_params
            )
            
            # 检查是否需要澄清
            if not params.get("topic"):
                yield {
                    "type": "clarification_needed",
                    "message": "需要明确学习主题"
                }
                return
            
            # Step 4: 加载 prompt
            prompt_content = self._load_prompt(skill)
            prompt = self._format_prompt(prompt_content, params, context)
            
            # Step 5: 流式调用 LLM
            yield {
                "type": "status", 
                "message": "正在生成内容..."
            }
            
            thinking_accumulated = []
            content_accumulated = []
            
            async for chunk in self.gemini_client.generate_stream(
                prompt=prompt,
                model=skill.models.get("primary", "gemini-2.5-flash"),
                thinking_budget=skill.thinking_budget or 1024
            ):
                # 累积数据
                if chunk["type"] == "thinking":
                    thinking_accumulated.append(chunk.get("text", ""))
                elif chunk["type"] == "content":
                    content_accumulated.append(chunk.get("text", ""))
                
                # 转发给前端
                yield chunk
            
            # Step 6: 解析最终结果
            full_thinking = "".join(thinking_accumulated)
            full_content = "".join(content_accumulated)
            
            # 🔧 提取JSON（去除markdown代码块）
            json_str = full_content
            if "```json" in json_str:
                # JSON被包裹在```json ...```中
                try:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                    logger.info(f"✂️  Extracted JSON from markdown code block")
                except:
                    logger.warning(f"⚠️  Failed to extract JSON from markdown")
            elif "```" in json_str:
                # JSON被包裹在``` ...```中
                try:
                    json_str = json_str.split("```")[1].split("```")[0].strip()
                    logger.info(f"✂️  Extracted JSON from code block")
                except:
                    pass
            
            # 尝试解析 JSON
            try:
                parsed_content = json.loads(json_str)
                logger.info(f"✅ JSON parsed successfully")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse JSON: {e}")
                logger.error(f"Content preview: {json_str[:200]}")
                yield {
                    "type": "error",
                    "message": "生成内容格式错误"
                }
                return
            
            # Step 7: 更新 memory
            # 更新 current_topic
            if params.get("topic"):
                await self.memory_manager.update_session_context(
                    session_id=session_id,
                    updates={"current_topic": params["topic"]}
                )
            
            # 添加到 artifact history
            # 🔧 修复：output_schema可能为None
            artifact_type = "unknown"
            if skill.output_schema and isinstance(skill.output_schema, dict):
                artifact_type = skill.output_schema.get("artifact_type", "unknown")
            
            await self.memory_manager.add_artifact(
                session_id=session_id,
                artifact_type=artifact_type,
                content=parsed_content
            )
            
            # 完成
            yield {
                "type": "done",
                "thinking": full_thinking,
                "content": parsed_content,
                "content_type": artifact_type
            }
            
            logger.info(f"✅ Stream orchestration complete for {skill.id}")
            
        except Exception as e:
            logger.error(f"❌ Stream orchestration error: {e}")
            yield {
                "type": "error",
                "message": str(e)
            }
    
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
        
        # ============= Phase 0: 检查是否需要澄清或引导（优先级最高）=============
        
        # 🎯 澄清机制：对所有需要明确主题的skills，提供引导或澄清
        needs_clarification_intents = [
            "notes", "flashcard_request", "quiz_request", 
            "explain_request", "mindmap", "learning_bundle"
        ]
        
        if intent_result.intent in needs_clarification_intents:
            # 获取 session context
            session_context = await self.memory_manager.get_session_context(session_id)
            artifact_history = []
            
            if session_context:
                artifact_history = session_context.artifact_history or []
            
            # 🎯 关键：只有当topic无效时才需要澄清/引导
            #    如果用户明确说了topic（如"微积分"），直接执行，不需要引导
            topic_is_valid = intent_result.topic and len(intent_result.topic) >= 3
            
            # 🆕 首次访问 + 无明确topic：提供onboarding引导（0 token消耗）
            if len(artifact_history) == 0 and not topic_is_valid:
                logger.info(f"👋 First-time user detected, showing onboarding (0 tokens)")
                
                return {
                    "content_type": "onboarding",
                    "intent": intent_result.intent,
                    "response_content": {
                        "welcome": "👋 欢迎使用 StudyX Agent！",
                        "message": "我注意到您还没有开始学习任何主题。",
                        "suggestions": [
                            {
                                "category": "物理",
                                "topics": ["牛顿定律", "光学", "电磁学", "量子力学"],
                                "icon": "⚛️"
                            },
                            {
                                "category": "数学",
                                "topics": ["微积分", "线性代数", "概率论", "统计学"],
                                "icon": "📐"
                            },
                            {
                                "category": "历史",
                                "topics": ["二战历史", "文艺复兴", "工业革命", "古代文明"],
                                "icon": "📜"
                            },
                            {
                                "category": "生物",
                                "topics": ["光合作用", "细胞结构", "遗传学", "进化论"],
                                "icon": "🧬"
                            },
                            {
                                "category": "计算机",
                                "topics": ["数据结构", "算法", "机器学习", "网络"],
                                "icon": "💻"
                            }
                        ],
                        "call_to_action": "请先告诉我您想学习什么主题，例如：「讲讲牛顿第二定律」或「什么是光合作用」"
                    }
                }
            
            # 多主题澄清：只有当topic无效且有多个主题时才触发
            if not topic_is_valid and len(artifact_history) > 1:
                # 提取所有已学习的主题
                learned_topics = []
                seen_topics = set()
                for artifact in reversed(artifact_history):  # 最新的在前
                    topic_val = artifact.topic if hasattr(artifact, 'topic') else artifact.get("topic")
                    artifact_type = artifact.artifact_type if hasattr(artifact, 'artifact_type') else artifact.get("artifact_type", "unknown")
                    
                    if topic_val and topic_val not in seen_topics:
                        seen_topics.add(topic_val)
                        learned_topics.append({
                            "topic": topic_val,
                            "type": artifact_type
                        })
                
                if len(learned_topics) >= 1:
                    logger.info(f"💬 Clarification needed: {len(learned_topics)} topic(s) available, asking user (0 tokens)")
                    
                    # 根据不同intent生成不同的问题
                    intent_questions = {
                        "notes": ("做笔记", "做{topic}的笔记"),
                        "quiz_request": ("生成题目", "生成{topic}的题目"),
                        "flashcard_request": ("生成闪卡", "生成{topic}的闪卡"),
                        "explain_request": ("讲解", "讲解{topic}"),
                        "mindmap": ("生成思维导图", "生成{topic}的思维导图"),
                        "learning_bundle": ("获取学习包", "获取{topic}的学习资料")
                    }
                    
                    action_text, example_text = intent_questions.get(
                        intent_result.intent, 
                        ("学习", "学习{topic}")
                    )
                    
                    # 返回澄清响应（0 token消耗）
                    return {
                        "content_type": "clarification",
                        "intent": intent_result.intent,
                        "response_content": {
                            "question": f"您想对哪个主题{action_text}呢？",
                            "learned_topics": learned_topics[:5],  # 最多显示5个
                            "suggestion": f"请告诉我您想选择的主题，例如：「{example_text.format(topic=learned_topics[0]['topic'])}」"
                        }
                    }
        
        # ============= Phase 3: 处理 ambiguous/contextual 意图 =============
        
        # Step 0.1: 处理模糊意图 (需要偏好推断)
        if intent_result.intent == "ambiguous":
            logger.info("🔄 Processing ambiguous intent - applying user preference...")
            
            # 获取用户偏好（不调用 LLM，直接查询数据库/内存）
            user_profile = await self.memory_manager.get_user_profile(user_id)
            
            # 从用户偏好中提取 top preference
            top_preference = "explain"  # 默认
            if user_profile and user_profile.preferences:
                # preferences 是 dict: {"preferred_artifact": "quiz", ...}
                preferred_artifact = user_profile.preferences.get("preferred_artifact")
                if preferred_artifact:
                    top_preference = preferred_artifact
            
            # 更新 intent 为用户偏好的技能
            intent_result.intent = top_preference
            logger.info(f"✅ Ambiguous intent resolved to: {top_preference} (based on user preference)")
            
            # 🆕 提取当前学习主题（如果用户没有指定topic，使用当前主题）
            if not intent_result.topic:
                session_context = await self.memory_manager.get_session_context(session_id)
                if session_context and session_context.current_topic:
                    intent_result.topic = session_context.current_topic
                    logger.info(f"✅ Ambiguous intent: using current topic: {session_context.current_topic}")
        
        # Step 0.2: 处理上下文引用 (需要从 last_artifact 提取信息)
        if intent_result.intent == "contextual":
            logger.info("🔄 Processing contextual intent - extracting from last artifact...")
            
            # 获取 session context（不调用 LLM，直接读取内存）
            session_context = await self.memory_manager.get_session_context(session_id)
            
            # 从 last_artifact 提取 topic
            if session_context and session_context.last_artifact:
                # last_artifact 格式: "Type: explanation | Topic: 牛顿第二定律"
                last_artifact = session_context.last_artifact
                
                # 🆕 优先从 last_artifact 字符串提取，如果失败则从 current_topic 提取
                if " | Topic: " in last_artifact:
                    topic = last_artifact.split(" | Topic: ")[1].strip()
                    intent_result.topic = topic
                    logger.info(f"✅ Extracted topic from last artifact: {topic}")
                elif session_context.current_topic:
                    # Fallback: 如果 last_artifact 没有 topic 信息，使用 current_topic
                    intent_result.topic = session_context.current_topic
                    logger.info(f"✅ Using current_topic as fallback: {session_context.current_topic}")
                else:
                    logger.warning("⚠️ No topic found in last artifact or current_topic")
                
                # 根据 last artifact 类型推断意图
                # 如果上一轮是 explain，这一轮可能是 quiz 或 flashcard
                user_profile = await self.memory_manager.get_user_profile(user_id)
                top_preference = "quiz"  # 默认
                if user_profile and user_profile.preferences:
                    preferred_artifact = user_profile.preferences.get("preferred_artifact")
                    if preferred_artifact:
                        top_preference = preferred_artifact
                
                intent_result.intent = top_preference
                logger.info(f"✅ Contextual intent resolved to: {top_preference}")
                
                # 标记需要使用 last_artifact 内容
                if not intent_result.parameters:
                    intent_result.parameters = {}
                intent_result.parameters['use_last_artifact'] = True
            else:
                logger.warning("⚠️ No last artifact found for contextual intent, falling back to 'other'")
                intent_result.intent = "other"
        
        # ============= End Phase 3 Processing =============
        
        # Step 1: 选择技能
        skill = self._select_skill(intent_result)
        if not skill:
            return self._create_error_response(
                "no_skill_found",
                f"未找到匹配意图 '{intent_result.intent}' 的技能"
            )
        
        logger.info(f"📦 Selected skill: {skill.id} ({skill.display_name})")
        
        # 🆕 Step 1.5: 检查是否为 Plan Skill
        if skill.skill_type == "plan":
            logger.info(f"🎯 Detected Plan Skill: {skill.id}")
            return await self._execute_plan_skill(
                skill=skill,
                intent_result=intent_result,
                user_id=user_id,
                session_id=session_id,
                additional_params=additional_params
            )
        
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
            response = await self._execute_skill(skill, params, context)
            # 🆕 response 是字典: {"content": str, "thinking": str, "usage": dict}
            
            # 提取内容
            result_json = response.get("content", response) if isinstance(response, dict) else response
            thinking = response.get("thinking") if isinstance(response, dict) else None
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            
            # 解析 JSON
            result = json.loads(result_json) if isinstance(result_json, str) else result_json
            
            # 🆕 将思考过程添加到结果中
            if thinking:
                result["_thinking"] = thinking
                result["_usage"] = usage
                logger.info(f"🧠 Thinking process included: {len(thinking)} chars")
            
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
        
        # 从 intent_result 提取基本参数，并验证 topic 有效性
        topic = intent_result.topic
        topic_is_valid = False
        
        if topic:
            # 验证 topic 是否有效（长度 >= 2，且不是纯数字/序数词）
            invalid_topics = ["第一", "第二", "第三", "这", "那", "它", "这个", "那个"]
            if len(topic) >= 2 and topic not in invalid_topics and not topic.isdigit():
                params["topic"] = topic
                topic_is_valid = True
            else:
                logger.info(f"⚠️  Invalid topic detected: '{topic}', will use fallback")
        
        # 🆕 Topic Fallback 策略
        if not topic_is_valid:
            if "session_context" in context:
                session_ctx = context["session_context"]
                current_topic = None
                artifact_history = []
                
                if isinstance(session_ctx, dict):
                    current_topic = session_ctx.get('current_topic')
                    artifact_history = session_ctx.get('artifact_history', [])
                else:
                    current_topic = getattr(session_ctx, 'current_topic', None)
                    artifact_history = getattr(session_ctx, 'artifact_history', [])
                
                # 🎯 注意：澄清机制已经在 execute() 方法开始时处理
                #    如果执行到这里，说明不需要澄清，直接使用 current_topic fallback
                
                # 标准 fallback: 使用 current_topic
                if current_topic:
                    params["topic"] = current_topic
                    logger.info(f"📎 Topic fallback: using session current_topic = {current_topic}")
                else:
                    logger.warning(f"⚠️  No valid topic found in intent_result or session_context for {skill.id}")
        
        # 添加 memory_summary
        if "memory_summary" in context:
            params["memory_summary"] = context["memory_summary"]
        
        # V1.5: 检查是否需要引用上一轮 artifact
        if hasattr(intent_result, 'parameters') and intent_result.parameters:
            use_last_artifact = intent_result.parameters.get('use_last_artifact', False)
            if use_last_artifact and "session_context" in context:
                session_ctx = context["session_context"]
                # session_ctx 可能是字典（model_dump后）或对象
                if isinstance(session_ctx, dict):
                    last_artifact_content = session_ctx.get('last_artifact_content')
                else:
                    last_artifact_content = getattr(session_ctx, 'last_artifact_content', None)
                
                if last_artifact_content:
                    # 🆕 智能提取：基于Intent Router识别的引用类型提取内容
                    import json
                    
                    # 🆕 优先从 artifact_history 中搜索（支持多轮引用）
                    artifact_history = getattr(session_ctx, 'artifact_history', []) if not isinstance(session_ctx, dict) else session_ctx.get('artifact_history', [])
                    
                    source_content = last_artifact_content
                    reference_type = intent_result.parameters.get("reference_type")
                    reference_index = intent_result.parameters.get("reference_index")
                    reference_description = intent_result.parameters.get("reference_description")
                    
                    # 🔍 如果有reference_description，尝试从历史中搜索匹配的artifact
                    if reference_description and artifact_history:
                        matched_artifact = self._search_artifact_history(artifact_history, reference_description)
                        if matched_artifact:
                            source_content = matched_artifact.content
                            logger.info(f"🔍 Found matching artifact in history: #{matched_artifact.turn_number} ({matched_artifact.artifact_type})")
                        else:
                            logger.info(f"ℹ️  No match found in history for '{reference_description}', using last_artifact")
                    
                    # 1️⃣ 引用特定题目（明确序号）
                    if reference_type == "question" and isinstance(reference_index, int):
                        if isinstance(last_artifact_content, dict) and "questions" in last_artifact_content:
                            questions = last_artifact_content["questions"]
                            if 1 <= reference_index <= len(questions):
                                specific_question = questions[reference_index - 1]
                                source_content = {
                                    "quiz_set_id": last_artifact_content.get("quiz_set_id"),
                                    "subject": last_artifact_content.get("subject"),
                                    "specific_question": specific_question,
                                    "question_number": reference_index
                                }
                                logger.info(f"✨ LLM detected: Extract question #{reference_index} from quiz_set")
                    
                    # 2️⃣ 引用特定例子（明确序号）
                    elif reference_type == "example" and isinstance(reference_index, int):
                        if isinstance(last_artifact_content, dict) and "examples" in last_artifact_content:
                            examples = last_artifact_content["examples"]
                            if 1 <= reference_index <= len(examples):
                                specific_example = examples[reference_index - 1]
                                source_content = {
                                    "concept": last_artifact_content.get("concept"),
                                    "subject": last_artifact_content.get("subject"),
                                    "specific_example": specific_example,
                                    "example_number": reference_index,
                                    "all_examples": examples  # 保留上下文
                                }
                                logger.info(f"✨ LLM detected: Extract example #{reference_index} from explanation")
                    
                    # 3️⃣ 引用所有例子
                    elif reference_type == "examples" and reference_index == "all":
                        if isinstance(last_artifact_content, dict) and "examples" in last_artifact_content:
                            source_content = {
                                "concept": last_artifact_content.get("concept"),
                                "subject": last_artifact_content.get("subject"),
                                "all_examples": last_artifact_content["examples"]
                            }
                            logger.info(f"✨ LLM detected: Use all {len(last_artifact_content['examples'])} examples")
                    
                    # 4️⃣ 引用特定内容（语义搜索）
                    elif reference_type == "content" and reference_description:
                        # 🔍 在last_artifact_content中搜索包含reference_description的内容
                        extracted_content = self._semantic_search_content(
                            last_artifact_content, 
                            reference_description
                        )
                        if extracted_content:
                            source_content = extracted_content
                            logger.info(f"✨ LLM detected: Extract content matching '{reference_description}'")
                        else:
                            logger.warning(f"⚠️  Could not find content matching '{reference_description}', using full content")
                    
                    # 5️⃣ 引用整个artifact（默认）
                    elif reference_type == "last_artifact" or not reference_type:
                        logger.info(f"✨ Using full last_artifact_content as source")
                    
                    # 将内容作为 source_content 传递给 skill
                    if isinstance(source_content, dict):
                        params["source_content"] = json.dumps(source_content, ensure_ascii=False, indent=2)
                    else:
                        params["source_content"] = str(source_content)
                    logger.info(f"📎 Prepared source_content for {skill.id}")
        
        # 添加用户提供的额外参数
        if additional_params:
            params.update(additional_params)
        
        return params
    
    def _search_artifact_history(
        self,
        artifact_history: List[Any],
        keyword: str
    ) -> Optional[Any]:
        """
        在artifact_history中搜索包含keyword的artifact
        
        Args:
            artifact_history: artifact历史记录列表
            keyword: 搜索关键词
        
        Returns:
            匹配的ArtifactRecord，如果没找到返回None
        """
        import json
        
        keyword_lower = keyword.lower()
        
        # 从最新到最旧搜索
        for artifact in reversed(artifact_history):
            # 1. 搜索summary
            if hasattr(artifact, 'summary') and artifact.summary:
                if keyword_lower in artifact.summary.lower():
                    logger.info(f"🎯 Keyword '{keyword}' found in artifact #{artifact.turn_number} summary")
                    return artifact
            
            # 2. 搜索topic
            if hasattr(artifact, 'topic') and artifact.topic:
                if keyword_lower in artifact.topic.lower():
                    logger.info(f"🎯 Keyword '{keyword}' found in artifact #{artifact.turn_number} topic")
                    return artifact
            
            # 3. 搜索content
            if hasattr(artifact, 'content'):
                content_str = json.dumps(artifact.content, ensure_ascii=False).lower()
                if keyword_lower in content_str:
                    logger.info(f"🎯 Keyword '{keyword}' found in artifact #{artifact.turn_number} content")
                    return artifact
        
        return None
    
    def _semantic_search_content(
        self,
        content: Dict[str, Any],
        keyword: str
    ) -> Optional[Dict[str, Any]]:
        """
        在content中搜索包含keyword的部分（简单的关键词匹配）
        
        Args:
            content: 要搜索的内容（last_artifact_content）
            keyword: 搜索关键词（如 "北极冰川"、"温室效应"）
        
        Returns:
            匹配的内容，如果没找到返回None
        """
        import json
        
        # 将content转为字符串便于搜索
        content_str = json.dumps(content, ensure_ascii=False).lower()
        keyword_lower = keyword.lower()
        
        # 1. 在examples中搜索
        if "examples" in content and isinstance(content["examples"], list):
            for idx, example in enumerate(content["examples"]):
                example_str = json.dumps(example, ensure_ascii=False).lower()
                if keyword_lower in example_str:
                    logger.info(f"🔍 Found keyword '{keyword}' in example #{idx+1}")
                    return {
                        "concept": content.get("concept"),
                        "subject": content.get("subject"),
                        "specific_example": example,
                        "example_number": idx + 1,
                        "matched_keyword": keyword,
                        "all_examples": content["examples"]
                    }
        
        # 2. 在questions中搜索
        if "questions" in content and isinstance(content["questions"], list):
            for idx, question in enumerate(content["questions"]):
                question_str = json.dumps(question, ensure_ascii=False).lower()
                if keyword_lower in question_str:
                    logger.info(f"🔍 Found keyword '{keyword}' in question #{idx+1}")
                    return {
                        "quiz_set_id": content.get("quiz_set_id"),
                        "subject": content.get("subject"),
                        "specific_question": question,
                        "question_number": idx + 1,
                        "matched_keyword": keyword
                    }
        
        # 3. 在flashcards中搜索
        if "flashcards" in content and isinstance(content["flashcards"], list):
            matched_cards = []
            for idx, card in enumerate(content["flashcards"]):
                card_str = json.dumps(card, ensure_ascii=False).lower()
                if keyword_lower in card_str:
                    matched_cards.append(card)
            
            if matched_cards:
                logger.info(f"🔍 Found keyword '{keyword}' in {len(matched_cards)} flashcard(s)")
                return {
                    "flashcard_set_id": content.get("flashcard_set_id"),
                    "subject": content.get("subject"),
                    "matched_flashcards": matched_cards,
                    "matched_keyword": keyword
                }
        
        # 4. 没找到，返回None
        logger.warning(f"⚠️  Keyword '{keyword}' not found in content")
        return None
    
    async def _execute_plan_skill(
        self,
        skill: SkillDefinition,
        intent_result: IntentResult,
        user_id: str,
        session_id: str,
        additional_params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行 Plan Skill（串联调用多个 skills）
        
        Args:
            skill: Plan Skill 定义
            intent_result: 意图结果
            user_id: 用户 ID
            session_id: 会话 ID
            additional_params: 额外参数
        
        Returns:
            学习包结果
        """
        from .plan_skill_executor import PlanSkillExecutor
        
        logger.info(f"\n{'='*70}")
        logger.info(f"🎯 开始执行 Plan Skill: {skill.id}")
        logger.info(f"{'='*70}\n")
        
        # 获取用户画像和会话上下文
        user_profile = await self.memory_manager.get_user_profile(user_id)
        session_context = await self.memory_manager.get_session_context(session_id)
        
        # 构建用户输入
        user_input = {
            "subject": intent_result.parameters.get("subject") if intent_result.parameters else None,
            "topic": intent_result.topic,
            "difficulty": intent_result.parameters.get("difficulty", "medium") if intent_result.parameters else "medium",
            "memory_summary": self._format_memory_summary(user_profile, session_context)
        }
        
        # 如果 subject 为空，尝试从 topic 中提取
        if not user_input["subject"] and intent_result.topic:
            # 简单提取：假设 topic 可能包含学科信息
            user_input["subject"] = "通用"
        
        # 创建 Plan Skill 执行器
        executor = PlanSkillExecutor(skill_orchestrator=self)
        
        # 执行计划
        try:
            bundle = await executor.execute_plan(
                plan_config=skill.raw_config,  # 🆕 使用原始配置
                user_input=user_input,
                user_profile=user_profile,
                session_context=session_context
            )
            
            # 封装输出
            output = {
                "skill_id": skill.id,
                "content_type": "learning_bundle",
                "response_content": bundle,
                "intent": intent_result.intent
            }
            
            # 更新记忆（保存学习包到 artifact_history）
            await self._update_memory(user_id, session_id, intent_result, bundle)
            
            logger.info(f"✅ Plan Skill 执行完成: {skill.id}")
            
            return output
            
        except Exception as e:
            logger.error(f"❌ Plan Skill 执行失败: {e}")
            logger.exception(e)
            return self._create_error_response(
                "plan_execution_error",
                f"学习包生成失败: {str(e)}"
            )
    
    async def _execute_single_skill(
        self,
        skill_id: str,
        input_params: Dict[str, Any],
        user_profile: Any,
        session_context: Any
    ) -> Dict[str, Any]:
        """
        执行单个 skill（供 PlanSkillExecutor 调用）
        
        Args:
            skill_id: Skill ID
            input_params: 输入参数
            user_profile: 用户画像
            session_context: 会话上下文
        
        Returns:
            Skill 执行结果
        """
        # 从 registry 获取 skill
        skill = None
        for s in self.skill_registry.skills:
            if s.id == skill_id:
                skill = s
                break
        
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")
        
        # 构建上下文
        context = {
            "user_profile": user_profile,
            "session_context": session_context
        }
        
        # 执行 skill
        response = await self._execute_skill(skill, input_params, context)
        
        # 🆕 response 是字典: {"content": str, "thinking": str, "usage": dict}
        # 提取内容
        result_json = response.get("content", response) if isinstance(response, dict) else response
        thinking = response.get("thinking") if isinstance(response, dict) else None
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        
        # 解析结果
        result = json.loads(result_json) if isinstance(result_json, str) else result_json
        
        # 🆕 将思考过程添加到结果中
        if thinking:
            result["_thinking"] = thinking
            result["_usage"] = usage
        
        return result
    
    async def _execute_skill(
        self,
        skill: SkillDefinition,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行技能（调用 Gemini API）- 🆕 支持思考模型
        
        Args:
            skill: Skill 定义
            params: 输入参数
            context: 上下文
        
        Returns:
            Dict[str, Any]: 包含以下键：
                - "content": 生成的内容
                - "thinking": 思考过程（如果有）
                - "usage": Token 使用统计
        """
        # 加载 prompt 模板
        prompt_content = self._load_prompt(skill)
        
        # 构建完整 prompt
        full_prompt = self._format_prompt(prompt_content, params, context)
        
        # 调用 Gemini
        model = skill.models.get("primary", "gemini-2.5-flash")  # 🆕 使用 2.5 Flash
        thinking_budget = skill.thinking_budget or 1024  # 🆕 从 skill 配置读取
        
        logger.debug(f"🤖 Calling Gemini model: {model} (thinking_budget={thinking_budget})")
        
        # 🆕 使用 generate 方法（返回字典）
        response = await self.gemini_client.generate(
            prompt=full_prompt,
            model=model,
            response_format="json",
            thinking_budget=thinking_budget,
            return_thinking=True
        )
        
        # response 是字典: {"content": str, "thinking": str, "usage": dict}
        return response
    
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
        elif "notes_id" in result or "structured_notes" in result:
            content_type = "notes"
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
            
            # 🆕 更新当前主题（只有当有明确主题时）
            #     简单策略：如果 topic 不为 None 且长度>=3，就认为是明确主题
            #     无需硬编码的 invalid_topics 列表，让规则引擎/LLM 决定
            if intent_result.topic and len(intent_result.topic) >= 3:
                session_context.current_topic = intent_result.topic
                logger.info(f"✅ Updated current_topic to: {intent_result.topic}")
            elif intent_result.topic:
                logger.info(f"⏭️  Topic too short ({len(intent_result.topic)} chars), keeping current_topic: {session_context.current_topic}")
            
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

