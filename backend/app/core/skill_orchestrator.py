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
from ..services.kimi import KimiClient  # 🆕 导入 KimiClient
from ..config import settings  # 🆕 导入配置
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
            gemini_client: Gemini Client 实例（兼容参数）
            memory_manager: Memory Manager 实例
        """
        self.skill_registry = skill_registry or get_skill_registry()
        
        # 🔥 根据配置选择 LLM Client
        if settings.KIMI_API_KEY and settings.KIMI_MODEL:
            self.llm_client = KimiClient()
            logger.info("✅ Using Kimi Client for LLM operations")
        else:
            self.llm_client = gemini_client or GeminiClient()
            logger.info("✅ Using Gemini Client for LLM operations")
        
        # 保持向后兼容
        self.gemini_client = self.llm_client
        
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
            
            # 🔧 检测Plan Skill - Plan Skill不支持流式（暂时回退到传统模式）
            logger.debug(f"🔍 Checking skill type: skill.id={skill.id}, skill.skill_type={skill.skill_type}")
            
            # 🔧 增强检测：检查skill_type或skill.id（防止skill_type未加载）
            is_plan_skill = (
                skill.skill_type == "plan" or 
                skill.id == "learning_plan_skill" or
                "plan" in skill.id.lower()
            )
            
            if is_plan_skill:
                # 🆕 Plan Skill 流式执行
                logger.info(f"🌊 Executing Plan Skill in streaming mode")
                
                # 加载用户画像和会话上下文
                user_profile = await self.memory_manager.get_user_profile(user_id)
                session_context = await self.memory_manager.get_session_context(session_id)
                
                # 构建输入参数
                context = await self._build_context(skill, user_id, session_id)
                input_params = self._build_input_params(
                    skill, intent_result, context, additional_params
                )
                
                # 使用PlanSkillExecutor流式执行
                from .plan_skill_executor import PlanSkillExecutor
                plan_executor = PlanSkillExecutor(skill_orchestrator=self)
                
                async for chunk in plan_executor.execute_plan_stream(
                    plan_config=skill.raw_config,
                    user_input=input_params,
                    user_profile=user_profile,
                    session_context=session_context
                ):
                    yield chunk
                
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
            
            # 🔥 使用 llm_client（支持 Kimi 或 Gemini）
            async for chunk in self.llm_client.generate_stream(
                prompt=prompt,
                model=skill.models.get("primary", self.llm_client.model),  # 使用 llm_client 的默认模型
                thinking_budget=skill.thinking_budget or 64,  # ⚡⚡⚡ 极速思考：64 tokens（~5-10秒）
                buffer_size=1,  # ⚡⚡⚡⚡ 极限优化：每个字符立即发送
                temperature=getattr(skill, 'temperature', 1.0)  # ⚡⚡⚡ 最大化速度
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
            
            # 🔥 如果content没有流式发送过（Kimi一次性生成），强制拆分流式显示
            content_chunks_sent = len(content_accumulated)
            logger.info(f"📊 Content chunks received: {content_chunks_sent}")
            
            if content_chunks_sent == 0 and full_content:
                # 完全没有content chunks，但有完整content（不应该发生）
                logger.warning(f"⚠️  No content chunks but have full_content, forcing stream")
                # 强制拆分发送
                chunk_size = 50
                for i in range(0, len(full_content), chunk_size):
                    mini_chunk = full_content[i:i+chunk_size]
                    accumulated_so_far = full_content[:i+len(mini_chunk)]
                    yield {
                        "type": "content",
                        "text": mini_chunk,
                        "accumulated": accumulated_so_far
                    }
            elif content_chunks_sent > 0 and content_chunks_sent < 5:
                # Content chunks太少（可能Kimi一次性生成了大块），强制拆分最后一块
                logger.info(f"📦 Content sent in {content_chunks_sent} large chunks, forcing granular stream")
                # 如果最后一块很大，拆分它
                if len(content_accumulated) > 0:
                    last_chunk = content_accumulated[-1]
                    if len(last_chunk) > 100:  # 如果最后一块超过100字符
                        logger.info(f"✂️  Splitting large final chunk ({len(last_chunk)} chars)")
                        chunk_size = 50
                        base_accumulated = "".join(content_accumulated[:-1])
                        for i in range(0, len(last_chunk), chunk_size):
                            mini_chunk = last_chunk[i:i+chunk_size]
                            accumulated_so_far = base_accumulated + last_chunk[:i+len(mini_chunk)]
                            yield {
                                "type": "content",
                                "text": mini_chunk,
                                "accumulated": accumulated_so_far
                            }
            
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
            
            # 检查内容是否为空（可能因API错误中断）
            if not json_str or len(json_str.strip()) < 10:
                logger.error(f"❌ Content is empty or too short, likely due to API interruption")
                yield {
                    "type": "error",
                    "message": "AI服务暂时过载，请稍后重试 (503 Service Unavailable)"
                }
                return
            
            # 检查内容是否看起来像markdown（而不是JSON）
            if json_str.strip().startswith('**') or json_str.strip().startswith('#'):
                logger.error(f"❌ Content appears to be markdown, not JSON - API stream was interrupted")
                yield {
                    "type": "error",
                    "message": "AI服务中断了生成过程，请刷新页面后重试"
                }
                return
            
            # 尝试解析 JSON
            try:
                parsed_content = json.loads(json_str)
                logger.info(f"✅ JSON parsed successfully")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse JSON: {e}")
                logger.error(f"Content preview: {json_str[:200]}")
                
                # 🔧 尝试修复截断的JSON
                # 策略：添加缺失的闭合符号
                if "Unterminated string" in str(e) or "Expecting" in str(e):
                    logger.warning(f"⚠️  JSON appears truncated, attempting to fix...")
                    
                    # 尝试添加缺失的 ] 和 }
                    fixed_attempts = [
                        json_str + '"}]}}',  # 尝试1: 字符串+数组+对象
                        json_str + '"]}}',    # 尝试2: 数组+对象
                        json_str + '}]}}',    # 尝试3: 对象+数组+对象
                        json_str + '}}',      # 尝试4: 对象
                        json_str + ']}'       # 尝试5: 数组+对象
                    ]
                    
                    for i, attempt in enumerate(fixed_attempts):
                        try:
                            parsed_content = json.loads(attempt)
                            logger.info(f"✅ JSON fixed and parsed (attempt {i+1})")
                            break
                        except:
                            continue
                    else:
                        # 所有尝试都失败
                        yield {
                            "type": "error",
                            "message": "生成内容格式错误（JSON截断），请重试"
                        }
                        return
                else:
                    yield {
                        "type": "error",
                        "message": "生成内容格式错误，请重试"
                    }
                    return
            
            # Step 7: 检测内容类型（使用和传统API相同的逻辑）
            content_type = "unknown"
            if "quiz_set_id" in parsed_content or "questions" in parsed_content:
                content_type = "quiz_set"
            elif "concept" in parsed_content or "explanation" in parsed_content:
                content_type = "explanation"
            elif "flashcard_set_id" in parsed_content or "cards" in parsed_content:
                content_type = "flashcard_set"
            elif "notes_id" in parsed_content or "structured_notes" in parsed_content:
                content_type = "notes"
            elif "bundle_id" in parsed_content or "components" in parsed_content:
                content_type = "learning_bundle"
            elif "mindmap_id" in parsed_content or "root" in parsed_content:
                content_type = "mindmap"
            elif "error" in parsed_content:
                content_type = "error"
            
            logger.info(f"✅ Detected content_type: {content_type}")
            
            # Step 8: 更新 memory（保存 artifact，构建用户画像）
            logger.info(f"💾 Saving artifact in stream mode (type: {content_type})")
            
            # 🔥 调用统一的 _update_memory 方法
            try:
                await self._update_memory(
                    user_id=user_id,
                    session_id=session_id,
                    intent_result=intent_result,
                    skill_result=parsed_content
                )
                logger.info(f"✅ Artifact saved and memory updated in stream mode")
            except Exception as e:
                logger.error(f"❌ Failed to save artifact in stream mode: {e}")
                # 不中断流程，继续返回结果
            
            # Step 9: 追加到 Conversation Session MD 文件
            try:
                session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
                await session_mgr.start_or_continue_session(intent_result.raw_text)
                
                await session_mgr.append_turn({
                    "user_query": intent_result.raw_text,
                    "agent_response": {
                        "skill": skill.id,
                        "artifact_id": parsed_content.get("artifact_id", ""),
                        "content": parsed_content
                    },
                    "response_type": content_type,
                    "timestamp": datetime.now(),
                    "intent": intent_result.model_dump(),
                    "metadata": {
                        "thinking_tokens": len(full_thinking.split()),  # 粗略估算
                        "output_tokens": len(full_content.split()),  # 粗略估算
                        "model": skill.models.get("primary", "unknown")
                    }
                })
                logger.debug(f"📝 Appended turn to conversation session MD (stream mode)")
            except Exception as e:
                logger.error(f"❌ Failed to append to conversation session (stream): {e}")
            
            # 完成
            yield {
                "type": "done",
                "thinking": full_thinking,
                "content": parsed_content,
                "content_type": content_type
            }
            
            logger.info(f"✅ Stream orchestration complete for {skill.id}")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Stream orchestration error: {e}")
            
            # 检测503错误（API过载）
            if "503" in error_msg or "overloaded" in error_msg.lower() or "unavailable" in error_msg.lower():
                yield {
                    "type": "error",
                    "message": "🔄 AI服务暂时过载，请等待10-30秒后重试",
                    "code": 503
                }
            else:
                yield {
                    "type": "error",
                    "message": f"发生错误: {error_msg}",
                    "code": 500
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
        logger.info(f"🎯 Orchestrating: intent={intent_result.intent}, topic={intent_result.topic}, confidence={intent_result.confidence:.2f}")
        
        # ============= Phase 0: 智能澄清机制（优先级最高）=============
        
        # 🆕 置信度过低：提供澄清选项
        if intent_result.confidence < 0.60:  # 置信度 < 60%
            logger.info(f"⚠️ Low confidence ({intent_result.confidence:.2f}), requesting clarification")
            
            session_context = await self.memory_manager.get_session_context(session_id)
            recent_intents = session_context.recent_intents[-5:] if session_context and session_context.recent_intents else []
            
            # 构建意图选项
            intent_options = []
            intent_labels = {
                "explain_request": {"label": "解释概念", "icon": "📖", "description": "详细讲解一个知识点"},
                "quiz_request": {"label": "练习题目", "icon": "✍️", "description": "生成测试题"},
                "flashcard_request": {"label": "记忆闪卡", "icon": "🗂️", "description": "生成记忆卡片"},
                "notes": {"label": "学习笔记", "icon": "📝", "description": "生成结构化笔记"},
                "mindmap": {"label": "思维导图", "icon": "🧠", "description": "生成知识导图"},
            }
            
            # 优先显示最近使用的意图
            for intent in recent_intents:
                if intent in intent_labels and intent not in [opt["value"] for opt in intent_options]:
                    info = intent_labels[intent]
                    intent_options.append({
                        "type": "intent",
                        "label": info["label"],
                        "value": intent,
                        "icon": info["icon"],
                        "description": info["description"]
                    })
            
            # 补充其他常用意图
            for intent, info in intent_labels.items():
                if intent not in [opt["value"] for opt in intent_options]:
                    intent_options.append({
                        "type": "intent",
                        "label": info["label"],
                        "value": intent,
                        "icon": info["icon"],
                        "description": info["description"]
                    })
            
            return {
                "content_type": "clarification_needed",
                "intent": "clarification",
                "response_content": {
                    "question": "抱歉，我不太确定您想要什么。请选择一个选项：",
                    "reason": "low_confidence",
                    "confidence": intent_result.confidence,
                    "options": intent_options[:5],  # 最多5个选项
                    "allow_custom_input": True,
                    "custom_input_placeholder": "或者用其他方式描述您的需求...",
                    "original_intent": intent_result.intent,
                    "original_message": intent_result.raw_text
                }
            }
        
        # ============= Phase 0 继续: 主题相关澄清 =============
        
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
            
            # 🆕 多主题澄清：即使有 current_topic，如果有多个历史主题也应询问
            if len(artifact_history) > 0 and not topic_is_valid:
                # 提取最近的主题列表
                recent_topics = await self._extract_recent_topics(session_id)
                
                # 如果有多个主题，提供澄清选项
                if len(recent_topics) >= 2:
                    logger.info(f"❓ Multiple topics detected ({len(recent_topics)} topics), requesting clarification")
                    
                    return {
                        "content_type": "clarification_needed",
                        "intent": intent_result.intent,
                        "response_content": {
                            "question": "我注意到您之前学习了多个主题，请问您想基于哪个主题继续？",
                            "reason": "topic_ambiguous",
                            "options": [
                                {
                                    "type": "topic",
                                    "label": topic,
                                    "value": topic,
                                    "icon": "📚"
                                }
                                for topic in recent_topics[:5]  # 最多5个选项
                            ],
                            "allow_custom_input": True,
                            "custom_input_placeholder": "或者输入新的主题...",
                            "original_intent": intent_result.intent,
                            "original_message": intent_result.raw_text
                        }
                    }
            
            # 🆕 如果消息中没有明确主题，但有 current_topic，检查是否应该澄清
            # 特殊情况：用户只说"生成X张闪卡"，有多个历史主题
            if topic_is_valid and len(artifact_history) > 0:
                recent_topics = await self._extract_recent_topics(session_id)
                # 如果有3个或更多不同主题，考虑澄清
                if len(recent_topics) >= 3:
                    # 检查消息是否非常模糊（没有明确提到主题）
                    message_lower = intent_result.raw_text.lower()
                    has_explicit_topic = any(topic in message_lower for topic in recent_topics)
                    
                    if not has_explicit_topic:
                        logger.info(f"❓ Ambiguous request with {len(recent_topics)} topics, requesting clarification")
                        
                        return {
                            "content_type": "clarification_needed",
                            "intent": intent_result.intent,
                            "response_content": {
                                "question": f"您想基于哪个主题生成？（当前默认：{intent_result.topic}）",
                                "reason": "topic_ambiguous",
                                "options": [
                                    {
                                        "type": "topic",
                                        "label": topic,
                                        "value": topic,
                                        "icon": "📚"
                                    }
                                    for topic in recent_topics[:5]
                                ],
                                "allow_custom_input": True,
                                "custom_input_placeholder": "或者输入新的主题...",
                                "original_intent": intent_result.intent,
                                "original_message": intent_result.raw_text
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
        
        # Step 7: 追加到 Conversation Session MD 文件
        try:
            session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
            await session_mgr.start_or_continue_session(intent_result.raw_text)
            
            await session_mgr.append_turn({
                "user_query": intent_result.raw_text,
                "agent_response": {
                    "skill": skill.id,
                    "artifact_id": result.get("artifact_id", ""),
                    "content": result
                },
                "response_type": output.get("content_type", "unknown"),
                "timestamp": datetime.now(),
                "intent": intent_result.model_dump(),
                "metadata": {
                    "thinking_tokens": result.get("_usage", {}).get("thinking_tokens", 0),
                    "output_tokens": result.get("_usage", {}).get("output_tokens", 0),
                    "model": skill.models.get("primary", "unknown")
                }
            })
            logger.debug(f"📝 Appended turn to conversation session MD")
        except Exception as e:
            logger.error(f"❌ Failed to append to conversation session: {e}")
        
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
        
        包括：
        1. 用户画像和会话上下文
        2. 最近的 artifacts（用于上下文连续性）
        3. Memory summary（行为总结）
        
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
            
            # 🔥 加载最近的 artifacts（构建上下文连续性）
            try:
                recent_artifacts = []
                if session_context.artifact_history:
                    # 获取最近的 3 个 artifacts
                    recent_artifact_ids = session_context.artifact_history[-3:]
                    
                    for artifact_id in recent_artifact_ids:
                        artifact_content = await self.memory_manager.get_artifact(artifact_id)
                        if artifact_content:
                            recent_artifacts.append({
                                "artifact_id": artifact_id,
                                "content": artifact_content
                            })
                
                context["recent_artifacts"] = recent_artifacts
                logger.info(f"📚 Loaded {len(recent_artifacts)} recent artifacts for context")
                
            except Exception as e:
                logger.warning(f"⚠️  Failed to load recent artifacts: {e}")
                context["recent_artifacts"] = []
        
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
        
        # 🆕 V1.7: 提取 quantity 参数（优先使用具体参数名）
        if hasattr(intent_result, 'parameters') and intent_result.parameters:
            quantity = None
            
            # 根据不同的 skill 优先查找对应的参数
            if skill.id == 'quiz_skill':
                # 优先查找 num_questions，然后是 quantity
                quantity = intent_result.parameters.get('num_questions') or intent_result.parameters.get('quantity')
                if quantity is None:
                    quantity = 5  # 默认 5 道题
                params['num_questions'] = quantity
                logger.info(f"📊 Quiz quantity: {quantity}")
                
            elif skill.id == 'flashcard_skill':
                # 优先查找 num_cards，然后是 quantity
                quantity = intent_result.parameters.get('num_cards') or intent_result.parameters.get('quantity')
                if quantity is None:
                    quantity = 5  # 默认 5 张卡
                params['num_cards'] = quantity
                logger.info(f"📊 Flashcard quantity: {quantity}")
        
        # 🔥 合并所有 intent parameters (除了已经被处理的)
        # 这确保 Plan Skill 可以接收 flashcard_quantity, quiz_quantity 等自定义参数
        # ⚠️  只合并非空值，避免传递 None 或空字符串导致后续处理错误
        if hasattr(intent_result, 'parameters') and intent_result.parameters:
            for key, value in intent_result.parameters.items():
                # 过滤掉 None、空字符串、空列表等无效值
                if value is not None and value != "" and value != [] and key not in params:
                    params[key] = value
        
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
        
        # 生成 memory summary
        memory_summary = await self.memory_manager.generate_memory_summary(user_id, session_id)
        
        # 构建用户输入
        user_input = {
            "subject": intent_result.parameters.get("subject") if intent_result.parameters else None,
            "topic": intent_result.topic,
            "difficulty": intent_result.parameters.get("difficulty", "medium") if intent_result.parameters else "medium",
            "memory_summary": memory_summary.recent_behavior  # 🔧 使用 generate_memory_summary 结果
        }
        
        # 🔥 将所有 intent parameters 合并到 user_input，确保 Plan Skill 可以访问所有提取的参数
        # (例如 flashcard_quantity, quiz_quantity 等)
        # ⚠️  只合并非空值，避免传递 None 或空字符串导致后续处理错误
        if intent_result.parameters:
            for key, value in intent_result.parameters.items():
                # 过滤掉 None、空字符串、空列表等无效值
                if value is not None and value != "" and value != [] and key not in user_input:
                    user_input[key] = value
                    logger.debug(f"📝 Merged parameter from intent: {key}={value}")
        
        # 如果 subject 为空，尝试从 topic 中提取
        if not user_input.get("subject") and intent_result.topic:
            # 简单提取：假设 topic 可能包含学科信息
            user_input["subject"] = "通用"
        
        # 🐛 DEBUG: Log final user_input before executing plan
        logger.debug(f"📥 Final user_input for Plan Skill: {user_input}")
        
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
        # 从 registry 获取 skill（使用公共方法）
        skill = self.skill_registry.get_skill(skill_id)
        
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
    
    async def _execute_single_skill_stream(
        self,
        skill_id: str,
        input_params: Dict[str, Any],
        user_profile: Any,
        session_context: Any
    ):
        """
        🆕 流式执行单个skill（用于Plan Skill的每个步骤）
        
        Args:
            skill_id: Skill ID
            input_params: 输入参数
            user_profile: 用户画像
            session_context: 会话上下文
        
        Yields:
            Dict: 流式事件
        """
        # 获取skill
        skill = self.skill_registry.get_skill(skill_id)
        if not skill:
            yield {
                "type": "error",
                "message": f"Skill not found: {skill_id}"
            }
            return
        
        # 加载prompt并格式化
        prompt_content = self._load_prompt(skill)
        context = {
            "user_profile": user_profile,
            "session_context": session_context
        }
        full_prompt = self._format_prompt(prompt_content, input_params, context)
        
        # 流式调用Kimi
        thinking_accumulated = []
        content_accumulated = []
        
        # 获取 thinking_budget（优先使用 skill 配置）
        thinking_budget = getattr(skill, 'thinking_budget', 64)
        logger.info(f"🎯 Executing sub-skill: {skill_id}, thinking_budget={thinking_budget}")
        
        async for chunk in self.gemini_client.generate_stream(
            prompt=full_prompt,
            model=getattr(skill, 'models', {}).get('primary', 'moonshotai/kimi-k2-thinking'),
            thinking_budget=thinking_budget,
            buffer_size=1,
            temperature=getattr(skill, 'temperature', 1.0)
        ):
            # 累积数据
            if chunk["type"] == "thinking":
                thinking_accumulated.append(chunk.get("text", ""))
            elif chunk["type"] == "content":
                content_accumulated.append(chunk.get("text", ""))
            
            # 转发chunk
            yield chunk
        
        # 解析最终结果
        full_thinking = "".join(thinking_accumulated)
        full_content = "".join(content_accumulated)
        
        # 提取JSON
        json_str = full_content
        if "```json" in json_str:
            try:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            except:
                pass
        elif "```" in json_str:
            try:
                json_str = json_str.split("```")[1].split("```")[0].strip()
            except:
                pass
        
        # 解析JSON
        try:
            parsed_content = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse JSON: {e}")
            yield {
                "type": "error",
                "message": "生成内容格式错误，请重试"
            }
            return
        
        # 检测content_type
        content_type = "unknown"
        if "quiz_set_id" in parsed_content or "questions" in parsed_content:
            content_type = "quiz_set"
        elif "concept" in parsed_content:
            content_type = "explanation"
        elif "card_set_id" in parsed_content or "cards" in parsed_content:
            content_type = "flashcard_set"
        elif "structured_notes" in parsed_content:
            content_type = "notes"
        elif "root" in parsed_content:
            content_type = "mindmap"
        
        # 构建完整结果
        result = {
            "skill_id": skill_id,
            "content_type": content_type,
            **parsed_content
        }
        
        # 发送done事件（格式统一：使用content字段）
        yield {
            "type": "done",
            "thinking": full_thinking,
            "content": parsed_content,
            "content_type": content_type
        }
    
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
        model = skill.models.get("primary", "gemini-2.5-flash-lite")  # 🆕 使用 2.5 Flash Lite
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
        import json
        
        # 🔥 Step 1: 替换 prompt 模板中的占位符
        # 准备格式化参数（包括 JSON 序列化）
        format_params = {}
        for k, v in params.items():
            if v is None:
                format_params[k] = ""  # None 替换为空字符串
            elif isinstance(v, (dict, list)):
                # 字典和列表序列化为 JSON
                format_params[k] = json.dumps(v, ensure_ascii=False, indent=2)
            else:
                format_params[k] = str(v)
        
        # 替换模板中的占位符
        try:
            formatted = prompt_template.format(**format_params)
        except KeyError as e:
            # 如果有缺失的参数，记录警告并使用原模板
            logger.warning(f"⚠️  Prompt 模板缺少参数: {e}")
            formatted = prompt_template
        
        # 🔥 Step 2: 附加参数 JSON（作为备用/调试信息）
        # 过滤掉 None 值和不可序列化的对象
        clean_params = {}
        for k, v in params.items():
            if v is not None:
                try:
                    json.dumps(v)
                    clean_params[k] = v
                except (TypeError, ValueError):
                    clean_params[k] = str(v)
        
        params_json = json.dumps(clean_params, ensure_ascii=False, indent=2)
        
        formatted += f"""

