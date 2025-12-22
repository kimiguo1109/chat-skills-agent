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
try:
    from ..services.gemini import GeminiClient
except ImportError:
    GeminiClient = None
from ..services.kimi import KimiClient  # 🆕 导入 KimiClient
from ..config import settings  # 🆕 导入配置
from .skill_registry import SkillRegistry, get_skill_registry
from .memory_manager import MemoryManager
from .thinking_mode_selector import ThinkingModeSelector  # 🆕 导入智能思考模式选择器
from .reference_resolver import get_reference_resolver, ReferenceResolver  # 🆕 导入引用解析器

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
        
        # 🔧 临时配置：全部使用 Gemini（关闭 Kimi 以提升速度）
        self.llm_client = gemini_client or GeminiClient()
        logger.info("✅ Using Gemini Client for ALL LLM operations (Kimi disabled)")
        
        # Gemini Client 也指向同一实例
        self.gemini_client = self.llm_client
        logger.info("✅ All thinking modes use Gemini 2.5 Flash")
        
        # 确保 MemoryManager 使用 S3（如果配置启用）
        self.memory_manager = memory_manager or MemoryManager(use_s3=settings.USE_S3_STORAGE)
        
        # 🆕 初始化智能思考模式选择器
        self.thinking_mode_selector = ThinkingModeSelector()
        
        # Prompt 文件目录
        self.prompts_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts"
        )
        
        logger.info("✅ SkillOrchestrator initialized with ThinkingModeSelector")
    
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
            
            # ============= Phase -1: 处理 clarification_needed (流式版本) =============
            
            if intent_result.intent == "clarification_needed":
                reason = intent_result.parameters.get('clarification_reason')
                logger.warning(f"⚠️  Clarification needed: {reason}")
                
                # 获取session context
                session_context = await self.memory_manager.get_session_context(session_id)
                
                if reason == "topic_missing":
                    # Topic 缺失，需要用户提供
                    recent_topics = []
                    if session_context and session_context.artifact_history:
                        recent_topics = [a.topic for a in session_context.artifact_history[-5:] if a.topic]  # 最近5个topics
                    
                    if recent_topics:
                        # 有历史 topics，让用户选择
                        yield {
                            "type": "done",
                            "content_type": "clarification_needed",
                            "content": {
                                "question": "您想基于以下哪个主题继续？",
                                "reason": "topic_missing",
                                "options": [
                                    {
                                        "type": "topic",
                                        "label": topic,
                                        "value": topic,
                                        "icon": "📚",
                                        "description": f"继续学习：{topic}"
                                    }
                                    for topic in recent_topics
                                ],
                                "allow_custom_input": True,
                                "custom_input_placeholder": "或输入新的学习主题..."
                            }
                        }
                    else:
                        # 没有历史 topics，请求用户输入
                        yield {
                            "type": "done",
                            "content_type": "clarification_needed",
                            "content": {
                                "question": "请问您想学习什么主题？",
                                "reason": "topic_missing",
                                "options": [],
                                "allow_custom_input": True,
                                "custom_input_placeholder": "例如：光合作用、二战历史、微积分..."
                            }
                        }
                    return
                
                elif reason == "multi_topic_insufficient":
                    # 用户请求多个 topics，但历史不足
                    yield {
                        "type": "done",
                        "content_type": "clarification_needed",
                        "content": {
                            "question": "您提到了多个主题，但我暂时只记录了一个主题。可以告诉我具体是哪些主题吗？",
                            "reason": "multi_topic_insufficient",
                            "options": [],
                            "allow_custom_input": True,
                            "custom_input_placeholder": "例如：光合作用和二战历史"
                        }
                    }
                    return
            
            # 🆕 处理 'other' intent（普通对话）
            if intent_result.intent == "other":
                logger.info(f"💬 Handling 'other' intent as chat conversation")
                async for chunk in self._handle_chat_stream(intent_result, user_id, session_id):
                    yield chunk
                return
            
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
                
                # 收集最终结果（用于追加到 MD）
                final_content = None
                
                async for chunk in plan_executor.execute_plan_stream(
                    plan_config=skill.raw_config,
                    user_input=input_params,
                    user_profile=user_profile,
                    session_context=session_context
                ):
                    # 转发给前端
                    yield chunk
                    
                    # 收集最终结果
                    if chunk.get("type") == "done":
                        final_content = chunk.get("content", {})
                
                # 追加到 Conversation Session MD 文件
                if final_content:
                    try:
                        session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
                        await session_mgr.start_or_continue_session(intent_result.raw_text, session_id=session_id)
                        
                        await session_mgr.append_turn({
                            "user_query": intent_result.raw_text,
                            "agent_response": {
                                "skill": skill.id,
                                "artifact_id": final_content.get("bundle_id", ""),
                                "content": final_content
                            },
                            "response_type": "learning_bundle",
                            "timestamp": datetime.now(),
                            "intent": intent_result.model_dump(),
                            "metadata": {
                                "thinking_tokens": 0,  # Plan Skill 没有单独的 thinking
                                "output_tokens": 0,
                                "model": skill.models.get("primary", "unknown")
                            }
                        })
                        logger.debug(f"📝 Appended Plan Skill turn to conversation session MD")
                    except Exception as e:
                        logger.error(f"❌ Failed to append Plan Skill to conversation session: {e}")
                
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
            
            # 🆕 Step 3.1: 引用解析（如果消息包含对历史 artifacts 的引用）
            if intent_result.has_reference:
                reference_resolver = get_reference_resolver()
                session_context_for_ref = await self.memory_manager.get_session_context(session_id)
                
                if session_context_for_ref and session_context_for_ref.artifact_history:
                    resolved_refs = reference_resolver.resolve_references(
                        intent_result.raw_text,
                        session_context_for_ref.artifact_history
                    )
                    
                    if resolved_refs:
                        resolved_content = reference_resolver.format_resolved_content(resolved_refs)
                        if resolved_content:
                            params["referenced_content"] = resolved_content
                            logger.info(f"🔗 Resolved {len(resolved_refs)} reference(s): {len(resolved_content)} chars")
                            
                            # 🆕 使用来源 artifact 的 topic（而非 current_topic）
                            # 例如：用户说 "把第一张闪卡出题"，闪卡是光合作用的，
                            # 即使 current_topic 是细胞呼吸，也应该用光合作用
                            source_topic = resolved_refs[0].source_topic
                            if source_topic:
                                params["topic"] = source_topic
                                intent_result.topic = source_topic  # 🔧 也更新 intent_result
                                logger.info(f"🔗 Using source topic from referenced artifact: {source_topic}")
                            
                            yield {
                                "type": "status",
                                "message": f"📎 已提取引用内容 (来源: {source_topic or '未知'})"
                            }
            
            # 检查是否需要澄清
            if not params.get("topic"):
                yield {
                    "type": "clarification_needed",
                    "message": "需要明确学习主题"
                }
                return
            
            # 🆕 Step 3.5: 多主题澄清检查（流式版本）
            session_context = await self.memory_manager.get_session_context(session_id)
            
            # 🔧 如果引用已经解析成功，跳过多主题澄清
            # 因为引用解析已经确定了目标内容的 topic
            reference_resolved = params.get("referenced_content") is not None
            
            # 检查是否有多个主题需要澄清
            if not reference_resolved and session_context and session_context.artifact_history:
                recent_topics = await self._extract_recent_topics(session_id)
                
                # 如果有 2+ 个不同主题，且用户没有明确指定主题
                if len(recent_topics) >= 2:
                    # 检查用户消息是否明确提到了某个主题
                    message_lower = intent_result.raw_text.lower()
                    has_explicit_topic = any(topic.lower() in message_lower for topic in recent_topics)
                    
                    if not has_explicit_topic:
                        logger.info(f"❓ Multi-topic clarification needed: {recent_topics}")
                        yield {
                            "type": "done",
                            "content_type": "clarification_needed",
                            "content": {
                                "question": f"您想基于哪个主题继续？",
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
                        return
            elif reference_resolved:
                logger.info(f"✅ Reference resolved, skipping multi-topic clarification")
            
            # 🆕 Step 3.6: 智能选择思考模式
            thinking_config = self.thinking_mode_selector.select_mode(
                intent_result=intent_result,
                session_context=session_context
            )
            
            # 🔧 临时配置：全部使用 Gemini（关闭 Kimi）
            active_client = GeminiClient()
            logger.info(f"⚡ Using Gemini: {thinking_config['reasoning']}")
            
            # 通知前端使用的模式
            yield {
                "type": "status",
                "message": f"🤖 {thinking_config['reasoning']}"
            }
            
            # Step 4: 加载 prompt
            prompt_content = self._load_prompt(skill)
            prompt = self._format_prompt(prompt_content, params, context)
            
            # 🆕 Step 4.5: 发送上下文预览（让用户知道基于什么生成）
            context_preview = self._generate_context_preview(
                context=context,
                params=params,
                thinking_mode=thinking_config["mode"]
            )
            if context_preview:
                yield {
                    "type": "context_preview",
                    "message": context_preview["message"],
                    "details": context_preview.get("details", [])
                }
            
            # 🔥 Step 4.6: flashcard_skill 特殊处理 - 总是调用外部 API
            # 📌 外部 API 支持多种输入：
            #    - 有 reference_explanation（前面有解释内容）→ 使用解释内容
            #    - 有 referenced_content（用户引用了历史内容）→ 使用引用内容
            #    - 有 input_text（用户提供的原始文本）→ 使用原始文本
            #    - 只有 topic → 使用 topic 作为输入
            
            if skill.id == 'flashcard_skill':
                logger.info(f"🌐 Using External API for flashcard_skill")
                yield {
                    "type": "status",
                    "message": "🌐 正在调用外部服务生成闪卡..."
                }
                
                try:
                    # 调用外部 API
                    api_result = await self._execute_flashcard_via_external_api(params, context)
                    
                    # 解析结果
                    parsed_content = json.loads(api_result["content"])
                    content_type = "flashcard_set"
                    
                    # 模拟流式输出 - 发送内容
                    yield {
                        "type": "content",
                        "text": api_result["content"],
                        "accumulated": api_result["content"]
                    }
                    
                    # Step 8: 更新 memory（保存 artifact）
                    logger.info(f"💾 Saving artifact in stream mode (type: {content_type})")
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
                    
                    # 🆕 提取实际 topic
                    actual_topic_stream = self._extract_topic_from_result(parsed_content, intent_result.topic)
                    if actual_topic_stream:
                        intent_result.topic = actual_topic_stream
                    
                    # Step 9: 追加到 Conversation Session MD 文件
                    try:
                        session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
                        await session_mgr.start_or_continue_session(intent_result.raw_text, session_id=session_id)
                        
                        await session_mgr.append_turn({
                            "user_query": intent_result.raw_text,
                            "agent_response": {
                                "skill": skill.id,
                                "artifact_id": parsed_content.get("artifact_id", ""),
                                "content": parsed_content,
                                "topic": actual_topic_stream  # 🆕 实际 topic
                            },
                            "response_type": content_type,
                            "timestamp": datetime.now(),
                            "intent": intent_result.model_dump(),
                            "metadata": {
                                "external_api": True,
                                "model": "external_flashcard_api"
                            }
                        })
                        logger.debug(f"📝 Appended turn to conversation session MD")
                    except Exception as e:
                        logger.error(f"❌ Failed to append to conversation session: {e}")
                    
                    logger.info(f"✅ External API flashcard generation complete")
                    
                    # 发送完成事件
                    yield {
                        "type": "done",
                        "thinking": None,
                        "content": parsed_content,
                        "content_type": content_type,
                        "usage_summary": {"external_api": True}
                    }
                    
                    logger.info(f"✅ Stream orchestration complete for {skill.id} (external API)")
                    return
                    
                except Exception as e:
                    logger.error(f"❌ External flashcard API failed: {e}, falling back to LLM")
                    yield {
                        "type": "status",
                        "message": f"⚠️ 外部服务异常，使用 AI 生成..."
                    }
                    # 继续执行 LLM 流程作为 fallback
            
            # 🔥 Step 4.7: quiz_skill 特殊处理 - 总是调用外部 API
            if skill.id == 'quiz_skill':
                logger.info(f"🌐 Using External API for quiz_skill")
                yield {
                    "type": "status",
                    "message": "🌐 正在调用外部服务生成测验..."
                }
                
                try:
                    # 调用外部 API
                    api_result = await self._execute_quiz_via_external_api(params, context)
                    
                    # 解析结果
                    parsed_content = json.loads(api_result["content"])
                    content_type = "quiz_set"
                    
                    # 模拟流式输出 - 发送内容
                    yield {
                        "type": "content",
                        "text": api_result["content"],
                        "accumulated": api_result["content"]
                    }
                    
                    # Step 8: 更新 memory（保存 artifact）
                    logger.info(f"💾 Saving artifact in stream mode (type: {content_type})")
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
                    
                    # 🆕 提取实际 topic
                    actual_topic_quiz = self._extract_topic_from_result(parsed_content, intent_result.topic)
                    if actual_topic_quiz:
                        intent_result.topic = actual_topic_quiz
                    
                    # Step 9: 追加到 Conversation Session MD 文件
                    try:
                        session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
                        await session_mgr.start_or_continue_session(intent_result.raw_text, session_id=session_id)
                        
                        await session_mgr.append_turn({
                            "user_query": intent_result.raw_text,
                            "agent_response": {
                                "skill": skill.id,
                                "artifact_id": parsed_content.get("artifact_id", ""),
                                "content": parsed_content,
                                "topic": actual_topic_quiz  # 🆕 实际 topic
                            },
                            "response_type": content_type,
                            "timestamp": datetime.now(),
                            "intent": intent_result.model_dump(),
                            "metadata": {
                                "external_api": True,
                                "model": "external_quiz_api"
                            }
                        })
                        logger.debug(f"📝 Appended turn to conversation session MD")
                    except Exception as e:
                        logger.error(f"❌ Failed to append to conversation session: {e}")
                    
                    logger.info(f"✅ External API quiz generation complete")
                    
                    # 发送完成事件
                    yield {
                        "type": "done",
                        "thinking": None,
                        "content": parsed_content,
                        "content_type": content_type,
                        "usage_summary": {"external_api": True}
                    }
                    
                    logger.info(f"✅ Stream orchestration complete for {skill.id} (external API)")
                    return
                    
                except Exception as e:
                    logger.error(f"❌ External quiz API failed: {e}, falling back to LLM")
                    yield {
                        "type": "status",
                        "message": f"⚠️ 外部服务异常，使用 AI 生成..."
                    }
                    # 继续执行 LLM 流程作为 fallback
            
            # Step 5: 流式调用 LLM
            yield {
                "type": "status", 
                "message": "正在生成内容..."
            }
            
            thinking_accumulated = []
            content_accumulated = []
            usage_stats = {}  # 🆕 收集 token 使用统计
            
            # 🔄 重试机制：处理 API 连接中断
            max_retries = 2
            retry_count = 0
            api_error_occurred = False
            
            while retry_count <= max_retries:
                try:
                    if retry_count > 0:
                        yield {
                            "type": "status",
                            "message": f"连接中断，正在重试 ({retry_count}/{max_retries})..."
                        }
                        logger.warning(f"🔄 Retrying API call (attempt {retry_count}/{max_retries})")
                    
                    # 🔥 使用智能选择的 LLM 客户端
                    # 🆕 直接使用配置的 thinking_budget，不再强制提升到 64
                    optimized_budget = thinking_config.get("thinking_budget", 32)
                    
                    async for chunk in active_client.generate_stream(
                        prompt=prompt,
                        model=thinking_config["model"],
                        thinking_budget=optimized_budget,  # 使用优化后的 budget
                        buffer_size=1,
                        temperature=thinking_config.get("temperature", 1.0)
                    ):
                        # 累积数据
                        if chunk["type"] == "thinking":
                            thinking_accumulated.append(chunk.get("text", ""))
                        elif chunk["type"] == "content":
                            content_accumulated.append(chunk.get("text", ""))
                        elif chunk["type"] == "usage":
                            # 🆕 收集 token 使用统计
                            usage_stats = chunk.get("usage", {})
                            logger.info(f"📊 Collected usage stats: {usage_stats}")
                            continue  # 不转发给前端，仅内部使用
                        elif chunk["type"] == "done":
                            # 🔧 FIX: 不转发底层的 done 事件，由 orchestrator 发送自己的 done 事件
                            # 这样可以确保 content_type 被正确设置
                            logger.debug(f"📦 Received done from LLM client, will send orchestrator's done event")
                            continue
                        elif chunk["type"] == "error":
                            # API 返回的错误
                            api_error_occurred = True
                            yield chunk
                            break
                        
                        # 转发给前端
                        yield chunk
                    
                    # 成功完成，退出重试循环
                    if not api_error_occurred:
                        break
                    
                except Exception as e:
                    error_msg = str(e)
                    
                    # 检查是否是可重试的错误
                    is_retryable = (
                        "peer closed connection" in error_msg.lower() or
                        "incomplete chunked read" in error_msg.lower() or
                        "connection reset" in error_msg.lower() or
                        "timeout" in error_msg.lower()
                    )
                    
                    if is_retryable and retry_count < max_retries:
                        retry_count += 1
                        logger.warning(f"⚠️  Retryable error detected: {error_msg}")
                        # 清空之前的累积内容
                        thinking_accumulated = []
                        content_accumulated = []
                        continue
                    else:
                        # 不可重试或已达最大重试次数
                        logger.error(f"❌ Non-retryable error or max retries reached: {e}")
                        yield {
                            "type": "error",
                            "message": f"AI服务连接失败，请稍后重试 ({error_msg[:100]})",
                            "code": 503
                        }
                        return
                
                # 如果 API 返回了错误，也需要增加重试次数
                if api_error_occurred:
                    retry_count += 1
                    if retry_count > max_retries:
                        return  # 错误已经通过 chunk 发送给前端了
                    api_error_occurred = False
                    thinking_accumulated = []
                    content_accumulated = []
            
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
            
            # 🔧 Step 1: 清理常见格式问题（中文引号、trailing commas等）
            json_str = self._clean_json_string(json_str)
            
            # 🔧 Step 2: 修复 LaTeX 公式中的转义问题
            json_str = self._fix_latex_escapes(json_str)
            
            # 尝试解析 JSON
            try:
                parsed_content = json.loads(json_str)
                logger.info(f"✅ JSON parsed successfully")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse JSON: {e}")
                logger.error(f"Content preview: {json_str[:200]}...")
                logger.error(f"Content tail: ...{json_str[-100:]}")
                
                # 🔧 智能修复截断的 JSON
                if "Unterminated string" in str(e) or "Expecting" in str(e) or "truncated" in str(e).lower():
                    logger.warning(f"⚠️  JSON appears truncated at position {e.pos if hasattr(e, 'pos') else 'unknown'}, attempting smart fix...")
                    
                    # 策略 1: 智能检测并修复
                    parsed_content = self._smart_fix_truncated_json(json_str, e)
                    
                    if parsed_content:
                        logger.info(f"✅ JSON smart fixed successfully")
                    else:
                        # 策略 2: 暴力尝试各种闭合组合
                        fixed_attempts = [
                            json_str + '"}]}}',  # 字符串+数组+对象
                            json_str + '"}}',    # 字符串+对象
                            json_str + '"]}}',   # 数组+对象
                            json_str + '}]}}',   # 对象+数组+对象
                            json_str + '}}',     # 对象
                            json_str + ']}}',    # 数组+对象
                            json_str + ']}'      # 数组+对象
                        ]
                        
                        for i, attempt in enumerate(fixed_attempts):
                            try:
                                parsed_content = json.loads(attempt)
                                logger.info(f"✅ JSON fixed (brute force attempt {i+1})")
                                break
                            except:
                                continue
                        else:
                            # 所有尝试都失败 - 返回友好错误
                            yield {
                                "type": "error",
                                "message": "生成内容被意外中断（API连接问题），请稍后重试",
                                "code": 503
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
            elif "cardList" in parsed_content or "flashcard_set_id" in parsed_content or "cards" in parsed_content:
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
            
            # 🆕 提取实际 topic
            actual_topic_llm = self._extract_topic_from_result(parsed_content, intent_result.topic)
            if actual_topic_llm:
                intent_result.topic = actual_topic_llm
            
            # Step 9: 追加到 Conversation Session MD 文件
            try:
                session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
                await session_mgr.start_or_continue_session(intent_result.raw_text, session_id=session_id)
                
                await session_mgr.append_turn({
                    "user_query": intent_result.raw_text,
                    "agent_response": {
                        "skill": skill.id,
                        "artifact_id": parsed_content.get("artifact_id", ""),
                        "content": parsed_content,
                        "topic": actual_topic_llm  # 🆕 实际 topic
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
            
            # 🆕 输出详细的 Token 使用汇总
            logger.info(f"\n{'='*70}")
            logger.info(f"📊 REQUEST TOKEN USAGE SUMMARY")
            logger.info(f"{'='*70}")
            logger.info(f"🎯 Skill: {skill.id} ({skill.display_name})")
            logger.info(f"📚 Topic: {intent_result.topic}")
            logger.info(f"🤖 Model: {thinking_config.get('model', 'unknown')}")
            logger.info(f"{'─'*70}")
            
            # Intent Router (0 tokens - local matching)
            logger.info(f"1️⃣  Intent Router:        0 tokens (local skill registry match)")
            
            # Main LLM Generation
            model_name = usage_stats.get('model', thinking_config.get('model', 'unknown')) if usage_stats else 'unknown'
            is_gemini = 'gemini' in model_name.lower()
            llm_label = "Gemini" if is_gemini else "Kimi"
            
            if usage_stats:
                source = usage_stats.get('source', 'unknown')
                gen_time = usage_stats.get('generation_time', 0)
                
                if source == 'api':
                    # 精确数据（来自 API）
                    prompt_tokens = usage_stats.get('prompt_tokens', 0)
                    completion_tokens = usage_stats.get('completion_tokens', 0)
                    total_tokens = usage_stats.get('total_tokens', 0)
                    logger.info(f"2️⃣  Main Generation ({llm_label}) [EXACT]:")
                    logger.info(f"    • Input:    {prompt_tokens:,} tokens")
                    logger.info(f"    • Output:   {completion_tokens:,} tokens")
                    logger.info(f"    • Total:    {total_tokens:,} tokens")
                    if gen_time > 0:
                        logger.info(f"    • Time:     {gen_time:.1f}s")
                    main_total = total_tokens
                elif source == 'estimated':
                    # 估算数据（Gemini 流式 fallback）
                    thinking_chars = usage_stats.get('thinking_chars', 0)
                    content_chars = usage_stats.get('content_chars', 0)
                    completion_tokens = usage_stats.get('completion_tokens', 0)
                    # Gemini Flash prompt 通常较小（skill prompt ~500 + context ~500）
                    estimated_input = 1000
                    total_estimated = estimated_input + completion_tokens
                    logger.info(f"2️⃣  Main Generation ({llm_label}) [ESTIMATED]:")
                    logger.info(f"    • Input:    ~{estimated_input:,} tokens (prompt)")
                    logger.info(f"    • Output:   ~{completion_tokens:,} tokens (from {content_chars} chars)")
                    logger.info(f"    • Total:    ~{total_estimated:,} tokens")
                    main_total = total_estimated
                else:
                    # gemini_stream 格式（只有 chars）
                    thinking_chars = usage_stats.get('thinking_chars', 0)
                    content_chars = usage_stats.get('content_chars', 0)
                    # 估算 tokens（中文约 0.5 token/char，JSON 约 0.3 token/char）
                    estimated_output = int((thinking_chars + content_chars) * 0.4)
                    # Gemini Flash prompt 通常较小（skill prompt ~500 + context ~500）
                    estimated_input = 1000
                    total_estimated = estimated_input + estimated_output
                    logger.info(f"2️⃣  Main Generation ({llm_label}) [ESTIMATED]:")
                    logger.info(f"    • Input:    ~{estimated_input:,} tokens (prompt)")
                    logger.info(f"    • Output:   ~{estimated_output:,} tokens (from {content_chars} chars)")
                    logger.info(f"    • Total:    ~{total_estimated:,} tokens")
                    if gen_time > 0:
                        logger.info(f"    • Time:     {gen_time:.1f}s")
                    main_total = total_estimated
            else:
                logger.info(f"2️⃣  Main Generation ({llm_label}): No usage stats available")
                main_total = 0
            
            # Background compression (conditional based on artifact size)
            # 🆕 只有 artifact > 2500 chars 时才触发 LLM 压缩
            content_size = len(json.dumps(parsed_content, ensure_ascii=False)) if parsed_content else 0
            
            # 始终使用 Gemini 压缩（异步后台执行）
            # Gemini 2.0 Flash Exp 压缩成本：~500-800 tokens ≈ $0.0001/次
            compression_estimate = 600  # Gemini 压缩请求的平均 token 消耗
            estimated_compressed = int(content_size * 0.25)  # 约压缩到 25%
            logger.info(f"3️⃣  Context Compress:     ~{compression_estimate:,} tokens (Gemini async, {content_size} → ~{estimated_compressed} chars)")
            logger.info(f"{'─'*70}")
            
            # Total estimate
            total_estimated = main_total + compression_estimate
            logger.info(f"📈 TOTAL FOR THIS REQUEST: ~{total_estimated:,} tokens")
            logger.info(f"{'='*70}\n")
            
            # 完成
            yield {
                "type": "done",
                "thinking": full_thinking,
                "content": parsed_content,
                "content_type": content_type,
                "usage_summary": usage_stats  # 🆕 包含使用统计
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
        
        # ============= Phase -1: 处理 Skill Registry 的 clarification_needed =============
        
        if intent_result.intent == "clarification_needed":
            reason = intent_result.parameters.get('clarification_reason')
            logger.warning(f"⚠️  Clarification needed: {reason}")
            
            if reason == "topic_missing":
                # Topic 缺失，需要用户提供
                # 检查历史 topics
                session_context = await self.memory_manager.get_session_context(session_id)
                recent_topics = []
                if session_context and session_context.artifact_history:
                    recent_topics = [a.topic for a in session_context.artifact_history[-5:] if a.topic]  # 最近5个topics
                
                if recent_topics:
                    # 有历史 topics，让用户选择
                    return {
                        "content_type": "clarification_needed",
                        "intent": "clarification",
                        "response_content": {
                            "question": "您想基于以下哪个主题继续？",
                            "reason": "topic_missing",
                            "options": [
                                {
                                    "type": "topic",
                                    "label": topic,
                                    "value": topic,
                                    "icon": "📚",
                                    "description": f"继续学习：{topic}"
                                }
                                for topic in recent_topics
                            ],
                            "allow_custom_input": True,
                            "custom_input_placeholder": "或输入新的学习主题..."
                        }
                    }
                else:
                    # 没有历史 topics，请求用户输入
                    return {
                        "content_type": "clarification_needed",
                        "intent": "clarification",
                        "response_content": {
                            "question": "请问您想学习什么主题？",
                            "reason": "topic_missing",
                            "options": [],
                            "allow_custom_input": True,
                            "custom_input_placeholder": "例如：光合作用、二战历史、微积分..."
                        }
                    }
            
            elif reason == "multi_topic_insufficient":
                # 用户请求多个 topics，但历史不足
                return {
                    "content_type": "clarification_needed",
                    "intent": "clarification",
                    "response_content": {
                        "question": "您提到了多个主题，但我暂时只记录了一个主题。可以告诉我具体是哪些主题吗？",
                        "reason": "multi_topic_insufficient",
                        "options": [],
                        "allow_custom_input": True,
                        "custom_input_placeholder": "例如：光合作用和二战历史"
                    }
                }
        
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
            
            # 🆕 检查是否有文件附件（有文件时跳过onboarding）
            has_file_uri = bool(intent_result.parameters.get('file_uri'))
            
            # 🆕 对于 learning_bundle，检查原始消息是否有具体主题
            # 例如 "帮我制定学习计划，主题是光合作用" 应该直接执行
            raw_text = intent_result.raw_text or ""
            has_explicit_topic_in_message = any(kw in raw_text for kw in ['主题是', '关于', '学习', '计划'])
            
            # 🆕 首次访问 + 无明确topic + 无文件：提供onboarding引导（0 token消耗）
            # 跳过条件：有文件、有明确主题指定、或是 learning_bundle 且消息中有明确主题
            skip_onboarding = has_file_uri or (intent_result.intent == "learning_bundle" and has_explicit_topic_in_message)
            
            if len(artifact_history) == 0 and not topic_is_valid and not skip_onboarding:
                logger.info(f"👋 First-time user detected, showing onboarding (0 tokens)")
                
                # 🆕 获取语言设置
                language = additional_params.get("language", "en") if additional_params else "en"
                
                if language == "en":
                    return {
                        "content_type": "onboarding",
                        "intent": intent_result.intent,
                        "response_content": {
                            "welcome": "👋 Welcome to StudyX Agent!",
                            "message": "I noticed you haven't started learning any topic yet.",
                            "suggestions": [
                                {
                                    "category": "Physics",
                                    "topics": ["Newton's Laws", "Optics", "Electromagnetism", "Quantum Mechanics"],
                                    "icon": "⚛️"
                                },
                                {
                                    "category": "Math",
                                    "topics": ["Calculus", "Linear Algebra", "Probability", "Statistics"],
                                    "icon": "📐"
                                },
                                {
                                    "category": "History",
                                    "topics": ["World War II", "Renaissance", "Industrial Revolution", "Ancient Civilizations"],
                                    "icon": "📜"
                                },
                                {
                                    "category": "Biology",
                                    "topics": ["Photosynthesis", "Cell Structure", "Genetics", "Evolution"],
                                    "icon": "🧬"
                                },
                                {
                                    "category": "Computer Science",
                                    "topics": ["Data Structures", "Algorithms", "Machine Learning", "Networking"],
                                    "icon": "💻"
                                }
                            ],
                            "call_to_action": "Please tell me what topic you'd like to learn, for example: 'Explain Newton's second law' or 'What is photosynthesis?'"
                        }
                    }
                else:
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
            
            # 🆕 多主题澄清：仅在用户请求非常模糊时触发
            # 条件：1) 没有文件附件  2) 消息中没有明确指定主题
            if len(artifact_history) > 0 and not has_file_uri:
                # 检查消息中是否包含任何明确的主题词汇
                message_lower = intent_result.raw_text.lower()
                
                # 模糊请求模式（如 "再来三道题"、"继续"）
                vague_patterns = ['再来', '继续', '更多', '还要', '再给', '多来', '再出']
                is_vague_request = any(p in message_lower for p in vague_patterns) and len(message_lower) < 15
                
                # 提取最近的主题列表（去重）
                recent_topics = await self._extract_recent_topics(session_id)
                unique_topics = list(dict.fromkeys(recent_topics))  # 去重但保持顺序
                
                # 检查用户消息是否明确提到了某个主题
                has_explicit_topic = any(topic.lower() in message_lower for topic in unique_topics if topic)
                
                # 🔥 关键：当请求模糊 + 有多个不同主题 + 没有明确指定主题时，触发澄清
                # 即使 topic_is_valid 为 True（从 current_topic 继承），也要澄清
                if is_vague_request and len(unique_topics) >= 2 and not has_explicit_topic:
                    logger.info(f"❓ Vague request with {len(unique_topics)} unique topics: {unique_topics}")
                    logger.info(f"🤔 Multi-topic clarification needed (even though current_topic is set)")
                    
                    return {
                        "content_type": "clarification_needed",
                        "intent": intent_result.intent,
                        "topic": intent_result.topic,  # 保留当前 topic 供参考
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
                                for topic in unique_topics[:5]  # 最多5个选项
                            ],
                            "allow_custom_input": True,
                            "custom_input_placeholder": "或者输入新的主题...",
                            "original_intent": intent_result.intent,
                            "original_message": intent_result.raw_text
                        }
                    }
            
            # 🆕 当有有效 topic 时，不再触发澄清 - 直接使用该 topic
            # 用户明确指定的 topic 或 file_uri 会绕过澄清逻辑
            # 删除了旧的 "Ambiguous request with N topics" 逻辑，因为它过于激进
            
            # 多主题澄清：只有当 topic 完全无效、没有文件附件、且请求模糊时才触发
            # 🆕 增加更严格的条件：只有极端模糊的请求才需要澄清
            if not topic_is_valid and len(artifact_history) > 1 and not has_file_uri:
                # 检查是否是极端模糊的请求（只有动作没有任何内容）
                message_lower = intent_result.raw_text.lower()
                extreme_vague_patterns = ['再来', '继续', '更多', '还要', '再给', '多来', '出题', '给我']
                is_extreme_vague = len(message_lower) < 10 and any(p in message_lower for p in extreme_vague_patterns)
                
                if is_extreme_vague:
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
                    
                    if len(learned_topics) >= 2:  # 🆕 至少2个不同主题才澄清
                        logger.info(f"💬 Extreme vague request with {len(learned_topics)} topic(s), asking user (0 tokens)")
                        
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
            
            # 🆕 首先检查用户消息的意图类型
            # 询问类消息应该转换为 explain/other，而不是生成新内容
            user_message = intent_result.raw_text.lower()
            
            # 询问/解释请求模式（扩展覆盖更多场景）
            inquiry_patterns = [
                # 理解/澄清类
                "不太理解", "不理解", "不太懂", "不懂", "不明白", "不清楚",
                "能解释", "帮我解释", "详细解释", "更简单", "简单一点",
                "什么意思", "怎么理解", "举个例子", "能举例",
                # 描述/介绍类
                "讲了什么", "说了什么", "是什么", "什么内容", "描述一下", "介绍一下",
                "讲的是什么", "说的是什么", "内容是什么",
                # 比较/分析类
                "比较", "对比", "不同", "区别", "联系", "关系", "相同", "相似",
                # 提问/请求帮助类
                "怎么做", "如何做", "帮我解答", "帮我解决", "有什么",
                "给我一些", "给点", "提示", "思路", "方向",
                # 总结/概述类（不是要求生成笔记）
                "总体来说", "总的来说", "概括一下", "简单说说"
            ]
            
            # 生成请求模式（明确要求生成新内容）
            generate_patterns = [
                "再来", "再出", "再给", "多出", "继续出", "还要",
                "更多题", "更多闪卡", "更多卡片",
                "帮我出", "给我出", "出几道", "生成", "创建"
            ]
            
            is_inquiry_request = any(p in user_message for p in inquiry_patterns)
            is_generate_request = any(p in user_message for p in generate_patterns)
            
            if is_inquiry_request and not is_generate_request:
                # 用户在请求询问/解释，不是生成新内容
                # 返回一个特殊标记，让 external.py 使用 Gemini 处理
                logger.info(f"🔍 Detected inquiry request in contextual message, redirecting to 'other' intent")
                return {
                    "content_type": "redirect_to_other",
                    "intent": "other",
                    "topic": session_context.current_topic if session_context else "",
                    "content": {},
                    "redirect": True,
                    "original_message": intent_result.raw_text
                }
            
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
        
        # 🆕 Step 3.1: 引用解析（如果消息包含对历史 artifacts 的引用）
        if intent_result.has_reference:
            reference_resolver = get_reference_resolver()
            session_context_for_ref = await self.memory_manager.get_session_context(session_id)
            
            if session_context_for_ref and session_context_for_ref.artifact_history:
                resolved_refs = reference_resolver.resolve_references(
                    intent_result.raw_text,
                    session_context_for_ref.artifact_history
                )
                
                if resolved_refs:
                    resolved_content = reference_resolver.format_resolved_content(resolved_refs)
                    if resolved_content:
                        params["referenced_content"] = resolved_content
                        logger.info(f"🔗 Resolved {len(resolved_refs)} reference(s): {len(resolved_content)} chars")
                        
                        # 使用来源 artifact 的 topic
                        for ref in resolved_refs:
                            if ref.source_topic:
                                intent_result.topic = ref.source_topic
                                logger.info(f"🔗 Using source topic from reference: {ref.source_topic}")
                                break
                    else:
                        logger.warning(f"⚠️  References detected but no content resolved")
                else:
                    logger.warning(f"⚠️  has_reference=True but resolve_references returned empty")
            else:
                logger.warning(f"⚠️  has_reference=True but no artifact_history available")
        
        # 🆕 Step 3.5: 智能选择思考模式
        session_context = await self.memory_manager.get_session_context(session_id)
        thinking_config = self.thinking_mode_selector.select_mode(
            intent_result=intent_result,
            session_context=session_context
        )
        
        # 🔧 临时配置：全部使用 Gemini（关闭 Kimi）
        active_client = GeminiClient()
        logger.info(f"⚡ Using Gemini: {thinking_config['reasoning']}")
        
        # Step 4: 执行技能
        try:
            response = await self._execute_skill(skill, params, context, 
                                                 client=active_client, 
                                                 thinking_config=thinking_config)
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
        
        # 🆕 Step 5: 提取实际 topic 并更新 intent_result
        # 这样 API 响应和 MD 文件中存储的 topic 是实际的，而不是从用户消息提取的
        actual_topic = self._extract_topic_from_result(result, intent_result.topic)
        if actual_topic and actual_topic != intent_result.topic:
            logger.info(f"📤 Updating intent_result.topic: '{intent_result.topic}' → '{actual_topic}'")
            intent_result.topic = actual_topic
        
        # Step 5.5: 封装输出（传入更新后的 intent_result）
        output = self._wrap_output(skill, result, intent_result)
        
        # 🆕 添加 topic 到输出
        output["topic"] = actual_topic or intent_result.topic or ""
        
        # Step 6: 更新记忆（异步，不阻塞）
        await self._update_memory(user_id, session_id, intent_result, result)
        
        # Step 7: 追加到 Conversation Session MD 文件
        try:
            session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
            await session_mgr.start_or_continue_session(intent_result.raw_text, session_id=session_id)
            
            await session_mgr.append_turn({
                "user_query": intent_result.raw_text,
                "agent_response": {
                    "skill": skill.id,
                    "artifact_id": result.get("artifact_id", ""),
                    "content": result,
                    "topic": actual_topic  # 🆕 直接传递实际 topic
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
        
        # 🆕 添加 usage_summary 到输出（供外部 API 统计）
        # 确保包含模型信息
        usage_summary = usage.copy() if usage else {}
        if not usage_summary.get("model"):
            usage_summary["model"] = thinking_config.get("model", "unknown")
        if "thinking_mode" not in usage_summary:
            usage_summary["thinking_mode"] = thinking_config.get("mode") == "real_thinking"
        output["usage_summary"] = usage_summary
        
        logger.info(f"✅ Orchestration complete for {skill.id}")
        return output
    
    async def _handle_chat_stream(
        self,
        intent_result: IntentResult,
        user_id: str,
        session_id: str
    ):
        """
        🆕 处理普通对话的流式响应（intent=other）
        
        Args:
            intent_result: 意图识别结果
            user_id: 用户 ID
            session_id: 会话 ID
            
        Yields:
            流式响应事件
        """
        logger.info(f"💬 Starting chat stream for user {user_id}")
        
        # 加载对话历史（简化版，直接获取最近的 turns 文本）
        session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
        conversation_context = ""
        
        try:
            await session_mgr.start_or_continue_session(intent_result.raw_text, session_id=session_id)
            # 获取最近 3 轮对话的 Markdown 文本
            conversation_context = await session_mgr.get_recent_turns(num_turns=3)
        except Exception as e:
            logger.warning(f"⚠️ Failed to load conversation history: {e}")
        
        # 构建 prompt（将 system instruction 和对话历史合并到 prompt）
        system_prompt = """你是一个友好的学习助手。请用简洁清晰的语言回答用户的问题。
如果用户问的是学习相关的问题，提供有帮助的信息。
如果用户只是打招呼或闲聊，友好地回应并引导他们开始学习。
回复使用中文。"""
        
        # 构建完整的 prompt（包含历史）
        full_prompt = f"{system_prompt}\n\n"
        if conversation_context:
            full_prompt += f"对话历史：\n{conversation_context}\n\n"
        full_prompt += f"用户: {intent_result.raw_text}\n助手:"
        
        # 使用 Gemini 生成响应
        full_response = ""
        
        try:
            yield {"type": "status", "message": "正在思考..."}
            
            async for chunk in self.gemini_client.generate_stream(
                prompt=full_prompt,
                model="gemini-2.5-flash",
                thinking_budget=0,  # 🔧 禁用思考以确保完整输出
                buffer_size=5,
                temperature=0.7
            ):
                if chunk.get("type") == "content":
                    content = chunk.get("content", "")
                    full_response += content
                    yield {
                        "type": "content",
                        "content": content,
                        "accumulated": full_response
                    }
                elif chunk.get("type") == "error":
                    # 流式生成出错
                    error_msg = chunk.get("message", "生成失败")
                    logger.error(f"❌ Stream generation error: {error_msg}")
                    full_response = f"抱歉，我暂时无法回复。请稍后再试。"
                    yield {
                        "type": "content",
                        "content": full_response,
                        "accumulated": full_response
                    }
            
            # 如果响应为空，提供一个默认回复
            if not full_response:
                full_response = "你好！有什么我可以帮助你的吗？"
            
            # 发送完成事件
            yield {
                "type": "done",
                "content_type": "text",
                "content": {"text": full_response},
                "intent": "other"
            }
            
            # 保存到会话历史
            try:
                from datetime import datetime
                await session_mgr.append_turn({
                    "user_query": intent_result.raw_text,
                    "agent_response": {
                        "skill": "chat",
                        "artifact_id": "",
                        "content": {"text": full_response}
                    },
                    "response_type": "text",  # 🆕 添加必需的 response_type 字段
                    "metadata": {
                        "model": "gemini-2.5-flash",
                        "source": "chat_stream"
                    },
                    "timestamp": datetime.now(),  # 🆕 改为 datetime 对象
                    "intent": {
                        "intent": "other",
                        "topic": intent_result.topic
                    }
                })
            except Exception as e:
                logger.warning(f"⚠️ Failed to save chat turn: {e}")
                
        except Exception as e:
            logger.error(f"❌ Chat stream error: {e}")
            yield {
                "type": "error",
                "message": f"对话生成失败: {str(e)}"
            }
    
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
    
    def _clean_json_string(self, json_str: str) -> str:
        """
        全面清理 JSON 字符串，修复常见格式问题
        
        修复：
        1. 中文引号 → 英文引号
        2. 多余的逗号（trailing commas）
        3. 缺少的逗号
        4. 其他格式问题
        
        Args:
            json_str: JSON 字符串
        
        Returns:
            清理后的 JSON 字符串
        """
        # 1. 修复中文引号
        json_str = json_str.replace('"', '"').replace('"', '"')
        json_str = json_str.replace(''', "'").replace(''', "'")
        
        # 2. 修复 trailing commas (对象结尾)
        import re
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*\]', ']', json_str)
        
        # 3. 修复多个连续逗号
        json_str = re.sub(r',\s*,', ',', json_str)
        
        return json_str
    
    def _fix_latex_escapes(self, json_str: str) -> str:
        """
        修复 JSON 字符串中 LaTeX 公式的转义问题
        
        LaTeX 公式中的反斜杠（如 \vec, \frac）在 JSON 字符串中需要转义为 \\
        问题：LLM 生成的 JSON 中，LaTeX 命令如 \vec 没有转义，导致 JSON 解析失败
        
        策略：逐字符扫描，找到字符串值中的 LaTeX 命令并转义
        
        Args:
            json_str: JSON 字符串
        
        Returns:
            修复后的 JSON 字符串
        """
        import re
        
        # 匹配 JSON 字符串值（"..."），包括转义的引号和反斜杠
        def fix_string_with_latex(match):
            """修复字符串值中的 LaTeX 转义"""
            full_match = match.group(0)
            content = match.group(1)  # 字符串内容（不包括引号）
            
            # 如果内容中不包含 $，说明可能没有 LaTeX，直接返回
            if '$' not in content:
                return full_match
            
            # 逐字符处理，修复 LaTeX 命令
            result = []
            i = 0
            while i < len(content):
                char = content[i]
                
                # 如果遇到反斜杠
                if char == '\\':
                    # 检查下一个字符
                    if i + 1 < len(content):
                        next_char = content[i + 1]
                        
                        # 如果下一个字符是字母（LaTeX 命令），需要转义
                        if next_char.isalpha():
                            # 检查前面是否已经是转义的反斜杠
                            # 在原始字符串中，如果前一个字符也是 \，说明已经是转义的
                            if i > 0 and content[i - 1] == '\\':
                                # 已经是转义的（在原始字符串中是 \\），保持不变
                                result.append(char)
                                result.append(next_char)
                            else:
                                # 需要转义：添加额外的反斜杠
                                # 在 JSON 字符串中，\\ 表示单个反斜杠
                                result.append('\\\\')
                                result.append(next_char)
                            i += 2
                            continue
                        else:
                            # 不是 LaTeX 命令（可能是转义序列如 \n, \t），保持原样
                            result.append(char)
                            result.append(next_char)
                            i += 2
                            continue
                    else:
                        # 反斜杠在末尾，保持原样
                        result.append(char)
                else:
                    result.append(char)
                
                i += 1
            
            fixed_content = ''.join(result)
            return f'"{fixed_content}"'
        
        # 匹配 JSON 字符串值（包括转义的引号）
        # 模式：匹配 "..." 中的内容，处理转义的字符
        pattern = r'"((?:[^"\\]|\\.)*)"'
        
        fixed_json = re.sub(pattern, fix_string_with_latex, json_str)
        
        return fixed_json
    
    def _smart_fix_truncated_json(
        self,
        json_str: str,
        error: json.JSONDecodeError
    ) -> Optional[Dict[str, Any]]:
        """
        智能修复截断的 JSON
        
        策略：
        1. 找到最后一个完整的字段
        2. 检测当前在什么结构中（对象、数组、字符串）
        3. 智能添加闭合符号
        
        Args:
            json_str: 截断的 JSON 字符串
            error: JSON 解析错误
        
        Returns:
            修复后的 dict 或 None
        """
        try:
            # 计算需要的闭合符号
            open_braces = json_str.count('{')
            close_braces = json_str.count('}')
            open_brackets = json_str.count('[')
            close_brackets = json_str.count(']')
            
            # 计算未闭合的引号（字符串）
            in_string = False
            escape_next = False
            for char in json_str:
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
            
            # 构建修复字符串
            fix = ""
            
            # 如果在字符串内被截断
            if in_string:
                fix += '"'
            
            # 关闭未闭合的数组
            for _ in range(open_brackets - close_brackets):
                fix += ']'
            
            # 关闭未闭合的对象
            for _ in range(open_braces - close_braces):
                fix += '}'
            
            # 尝试修复
            fixed_json = json_str + fix
            parsed = json.loads(fixed_json)
            
            logger.info(f"🔧 Smart fix applied: added {repr(fix)}")
            return parsed
        
        except Exception as e:
            logger.debug(f"Smart fix failed: {e}")
            return None
    
    async def _build_context(
        self,
        skill: SkillDefinition,
        user_id: str,
        session_id: str
    ) -> Dict[str, Any]:
        """
        🆕 构建技能执行所需的上下文（智能加载）
        
        包括：
        1. 用户画像和会话上下文
        2. 最近的 artifacts（用于上下文连续性）
        3. Memory summary（行为总结）
        4. 🆕 Conversation Session Context（长期记忆，智能压缩）
        
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
                    # 🔍 调试：查看 artifact_history 内容
                    logger.info(f"🔍 Total artifacts in history: {len(session_context.artifact_history)}")
                    for idx, record in enumerate(session_context.artifact_history):
                        logger.debug(f"  [{idx}] {record.artifact_id[:50]}... | {record.topic} | {len(str(record.content)) if record.content else 0} chars")
                    
                    # 获取最近的 2 个 artifact records (限制为2避免prompt过大)
                    recent_artifact_records = session_context.artifact_history[-2:]
                    
                    for artifact_record in recent_artifact_records:
                        # 🆕 使用 summary（压缩摘要）作为 LLM 上下文
                        # content 保留原始完整数据，供 reference_resolver 使用
                        summary_str = artifact_record.summary if artifact_record.summary else ""
                        summary_size = len(summary_str)
                        
                        if summary_str:
                            recent_artifacts.append({
                                "artifact_id": artifact_record.artifact_id,
                                "topic": artifact_record.topic,
                                "type": artifact_record.artifact_type,
                                "summary": artifact_record.summary,  # 用于 LLM 上下文
                                # 🆕 不再传 content 给 LLM（太大），只传 summary
                            })
                            logger.info(f"📄 Loaded artifact: {artifact_record.topic} ({artifact_record.artifact_type}, {summary_size} chars)")
                        else:
                            logger.warning(f"⚠️  Artifact {artifact_record.artifact_id} has no summary")
                
                context["recent_artifacts"] = recent_artifacts
                logger.info(f"📚 Loaded {len(recent_artifacts)} recent artifacts for context")
                
            except Exception as e:
                logger.warning(f"⚠️  Failed to load recent artifacts: {e}")
                context["recent_artifacts"] = []
        
        # 🆕 加载 Conversation Session Context（长期记忆 + 智能压缩）
        try:
            session_mgr = self.memory_manager.get_conversation_session_manager(user_id)
            
            # 获取智能构建的 session context（包含继承 + 最近对话）
            conversation_context = await session_mgr.get_session_context_for_llm(
                include_recent_turns=5,  # 最近 5 轮
                include_inherited=True   # 包含继承的 summary
            )
            
            if conversation_context:
                context["conversation_history"] = conversation_context
                logger.debug(f"🗂️  Loaded conversation session context ({len(conversation_context)} chars)")
            else:
                context["conversation_history"] = ""
                logger.debug("🗂️  No conversation history available")
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to load conversation session context: {e}")
            context["conversation_history"] = ""
        
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
            "memory_summary": memory_summary.recent_behavior,  # 🔧 使用 generate_memory_summary 结果
            "language": additional_params.get("language", "auto") if additional_params else "auto"  # 🆕 传递语言偏好
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
        session_context: Any,
        step_index: int = 1  # 🆕 步骤索引，用于智能选择 thinking 模式
    ):
        """
        🆕 流式执行单个skill（用于Plan Skill的每个步骤）
        
        Args:
            skill_id: Skill ID
            input_params: 输入参数
            user_profile: 用户画像
            session_context: 会话上下文
            step_index: 步骤索引（1=第一步，2+=后续步骤）
        
        Thinking 模式选择逻辑：
            - 第一步 (explain_skill) → 真思考 (Kimi)，深度理解核心概念
            - 后续步骤 (flashcard/quiz/notes/mindmap) → 伪思考 (Gemini)，快速生成
        
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
        
        # 🔥 智能选择 Thinking 模式
        # 
        # 判断条件：
        # 1. 第一步 (step_index == 1) 且 session 中没有该 topic 的 artifact → 真思考
        # 2. 后续步骤或已有上下文 → 伪思考
        #
        # 这样无论 Plan Skill 的步骤顺序如何（可能是 flashcard + quiz，没有 explain），
        # 第一步都会用真思考来理解 topic，后续步骤用伪思考基于已有内容快速生成
        
        # 检查 session 中是否已有该 topic 的 artifact
        topic = input_params.get("topic", "")
        has_existing_context = False
        if session_context and hasattr(session_context, 'artifact_history'):
            for artifact in session_context.artifact_history:
                if artifact.topic == topic:
                    has_existing_context = True
                    break
        
        # 🔧 临时配置：全部使用 Gemini（关闭 Kimi）
        
        thinking_accumulated = []
        content_accumulated = []
        
        # ⚡ 全部使用 Gemini（快速稳定）
        logger.info(f"⚡ Executing sub-skill: {skill_id} (Step {step_index}, topic='{topic}' → Gemini)")
        
        async for chunk in self.gemini_client.generate_stream(
            prompt=full_prompt,
            model="gemini-2.5-flash",
            thinking_budget=0,  # 🔧 禁用思考以确保完整输出
            buffer_size=1,
            temperature=getattr(skill, 'temperature', 0.7)
        ):
            # 累积数据
            if chunk["type"] == "thinking":
                thinking_accumulated.append(chunk.get("text", ""))
            elif chunk["type"] == "content":
                content_accumulated.append(chunk.get("text", ""))
            
            # 🔥 转发 chunk（跳过 LLM 客户端的 done 事件，我们自己构建）
            if chunk["type"] != "done":
                yield chunk
        
        # 解析最终结果
        full_thinking = "".join(thinking_accumulated)
        full_content = "".join(content_accumulated)
        
        # 🔥 检查是否有实际内容（LLM 可能把所有 token 花在 thinking 上）
        if not full_content or len(full_content.strip()) < 10:
            logger.error(f"❌ No content generated (content: {len(full_content)} chars, thinking: {len(full_thinking)} chars)")
            yield {
                "type": "error",
                "message": "LLM 生成内容为空（可能 thinking 消耗了所有 token），请重试"
            }
            return
        
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
        
        # 🔧 Step 1: 清理常见格式问题
        json_str = self._clean_json_string(json_str)
        
        # 🔧 Step 2: 修复 LaTeX 公式中的转义问题
        json_str = self._fix_latex_escapes(json_str)
        
        # 解析JSON
        parsed_content = None
        try:
            parsed_content = json.loads(json_str)
            logger.info(f"✅ JSON parsed successfully (sub-skill)")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse JSON: {e}")
            logger.error(f"Content preview: {json_str[:200]}...")
            
            # 🔧 智能修复截断的 JSON
            if "Unterminated string" in str(e) or "Expecting" in str(e):
                logger.warning(f"⚠️  JSON appears malformed, attempting smart fix...")
                
                # 策略 1: 智能检测并修复
                parsed_content = self._smart_fix_truncated_json(json_str, e)
                
                # 策略 2: 暴力修复（如果智能修复失败）
                if parsed_content is None:
                    logger.warning(f"⚠️  Smart fix failed, trying brute force...")
                    fixed_attempts = [
                        json_str + '"}',       # 缺少引号和花括号
                        json_str + '"]}}',     # 数组+对象
                        json_str + '"}}',      # 字符串+对象
                        json_str + '}}',       # 对象
                        json_str + ']}}',      # 数组+对象
                    ]
                    
                    for i, attempt in enumerate(fixed_attempts):
                        try:
                            parsed_content = json.loads(attempt)
                            logger.info(f"✅ JSON fixed (brute force attempt {i+1})")
                            break
                        except:
                            continue
            
            if parsed_content is None:
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
        elif "cardList" in parsed_content or "card_set_id" in parsed_content or "cards" in parsed_content:
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
        context: Dict[str, Any],
        client: Optional[Any] = None,
        thinking_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行技能 - 🆕 支持智能思考模式选择
        
        Args:
            skill: Skill 定义
            params: 输入参数
            context: 上下文
            client: LLM 客户端（可选，如果未提供则使用默认）
            thinking_config: 思考模式配置（可选）
        
        Returns:
            Dict[str, Any]: 包含以下键：
                - "content": 生成的内容
                - "thinking": 思考过程（如果有）
                - "usage": Token 使用统计
        """
        # 🔥 flashcard_skill 特殊处理：调用外部 API（带 fallback）
        if skill.id == 'flashcard_skill':
            try:
                result = await self._execute_flashcard_via_external_api(params, context)
                # 检查是否有错误
                content = json.loads(result.get("content", "{}"))
                if not content.get("error"):
                    return result
                logger.warning(f"⚠️ External flashcard API returned error, falling back to LLM")
            except Exception as e:
                logger.warning(f"⚠️ External flashcard API failed: {e}, falling back to LLM")
            # Fallback: 继续执行 LLM 流程
        
        # 🔥 quiz_skill 特殊处理：调用外部 API（带 fallback）
        if skill.id == 'quiz_skill':
            try:
                result = await self._execute_quiz_via_external_api(params, context)
                # 检查是否有错误
                content = json.loads(result.get("content", "{}"))
                if not content.get("error"):
                    return result
                logger.warning(f"⚠️ External quiz API returned error, falling back to LLM")
            except Exception as e:
                logger.warning(f"⚠️ External quiz API failed: {e}, falling back to LLM")
            # Fallback: 继续执行 LLM 流程
        
        # 加载 prompt 模板
        prompt_content = self._load_prompt(skill)
        
        # 构建完整 prompt
        full_prompt = self._format_prompt(prompt_content, params, context)
        
        # 🆕 使用提供的客户端或默认客户端
        active_client = client or self.llm_client
        
        # 🆕 使用思考配置或默认配置
        if thinking_config:
            model = thinking_config["model"]
            thinking_budget = thinking_config.get("thinking_budget")
            temperature = thinking_config.get("temperature", 1.0)
        else:
            model = skill.models.get("primary", self.llm_client.model)
            thinking_budget = skill.thinking_budget or 32
            temperature = getattr(skill, 'temperature', 1.0)
        
        # 🆕 从 params 获取 max_tokens，默认 4000（避免复杂回答被截断）
        max_tokens = params.get('max_tokens', 4000)
        
        logger.debug(f"🤖 Calling LLM: {model} (thinking_budget={thinking_budget}, temp={temperature}, max_tokens={max_tokens})")
        
        # 🆕 使用 generate 方法（返回字典）
        response = await active_client.generate(
            prompt=full_prompt,
            model=model,
            response_format="json",
            thinking_budget=thinking_budget,
            return_thinking=True,
            temperature=temperature,
            max_tokens=max_tokens  # 🆕 增加 token 限制，避免截断
        )
        
        # response 是字典: {"content": str, "thinking": str, "usage": dict}
        return response
    
    async def _execute_flashcard_via_external_api(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        🔥 通过外部 API 生成闪卡（替代 LLM 调用）
        
        仅当有丰富内容时调用：
        - reference_explanation: 前面的解释内容
        - referenced_content: 用户引用的历史内容
        - input_text: 用户提供的原始文本
        
        Args:
            params: 输入参数（包含 topic, num_cards 等）
            context: 上下文
        
        Returns:
            Dict: {"content": str (JSON), "thinking": None, "usage": {}}
        """
        import json
        from ..services.external_flashcard_service import get_external_flashcard_service
        
        # 获取外部服务
        external_service = get_external_flashcard_service()
        
        # 提取参数
        topic = params.get('topic', '')
        # num_cards: 用户指定的数量，None 表示让 API 自动决定
        num_cards = params.get('num_cards')  # 不设默认值，让 API 自动决定
        
        # 构建输入文本 - 按优先级选择内容源
        input_text = ""
        content_source = ""
        
        # 1. 优先使用 reference_explanation（前面的解释内容）
        if params.get('reference_explanation'):
            ref = params['reference_explanation']
            if isinstance(ref, dict):
                # 从解释内容中提取文本
                parts = []
                if ref.get('intuition'):
                    parts.append(ref['intuition'])
                if ref.get('deep_dive'):
                    parts.append(ref['deep_dive'])
                if ref.get('examples'):
                    for ex in ref['examples'][:2]:  # 取前2个例子
                        if isinstance(ex, dict):
                            parts.append(ex.get('description', ''))
                        else:
                            parts.append(str(ex))
                input_text = " ".join(parts)
            else:
                input_text = str(ref)
            content_source = "reference_explanation"
        
        # 2. 其次使用 referenced_content（用户引用的历史内容）
        elif params.get('referenced_content'):
            input_text = params['referenced_content']
            content_source = "referenced_content"
        
        # 3. 使用 input_text（用户提供的原始文本）
        elif params.get('input_text'):
            input_text = params['input_text']
            content_source = "input_text"
        
        # 🆕 获取 file_uris（多文件附件）
        file_uris = params.get('file_uris', [])
        file_uri = params.get('file_uri')  # 兼容旧逻辑
        from_file = params.get('from_file', False)
        
        # 4. Fallback: 使用 topic（但这种情况不应该走外部 API）
        has_files = (file_uris and len(file_uris) > 0) or file_uri
        if not input_text.strip():
            if has_files:
                # 🆕 有文件时，使用简单指令让外部 API 处理
                file_count = len(file_uris) if file_uris else 1
                input_text = f"根据{file_count}个文件的内容生成闪卡"
                content_source = "file_based"
            else:
                input_text = topic
                content_source = "topic_only"
        
        # 🆕 获取语言设置
        language = params.get('language', 'auto')
        # 语言映射：将内部语言代码映射到外部 API 支持的格式（支持 30+ 语言）
        lang_map = {
            'auto': None,  # None 表示让 API 自动检测
            'en': 'English',
            'zh': 'Chinese',
            'zh-CN': 'Chinese',
            'zh-TW': 'Traditional Chinese',
            'ja': 'Japanese',
            'ko': 'Korean',
            'fr': 'French',
            'es': 'Spanish',
            'pt': 'Portuguese',
            'de': 'German',
            'it': 'Italian',
            'ru': 'Russian',
            'vi': 'Vietnamese',
            'th': 'Thai',
            'hi': 'Hindi',
            'id': 'Indonesian',
            'ms': 'Malay',
            'tr': 'Turkish',
            'pl': 'Polish',
            'nl': 'Dutch',
            'ro': 'Romanian',
            'cs': 'Czech',
            'sk': 'Slovak',
            'hu': 'Hungarian',
            'tl': 'Filipino',
            'no': 'Norwegian',
            'da': 'Danish',
            'fi': 'Finnish',
        }
        output_language = lang_map.get(language, None)
        
        logger.info(f"🌐 Executing flashcard via external API: topic='{topic}', num_cards={num_cards}, source={content_source}, input_len={len(input_text)}, file_uris={file_uris if file_uris else 'N/A'}, language={language}→{output_language}")
        
        try:
            # 调用外部 API（传递多文件）
            result = await external_service.create_flashcards(
                text=input_text,
                card_size=num_cards,
                output_language=output_language,  # 🆕 使用用户语言偏好
                file_uri=file_uri,  # 兼容旧逻辑
                file_uris=file_uris  # 🆕 传递多文件 URI 列表
            )
            
            # 🆕 外部 API 可能忽略 cardSize，手动截取到用户指定数量
            if num_cards and 'cardList' in result:
                actual_count = len(result['cardList'])
                if actual_count > num_cards:
                    logger.info(f"✂️ Trimming flashcards: API returned {actual_count}, user requested {num_cards}")
                    result['cardList'] = result['cardList'][:num_cards]
            
            # 返回格式与 LLM 调用一致
            return {
                "content": json.dumps(result, ensure_ascii=False),
                "thinking": None,
                "usage": {"external_api": True}
            }
            
        except Exception as e:
            logger.error(f"❌ External flashcard API failed: {e}")
            # 返回错误格式
            error_result = {
                "title": f"生成失败: {topic}",
                "cardList": [],
                "error": str(e)
            }
            return {
                "content": json.dumps(error_result, ensure_ascii=False),
                "thinking": None,
                "usage": {"external_api": True, "error": str(e)}
            }
    
    async def _execute_quiz_via_external_api(
        self,
        params: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        🔥 通过外部 API 生成测验题目（替代 LLM 调用）
        
        Args:
            params: 输入参数（包含 topic, num_questions 等）
            context: 上下文
        
        Returns:
            Dict: {"content": str (JSON), "thinking": None, "usage": {}}
        """
        from ..services.external_quiz_service import get_external_quiz_service
        
        # 获取外部服务
        external_service = get_external_quiz_service()
        
        # 提取参数
        topic = params.get('topic', '')
        # num_questions: 用户指定的数量，None 表示让 API 自动决定
        num_questions = params.get('num_questions')
        
        # 构建输入文本 - 按优先级选择内容源
        input_text = ""
        content_source = ""
        
        # 1. 优先使用 reference_explanation（前面的解释内容）
        if params.get('reference_explanation'):
            ref = params['reference_explanation']
            if isinstance(ref, dict):
                parts = []
                if ref.get('intuition'):
                    parts.append(ref['intuition'])
                if ref.get('deep_dive'):
                    parts.append(ref['deep_dive'])
                if ref.get('examples'):
                    for ex in ref['examples'][:2]:
                        if isinstance(ex, dict):
                            parts.append(ex.get('description', ''))
                        else:
                            parts.append(str(ex))
                input_text = " ".join(parts)
            else:
                input_text = str(ref)
            content_source = "reference_explanation"
        
        # 2. 其次使用 referenced_content（用户引用的历史内容）
        elif params.get('referenced_content'):
            input_text = params['referenced_content']
            content_source = "referenced_content"
        
        # 3. 使用 input_text（用户提供的原始文本）
        elif params.get('input_text'):
            input_text = params['input_text']
            content_source = "input_text"
        
        # 🆕 获取 file_uris（多文件附件）
        file_uris = params.get('file_uris', [])
        file_uri = params.get('file_uri')  # 兼容旧逻辑
        from_file = params.get('from_file', False)
        
        # 4. Fallback: 使用 topic
        has_files = (file_uris and len(file_uris) > 0) or file_uri
        if not input_text.strip():
            if has_files:
                # 🆕 有文件时，使用简单指令让外部 API 处理
                file_count = len(file_uris) if file_uris else 1
                input_text = f"根据{file_count}个文件的内容出题"
                content_source = "file_based"
            else:
                input_text = topic
                content_source = "topic_only"
        
        # 🆕 获取语言设置
        language = params.get('language', 'auto')
        # 语言映射：将内部语言代码映射到外部 API 支持的格式（支持 30+ 语言）
        lang_map = {
            'auto': None,  # None 表示让 API 自动检测
            'en': 'English',
            'zh': 'Chinese',
            'zh-CN': 'Chinese',
            'zh-TW': 'Traditional Chinese',
            'ja': 'Japanese',
            'ko': 'Korean',
            'fr': 'French',
            'es': 'Spanish',
            'pt': 'Portuguese',
            'de': 'German',
            'it': 'Italian',
            'ru': 'Russian',
            'vi': 'Vietnamese',
            'th': 'Thai',
            'hi': 'Hindi',
            'id': 'Indonesian',
            'ms': 'Malay',
            'tr': 'Turkish',
            'pl': 'Polish',
            'nl': 'Dutch',
            'ro': 'Romanian',
            'cs': 'Czech',
            'sk': 'Slovak',
            'hu': 'Hungarian',
            'tl': 'Filipino',
            'no': 'Norwegian',
            'da': 'Danish',
            'fi': 'Finnish',
        }
        output_language = lang_map.get(language, None)
        
        logger.info(f"🌐 Executing quiz via external API: topic='{topic}', num_questions={num_questions}, source={content_source}, input_len={len(input_text)}, file_uris={file_uris if file_uris else 'N/A'}, language={language}→{output_language}")
        
        try:
            # 调用外部 API（传递多文件）
            result = await external_service.create_quiz(
                text=input_text,
                question_count=num_questions,
                output_language=output_language,  # 🆕 使用用户语言偏好
                file_uri=file_uri,  # 兼容旧逻辑
                file_uris=file_uris  # 🆕 传递多文件 URI 列表
            )
            
            # 🆕 外部 API 可能忽略 questionCount，手动截取到用户指定数量
            if num_questions and 'questions' in result:
                actual_count = len(result['questions'])
                if actual_count > num_questions:
                    logger.info(f"✂️ Trimming quiz: API returned {actual_count}, user requested {num_questions}")
                    result['questions'] = result['questions'][:num_questions]
            
            # 返回格式与 LLM 调用一致
            return {
                "content": json.dumps(result, ensure_ascii=False),
                "thinking": None,
                "usage": {"external_api": True}
            }
            
        except Exception as e:
            logger.error(f"❌ External quiz API failed: {e}")
            # 返回错误格式
            error_result = {
                "title": f"生成失败: {topic}",
                "questions": [],
                "error": str(e)
            }
            return {
                "content": json.dumps(error_result, ensure_ascii=False),
                "thinking": None,
                "usage": {"external_api": True, "error": str(e)}
            }
    
    def _generate_context_preview(
        self,
        context: Dict[str, Any],
        params: Dict[str, Any],
        thinking_mode: str
    ) -> Optional[Dict[str, Any]]:
        """
        🆕 生成上下文预览信息（让用户知道基于什么来生成）
        
        Args:
            context: 上下文字典
            params: 参数字典
            thinking_mode: 思考模式 ("real_thinking" / "fake_thinking")
        
        Returns:
            预览信息字典，包含 message 和 details
        """
        details = []
        
        # 1. 提取主题
        topic = params.get("topic", "")
        if topic:
            details.append(f"📚 主题：{topic}")
        
        # 2. 提取引用内容摘要（清理 LaTeX）
        if params.get("referenced_content"):
            ref_content = params["referenced_content"]
            # 清理 LaTeX 和特殊符号
            ref_preview = self._clean_for_display(ref_content[:150])
            details.append(f"📎 引用内容：{ref_preview}...")
        
        # 3. 提取历史上下文摘要
        recent_artifacts = context.get("recent_artifacts", [])
        if recent_artifacts:
            # 只显示最近 2 个
            for artifact in recent_artifacts[:2]:
                artifact_topic = artifact.get("topic", "")
                artifact_type = artifact.get("type", "")
                # 类型中文映射
                type_map = {
                    "explanation": "概念讲解",
                    "quiz_set": "练习题",
                    "flashcard_set": "闪卡",
                    "mindmap": "思维导图",
                    "notes": "笔记"
                }
                type_cn = type_map.get(artifact_type, artifact_type)
                
                # 获取摘要并清理
                summary = artifact.get("summary", "")
                if summary:
                    summary_preview = self._clean_for_display(summary[:80])
                    details.append(f"📄 {artifact_topic}({type_cn})：{summary_preview}...")
        
        # 4. 生成主消息
        if not details:
            return None  # 没有上下文，不显示预览
        
        # 根据思考模式选择提示语
        if thinking_mode == "real_thinking":
            message = "🧠 深度分析中，基于以下上下文..."
        else:
            message = "⚡ 快速生成中，基于以下上下文..."
        
        return {
            "message": message,
            "details": details
        }
    
    def _clean_for_display(self, text: str) -> str:
        """
        清理文本用于显示（移除 LaTeX、特殊符号等）
        
        Args:
            text: 原始文本
        
        Returns:
            清理后的文本
        """
        import re
        
        if not text:
            return ""
        
        # 移除 LaTeX 公式 $...$ 和 $$...$$
        text = re.sub(r'\$\$[^$]+\$\$', '[公式]', text)
        text = re.sub(r'\$[^$]+\$', '[公式]', text)
        
        # 移除 LaTeX 命令 \xxx{...}
        text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', text)
        text = re.sub(r'\\[a-zA-Z]+', '', text)
        
        # 移除 JSON 特殊字符
        text = text.replace('{', '').replace('}', '')
        text = text.replace('[', '').replace(']', '')
        text = text.replace('"', '').replace("'", '')
        
        # 移除多余空白
        text = ' '.join(text.split())
        
        return text.strip()
    
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
        格式化 Prompt（直接拼接模板和参数 JSON）
        
        新版 Prompt 不再使用占位符，而是直接通过 JSON 传递参数
        
        Args:
            prompt_template: Prompt 模板
            params: 输入参数
            context: 上下文
        
        Returns:
            格式化后的 prompt
        """
        import json
        
        # 新版 Prompt 不使用占位符，直接使用原模板
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
"""
        
        # 🆕 添加语言指令（如果有 language 参数）
        language = params.get('language', 'auto')
        if language and language != 'auto':
            # 语言代码到语言名称的映射
            LANGUAGE_NAMES = {
                "en": "English",
                "zh": "Simplified Chinese (简体中文)",
                "zh-CN": "Simplified Chinese (简体中文)",
                "zh-TW": "Traditional Chinese (繁體中文)",
                "ja": "Japanese (日本語)",
                "ko": "Korean (한국어)",
                "fr": "French (Français)",
                "es": "Spanish (Español)",
                "pt": "Portuguese (Português)",
                "de": "German (Deutsch)",
                "it": "Italian (Italiano)",
                "ru": "Russian (Русский)",
                "vi": "Vietnamese (Tiếng Việt)",
                "th": "Thai (ภาษาไทย)",
                "hi": "Hindi (हिंदी)",
                "id": "Indonesian (Bahasa Indonesia)",
                "ms": "Malay (Melayu)",
                "tr": "Turkish (Türkçe)",
                "pl": "Polish (Polski)",
                "nl": "Dutch (Nederlands)",
                "ro": "Romanian (Română)",
                "cs": "Czech (Čeština)",
                "sk": "Slovak (Slovenčina)",
                "hu": "Hungarian (Magyar)",
                "tl": "Filipino/Tagalog",
                "no": "Norwegian (Norsk)",
                "da": "Danish (Dansk)",
                "fi": "Finnish (Suomi)",
            }
            target_language = LANGUAGE_NAMES.get(language, language)
            formatted += f"""

## ⚠️ LANGUAGE REQUIREMENT

**CRITICAL**: You MUST respond in **{target_language}** only. All text content in your response must be in {target_language}. This is a strict requirement.
"""
            logger.info(f"🌐 Added language instruction: {target_language}")
        
        # 🆕 Step 2.5: 附加引用内容（如果有）
        if "referenced_content" in params and params["referenced_content"]:
            formatted += f"""

## Referenced Content (用户引用的历史内容)

用户消息中引用了以下历史内容，请在生成响应时基于这些内容：

{params["referenced_content"]}
"""
            logger.info(f"📎 Added referenced content to prompt (~{len(params['referenced_content'])} chars)")
        
        # 🔥 Step 3: 附加上下文信息（上下文卸载的关键！）
        if context:
            # 添加 recent artifacts（压缩的历史上下文）
            if "recent_artifacts" in context and context["recent_artifacts"]:
                artifacts_summary = []
                for artifact in context["recent_artifacts"]:
                    # 🆕 只使用 summary（压缩摘要），不传 content（完整数据太大）
                    artifacts_summary.append({
                        "topic": artifact.get("topic"),
                        "type": artifact.get("type"),
                        "summary": artifact.get("summary")  # 压缩的上下文摘要
                    })
                
                artifacts_json = json.dumps(artifacts_summary, ensure_ascii=False, indent=2)
                formatted += f"""

## Previous Learning Context (Compressed)

The user has previously learned the following topics. Use this context to maintain continuity and avoid repetition:

```json
{artifacts_json}
```
"""
                logger.info(f"📦 Added {len(artifacts_summary)} artifact summaries to prompt (~{len(artifacts_json)} chars)")
            
            # 添加 conversation history（如果有）
            if "conversation_history" in context and context["conversation_history"]:
                formatted += f"""

## Recent Conversation

{context["conversation_history"][:1000]}  
"""
                logger.debug(f"💬 Added conversation history to prompt")
        
        formatted += """

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
        elif "cardList" in result or "flashcard_set_id" in result or "cards" in result:
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
            
            # 🆕 优先从 skill_result 中提取实际 topic（API 返回的）
            # 如果 skill_result 没有，再使用 intent_result.topic
            topic = None
            
            # 1. 尝试从 skill_result 中提取 topic
            if skill_result:
                # Quiz/Flashcard: title 字段
                if skill_result.get('title'):
                    topic = skill_result.get('title')
                    logger.info(f"📤 Extracted topic from skill_result.title: '{topic}'")
                # Explanation: concept 或 subject 字段
                elif skill_result.get('concept'):
                    topic = skill_result.get('concept')
                    logger.info(f"📤 Extracted topic from skill_result.concept: '{topic}'")
                elif skill_result.get('subject'):
                    topic = skill_result.get('subject')
                    logger.info(f"📤 Extracted topic from skill_result.subject: '{topic}'")
                # Learning Bundle: topic 字段
                elif skill_result.get('topic'):
                    topic = skill_result.get('topic')
                    logger.info(f"📤 Extracted topic from skill_result.topic: '{topic}'")
            
            # 2. Fallback: 使用 intent_result.topic（但排除无效的 topic）
            invalid_topics = {"文件内容", "这文件 内容", "附件内容", "文件", "附件", "None", ""}
            if not topic or topic in invalid_topics:
                intent_topic = intent_result.topic
                if intent_topic and intent_topic not in invalid_topics and len(intent_topic) >= 3:
                    topic = intent_topic
                    logger.info(f"📤 Using intent_result.topic: '{topic}'")
                else:
                    # 3. Fallback: 使用 session current_topic
                    topic = session_context.current_topic or "未知主题"
                    logger.info(f"📤 Fallback to session current_topic: '{topic}'")
            
            # 更新 session 的 current_topic
            if topic and topic not in invalid_topics and len(topic) >= 3:
                session_context.current_topic = topic
                logger.info(f"✅ Updated current_topic to: {topic}")
            
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
            for artifact_record in reversed(session_context.artifact_history[-10:]):  # 最近10个
                # 🔥 直接使用 artifact_record.topic
                topic = artifact_record.topic
                if topic and topic not in seen_topics and topic != "未知主题":
                    topics.append(topic)
                    seen_topics.add(topic)
            
            logger.info(f"📚 Extracted {len(topics)} recent topics: {topics}")
            return topics
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to extract recent topics: {e}")
            return []
    
    def _extract_topic_from_result(self, skill_result: Dict[str, Any], fallback_topic: str = None) -> str:
        """
        从 skill_result 中提取实际 topic
        
        优先级：
        1. skill_result.title (quiz/flashcard)
        2. skill_result.concept (explanation)
        3. skill_result.subject (explanation)
        4. skill_result.topic (learning_bundle)
        5. fallback_topic
        
        Args:
            skill_result: 技能执行结果
            fallback_topic: 后备 topic
        
        Returns:
            提取的 topic
        """
        if not skill_result:
            return fallback_topic or ""
        
        # 🆕 类型检查：如果 skill_result 是列表，尝试从第一个元素提取
        if isinstance(skill_result, list):
            if len(skill_result) > 0 and isinstance(skill_result[0], dict):
                skill_result = skill_result[0]
            else:
                return fallback_topic or ""
        
        # 确保 skill_result 是字典
        if not isinstance(skill_result, dict):
            return fallback_topic or ""
        
        # 无效 topic 列表
        invalid_topics = {"文件内容", "这文件 内容", "附件内容", "文件", "附件", "None", "", "N/A", "未知主题"}
        
        # 按优先级尝试提取
        candidates = [
            skill_result.get('title'),       # Quiz/Flashcard
            skill_result.get('concept'),     # Explanation
            skill_result.get('subject'),     # Explanation fallback
            skill_result.get('topic'),       # Learning Bundle
        ]
        
        for candidate in candidates:
            if candidate and candidate not in invalid_topics and len(str(candidate)) >= 2:
                return str(candidate)
        
        # 使用 fallback，但需要验证
        if fallback_topic and fallback_topic not in invalid_topics and len(fallback_topic) >= 2:
            return fallback_topic
        
        return ""
    
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