## Input Parameters (JSON)

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
        
        包括：
        1. 保存 artifact 到 S3（构建用户画像）
        2. 更新 session context（当前主题、意图历史）
        3. 维护 artifact_history 引用链
        
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
            topic = intent_result.topic
            if topic and len(topic) >= 3:
                session_context.current_topic = topic
                logger.info(f"✅ Updated current_topic to: {topic}")
            elif topic:
                logger.info(f"⏭️  Topic too short ({len(topic)} chars), keeping current_topic: {session_context.current_topic}")
                # 使用 current_topic 作为 fallback
                topic = session_context.current_topic
            else:
                topic = session_context.current_topic or "未知主题"
            
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
            
            # 🔥 核心：保存 artifact 到 S3，构建用户画像
            try:
                # 确定 artifact 类型
                artifact_type_mapping = {
                    "quiz_request": "quiz_set",
                    "flashcard_request": "flashcard_set",
                    "explain_request": "explanation",
                    "notes": "notes",
                    "mindmap": "mindmap",
                    "learning_bundle": "learning_bundle"
                }
                
                artifact_type = artifact_type_mapping.get(intent, intent)
                
                # 移除内部字段
                artifact_content = {k: v for k, v in skill_result.items() if not k.startswith('_')}
                
                # 保存到 S3
                artifact_record = await self.memory_manager.save_artifact(
                    session_id=session_id,
                    artifact=artifact_content,
                    artifact_type=artifact_type,
                    topic=topic,
                    user_id=user_id
                )
                
                logger.info(f"✅ Artifact saved: {artifact_record.artifact_id} (Storage: {artifact_record.storage_type})")
                
                # 注意：artifact_history 已经在 memory_manager.save_artifact() 中更新了
                # 这里不需要重复添加，只需要记录日志
                session_context_updated = await self.memory_manager.get_session_context(session_id)
                logger.info(f"📝 Artifact history updated: {len(session_context_updated.artifact_history)} artifacts")
                
            except Exception as e:
                logger.error(f"❌ Failed to save artifact: {e}")
                # 不中断流程，继续更新 session context
            
            await self.memory_manager.update_session_context(session_id, session_context)
            
            logger.debug(f"📝 Memory updated for user {user_id}, session {session_id}")
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to update memory: {e}")
    
    async def _extract_recent_topics(self, session_id: str) -> List[str]:
        """
        从 session context 提取最近的主题列表
        
        Args:
            session_id: 会话 ID
        
        Returns:
            主题列表（去重，按最近顺序）
        """
        try:
            session_context = await self.memory_manager.get_session_context(session_id)
            
            if not session_context or not session_context.artifact_history:
                return []
            
            # 从 artifact_history 提取主题
            topics = []
            seen_topics = set()
            
            # 倒序遍历（最近的优先）
            for artifact_id in reversed(session_context.artifact_history[-10:]):  # 最近10个
                # artifact_id 格式: artifact_{type}_{topic}_{timestamp}
                parts = artifact_id.split('_')
                if len(parts) >= 3:
                    # 提取 topic（可能包含多个部分）
                    topic_parts = parts[2:-1]  # 排除 type 和 timestamp
                    if topic_parts:
                        topic = '_'.join(topic_parts)
                        if topic and topic not in seen_topics and topic != "未知主题":
                            topics.append(topic)
                            seen_topics.add(topic)
            
            logger.info(f"📚 Extracted {len(topics)} recent topics: {topics}")
            return topics
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to extract recent topics: {e}")
            return []
    
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

