"""
Agent API - 统一的聊天端点

提供 /api/agent/chat 端点，完整编排 Intent Router, Memory Manager, 和 Skill Orchestrator
"""
import logging
import time
import json
import asyncio
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.core import SkillOrchestrator, MemoryManager
from app.services.gemini import GeminiClient
from app.dependencies import get_memory_manager, get_gemini_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ============= Helper Functions =============

def _generate_artifact_summary(artifact_type: str, content: Dict[str, Any]) -> str:
    """
    生成artifact的摘要，用于显示和搜索
    
    Args:
        artifact_type: artifact类型
        content: artifact内容
    
    Returns:
        摘要文本
    """
    try:
        if artifact_type == "explanation":
            concept = content.get("concept", "未知概念")
            examples_count = len(content.get("examples", []))
            return f"概念「{concept}」的解释，包含{examples_count}个例子"
        
        elif artifact_type == "quiz_set":
            questions_count = len(content.get("questions", []))
            topic = content.get("topic", "未知主题")
            return f"{questions_count}道关于「{topic}」的题目"
        
        elif artifact_type == "flashcard_set":
            cards_count = len(content.get("cards", []))
            topic = content.get("topic", "未知主题")
            return f"{cards_count}张关于「{topic}」的闪卡"
        
        elif artifact_type == "notes":
            if "structured_notes" in content:
                notes = content["structured_notes"]
                sections_count = len(notes.get("sections", []))
                topic = notes.get("topic", "未知主题")
                return f"关于「{topic}」的笔记，包含{sections_count}个章节"
            return "学习笔记"
        
        elif artifact_type == "mindmap":
            topic = content.get("root_concept", "未知主题")
            return f"「{topic}」的思维导图"
        
        elif artifact_type == "learning_bundle":
            components = content.get("components", [])
            topic = content.get("topic", "未知主题")
            return f"「{topic}」的学习包，包含{len(components)}个组件"
        
        elif artifact_type == "mixed_response":
            responses = content.get("responses", [])
            return f"混合响应，包含{len(responses)}个组件"
        
        else:
            return f"{artifact_type}类型的学习内容"
    
    except Exception as e:
        logger.warning(f"⚠️ Failed to generate summary for {artifact_type}: {e}")
        return f"{artifact_type}类型的学习内容"


# ============= Request/Response Models =============

class AgentChatRequest(BaseModel):
    """Agent 聊天请求"""
    user_id: str = Field(..., description="用户 ID", min_length=1, max_length=100)
    session_id: str = Field(..., description="会话 ID", min_length=1, max_length=100)
    message: str = Field(..., description="用户消息", min_length=1, max_length=5000)

    @field_validator('message')
    @classmethod
    def validate_message(cls, v: str) -> str:
        """验证消息不为空且不只包含空格"""
        if not v.strip():
            raise ValueError("消息不能为空")
        return v.strip()


class AgentChatResponse(BaseModel):
    """Agent 聊天响应"""
    user_id: str = Field(..., description="用户 ID")
    session_id: str = Field(..., description="会话 ID")
    response_content: Dict[str, Any] = Field(..., description="响应内容（Quiz, Explain 等）")
    content_type: str = Field(..., description="内容类型：quiz_set, explanation, error 等")
    intent: str = Field(..., description="识别的意图")
    skill_id: str = Field(..., description="使用的技能 ID")
    processing_time_ms: int = Field(default=0, description="处理时间（毫秒）")


# ============= Dependency Functions =============



def get_skill_orchestrator(
    memory_manager: MemoryManager = Depends(get_memory_manager),
    gemini_client: GeminiClient = Depends(get_gemini_client)
) -> SkillOrchestrator:
    """获取 Skill Orchestrator 实例"""
    return SkillOrchestrator(
        memory_manager=memory_manager,
        gemini_client=gemini_client
    )


# ============= API Endpoints =============

@router.post("/chat", response_model=AgentChatResponse, status_code=status.HTTP_200_OK)
async def agent_chat(
    request: AgentChatRequest,
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
) -> AgentChatResponse:
    """
    统一的 Agent 聊天端点
    
    完整流程：
    1. 解析用户意图 (Intent Router)
    2. 选择合适的技能 (Skill Registry)
    3. 执行技能 (Skill Orchestrator)
    4. 更新用户记忆 (Memory Manager)
    5. 返回结构化结果
    
    Args:
        request: 包含 user_id, session_id, message 的请求
        orchestrator: 技能编排器（依赖注入）
    
    Returns:
        AgentChatResponse: 包含生成内容、意图、技能ID等信息
        
    Raises:
        HTTPException: 当发生错误时返回相应的HTTP错误
    """
    start_time = time.time()
    
    logger.info(
        f"📩 Agent chat request from user={request.user_id}, "
        f"session={request.session_id}, message_len={len(request.message)}"
    )
    logger.info(f"💬 User message: {request.message}")
    logger.info("━"*70)
    
    try:
        # 1. 先通过 Intent Router 识别意图
        from ..core.intent_router import IntentRouter
        intent_router = IntentRouter(gemini_client=orchestrator.gemini_client)
        
        # ============= STEP 1: 记忆检索 =============
        logger.info("🔍 STEP 1: Retrieving Memory Context...")
        memory_start = time.time()
        
        memory_summary = await orchestrator.memory_manager.generate_memory_summary(
            request.user_id,
            request.session_id
        )
        memory_elapsed = time.time() - memory_start
        logger.info(f"✅ Memory retrieved in {memory_elapsed:.2f}s")
        logger.info(f"📊 Memory summary: {memory_summary}")
        logger.info("━"*70)
        
        # V1.5: 获取上一轮 artifact 摘要（用于上下文引用）
        last_artifact_summary = "No previous interaction."
        try:
            session_context = await orchestrator.memory_manager.get_session_context(
                session_id=request.session_id
            )
            if session_context and session_context.last_artifact and session_context.last_artifact_content:
                # 生成简短的摘要
                artifact_type = session_context.last_artifact
                topic = session_context.current_topic or "unknown topic"
                
                # 提取关键信息（如例子数量、问题数量等）
                content = session_context.last_artifact_content
                extra_info = ""
                if isinstance(content, dict):
                    if "examples" in content and isinstance(content["examples"], list):
                        extra_info += f" Contains {len(content['examples'])} examples."
                    if "questions" in content and isinstance(content["questions"], list):
                        extra_info += f" Contains {len(content['questions'])} questions."
                    if "cards" in content and isinstance(content["cards"], list):
                        extra_info += f" Contains {len(content['cards'])} flashcards."
                
                # 限制内容摘要长度
                content_str = str(content)[:150]
                last_artifact_summary = f"Previous: {artifact_type} about {topic}.{extra_info} Content preview: {content_str}..."
                logger.info(f"📎 Including last artifact context: {artifact_type}, topic: {topic}{extra_info}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to get last artifact summary: {e}")
        
        # ============= STEP 2: 意图识别 =============
        logger.info("🧭 STEP 2: Parsing User Intent (Intent Router)...")
        intent_start = time.time()
        
        intent_results = await intent_router.parse(
            message=request.message,
            memory_summary=memory_summary,
            last_artifact_summary=last_artifact_summary
        )
        
        intent_elapsed = time.time() - intent_start
        logger.info(f"✅ Intent parsed in {intent_elapsed:.2f}s")
        logger.info(f"📊 Detected {len(intent_results)} intent(s): {[r.intent for r in intent_results]}")
        logger.info("━"*70)
        
        # 2. 特殊处理：如果意图是 "help"，返回功能列表
        if len(intent_results) == 1 and intent_results[0].intent == "help":
            processing_time = time.time() - start_time
            help_text = """你好！我是 StudyX Agent，你的智能学习助手 🎓

我目前支持以下 6 大核心学习技能：

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1️⃣ 📖 概念讲解 (Explanation)
   用法：「解释牛顿第二定律」「帮我理解量子力学」
   特点：直觉理解 + 正式定义 + 实例说明

2️⃣ 📝 测验生成 (Quiz)
   用法：「给我5道微积分的题」「二战历史测验」
   特点：多题型（选择、填空、简答），自动评分

3️⃣ 🎴 闪卡生成 (Flashcard)
   用法：「生成光合作用的闪卡」「给我3张英语单词卡」
   特点：Anki 风格，正反面记忆

4️⃣ 📝 学习笔记 (Notes)
   用法：「帮我做个笔记」「总结二战历史」
   特点：结构化笔记，支持编辑保存

5️⃣ 🗺️ 思维导图 (Mind Map)
   用法：「画个二战历史的思维导图」「量子力学知识图谱」
   特点：知识点可视化，层级清晰

6️⃣ 📦 学习包 (Learning Bundle)
   用法：「二战历史学习资料」「帮我全面学习微积分」「量子力学学习材料」
   特点：混合讲解 + 测验 + 闪卡，一站式学习

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 智能特性：
• 上下文理解：「根据这些例子生成测验」
• 个性化推荐：根据你的学习偏好智能推荐
• 混合请求：「先讲解牛顿定律，然后给我5道题」

试试问我：「二战历史学习资料」或「给我5道量子力学的题」吧！😊"""
            
            response = AgentChatResponse(
                user_id=request.user_id,
                session_id=request.session_id,
                response_content={"text": help_text},
                content_type="text",
                intent="help",
                skill_id="help",
                processing_time_ms=int(processing_time * 1000)
            )
            return response
        
        # 3. 特殊处理：如果意图是 "other"，进行友好对话和引导
        if len(intent_results) == 1 and intent_results[0].intent == "other":
            # 调用 Gemini 进行友好对话
            from app.config import settings
            gemini_client = orchestrator.gemini_client
            
            # 构建上下文信息
            context_info = ""
            relevant_topic = ""
            content_details = []  # 新增：存储具体的学习内容（如例子标题）
            
            # 尝试从 session_context 获取上一个学习主题和具体内容
            try:
                session_context = await orchestrator.memory_manager.get_session_context(
                    session_id=request.session_id
                )
                if session_context and session_context.last_artifact:
                    # 只有当 last_artifact 是学习相关类型时才提取主题
                    learning_artifacts = ["explanation", "quiz_set", "flashcard_set", "notes", "mindmap", "learning_bundle"]
                    if session_context.last_artifact in learning_artifacts and session_context.current_topic:
                        # 提取主题，去掉可能的前缀（如 "历史-"）
                        topic_part = session_context.current_topic
                        if "-" in topic_part:
                            parts = topic_part.split("-")
                            relevant_topic = parts[-1] if len(parts) > 1 else topic_part
                        else:
                            relevant_topic = topic_part
                        
                        # 🆕 提取具体学习内容（examples, sections, questions等）
                        if session_context.last_artifact_content and isinstance(session_context.last_artifact_content, dict):
                            content = session_context.last_artifact_content
                            
                            # 从 explanation 提取 examples
                            if "examples" in content and isinstance(content["examples"], list):
                                for ex in content["examples"][:5]:  # 最多取5个
                                    if isinstance(ex, dict) and "title" in ex:
                                        content_details.append(ex["title"])
                            
                            # 从 notes 提取 sections
                            if "structured_notes" in content:
                                notes = content["structured_notes"]
                                if isinstance(notes, dict) and "sections" in notes:
                                    for section in notes["sections"][:5]:  # 最多取5个
                                        if isinstance(section, dict) and "heading" in section:
                                            content_details.append(section["heading"])
                            
                            # 从 quiz 提取 questions（简化版，只取题目类型）
                            if "questions" in content and isinstance(content["questions"], list):
                                quiz_topics = set()
                                for q in content["questions"][:5]:
                                    if isinstance(q, dict) and "question_text" in q:
                                        # 尝试从题目中提取关键概念
                                        q_text = q["question_text"]
                                        if len(q_text) < 50:  # 只取简短的概念名
                                            quiz_topics.add(q_text.split("是")[0].split("有关")[0][:20])
                                content_details.extend(list(quiz_topics)[:3])
                        
                        # 构建上下文信息
                        context_info = f"\n\n⚠️ CRITICAL: 用户学习上下文：用户最近在学习「{relevant_topic}」相关内容。"
                        if content_details:
                            context_info += f"\n具体内容包括：{', '.join(content_details[:5])}"
                        context_info += "\n你的建议必须与「{relevant_topic}」主题相关！"
                        
                        logger.info(f"🎯 Detected learning context: {relevant_topic}, details: {content_details[:3]}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to get session context for learning topic: {e}")
            
            # Fallback: 从 last_artifact_summary 提取（如果上面失败）
            if not relevant_topic and last_artifact_summary and "No previous interaction" not in last_artifact_summary:
                if "topic:" in last_artifact_summary:
                    topic_part = last_artifact_summary.split("topic:")[1].split(".")[0].strip()
                    if "-" in topic_part:
                        parts = topic_part.split("-")
                        relevant_topic = parts[-1] if len(parts) > 1 else topic_part
                    else:
                        relevant_topic = topic_part
                    context_info = f"\n\n⚠️ CRITICAL: 用户学习上下文：用户最近在学习「{relevant_topic}」相关内容。你的建议必须与「{relevant_topic}」主题相关！"
                    logger.info(f"🎯 Detected learning context from summary: {relevant_topic}")
            
            conversation_prompt = f"""你是一个智能学习助手 StudyX Agent。用户向你提问了一个与学习无关的问题。

用户问题：{request.message}{context_info}

⚠️⚠️⚠️ CRITICAL RULES:
1. 你不支持用户请求的功能（如播客、视频、动画等），必须诚实地说"很抱歉，我目前还不支持XXX功能"
2. 不要给出任何虚假的承诺、链接、或推荐（不要说"没问题"、"这里为你推荐"等）
3. 不要编造任何链接（不要包含 http、.com 等）

请友好地回应用户，然后引导用户使用你的学习功能：
1. 诚实回应：明确说你不支持用户请求的功能（1句话）
2. 简洁介绍：你可以提供的学习功能（练习题、概念讲解、闪卡、学习包、笔记、思维导图）
3. ⚠️⚠️⚠️ CRITICAL - 示例必须基于具体学习内容：
   - 学习主题：{relevant_topic if relevant_topic else "无"}
   - 具体内容：{', '.join(content_details[:3]) if content_details else "无"}
   - 如果有具体内容（不为"无"），你的建议必须引用这些具体内容！
   - ✅ 好的示例：
     * 如果具体内容是"《凡尔赛条约》对德国的苛刻制裁, 1929年世界经济大萧条, 日本对中国东北的侵略"
     * 建议："详细讲解《凡尔赛条约》对德国的影响" 或 "生成关于1929年经济大萧条的闪卡" 或 "给我几道关于九一八事变的选择题"
   - ❌ 错误示例：
     * "给我几道关于二战起因的选择题"（太泛泛，应该具体到《凡尔赛条约》等具体内容）
   - 只有在没有具体内容时，才使用主题级别的建议
   - 不要使用占位符（如 **主题**），直接使用真实内容名称

保持回复友好、简洁、鼓励性（最多120字）。不要给出虚假承诺或链接！"""
            
            try:
                friendly_response = await gemini_client.generate(
                    prompt=conversation_prompt,
                    model=settings.GEMINI_MODEL,
                    max_tokens=300,
                    temperature=0.7
                )
                
                # ⚠️ CRITICAL: 验证生成的回复是否包含上下文主题和具体内容
                use_fallback = False
                if relevant_topic:
                    # 检查回复中是否包含相关主题（或其关键词）
                    topic_keywords = relevant_topic.split()
                    contains_topic = any(keyword in friendly_response for keyword in topic_keywords if len(keyword) > 1)
                    
                    # 🆕 检查是否包含具体内容（更精准的验证）
                    contains_specific_content = False
                    if content_details:
                        # 如果有具体内容，检查回复中是否引用了任何一个
                        for detail in content_details[:3]:
                            # 提取关键词（去掉标点和停用词）
                            detail_keywords = [w for w in detail.split() if len(w) > 1][:3]
                            if any(kw in friendly_response for kw in detail_keywords):
                                contains_specific_content = True
                                break
                    
                    # 检查是否包含常见的不相关示例（黑名单）
                    irrelevant_topics = ["光合作用", "量子力学", "勾股定理", "牛顿定律", "导数", "微积分", "宇宙大爆炸"]
                    contains_irrelevant = any(topic in friendly_response for topic in irrelevant_topics)
                    
                    # 检查是否包含错误承诺或幻觉内容（播客、视频、链接等）
                    hallucination_indicators = [
                        "没问题！",
                        "这里为你推荐",
                        "http://",
                        "https://",
                        ".com",
                        "播客链接",
                        "视频链接",
                        "下载链接"
                    ]
                    contains_hallucination = any(indicator in friendly_response for indicator in hallucination_indicators)
                    
                    # 验证失败条件：
                    # 1. 没有主题关键词 或
                    # 2. 包含不相关主题 或
                    # 3. 包含幻觉内容 或
                    # 4. 🆕 有具体内容但回复中没有引用（说明建议太泛泛）
                    if not contains_topic or contains_irrelevant or contains_hallucination or (content_details and not contains_specific_content):
                        if contains_hallucination:
                            logger.warning(f"⚠️ LLM response contains hallucination or false promises, using fallback")
                        elif content_details and not contains_specific_content:
                            logger.warning(f"⚠️ LLM response doesn't reference specific content details, using fallback")
                        else:
                            logger.warning(f"⚠️ LLM response doesn't contain relevant topic '{relevant_topic}' or contains irrelevant topics, using fallback")
                        use_fallback = True
                
                # 如果验证失败，使用默认回复
                if use_fallback:
                    if relevant_topic:
                        # 构建基于具体内容的建议
                        if content_details:
                            # 使用具体内容生成精准建议
                            suggestions = []
                            for i, detail in enumerate(content_details[:3]):
                                if i == 0:
                                    suggestions.append(f"• 📝 详细讲解{detail}")
                                elif i == 1:
                                    suggestions.append(f"• 🎴 生成关于{detail}的学习闪卡")
                                elif i == 2:
                                    suggestions.append(f"• 📖 给我几道关于{detail}的练习题")
                            suggestions_text = "\n".join(suggestions)
                            friendly_response = f"""很抱歉，我目前专注于学习辅助功能。

我看到你正在学习「{relevant_topic}」，特别是以下内容：
{suggestions_text}

继续你的学习之旅吧！😊"""
                        else:
                            # Fallback到主题级别建议
                            friendly_response = f"""很抱歉，我目前专注于学习辅助功能。

我看到你正在学习「{relevant_topic}」，我可以帮你：
• 📝 给我几道关于{relevant_topic}的练习题
• 📖 详细讲解{relevant_topic}的某个概念
• 🎴 生成{relevant_topic}的学习闪卡
• 📝 帮我整理{relevant_topic}的学习笔记
• 🗺️ 画一个{relevant_topic}的思维导图

继续你的学习之旅吧！😊"""
                    else:
                        friendly_response = """你好！我是 StudyX Agent，你的智能学习助手 🎓

我专注于帮助你学习，可以为你提供：
• 📝 练习题：各学科的针对性练习
• 📖 概念讲解：清晰的知识点讲解
• 🎴 学习闪卡：帮助记忆的卡片
• 📝 学习笔记：结构化笔记生成
• 🗺️ 思维导图：知识点可视化

试试问我一个学习相关的问题吧！😊"""
                
                # 计算处理时间
                processing_time = time.time() - start_time
                
                response = AgentChatResponse(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    response_content={"text": friendly_response},
                    content_type="text",
                    intent="other",
                    skill_id="conversation",
                    processing_time_ms=int(processing_time * 1000)
                )
            except Exception as e:
                logger.error(f"❌ Failed to generate friendly response: {e}")
                # 如果生成失败，使用预设的友好回复
                # 根据上下文构建默认回复
                if relevant_topic:
                    default_response = f"""很高兴为你提供帮助！不过，我目前专注于学习辅助功能。

我看到你正在学习「{relevant_topic}」，我可以帮你：
• 📝 给我几道关于{relevant_topic}的练习题
• 📖 详细讲解{relevant_topic}的某个概念
• 🎴 生成{relevant_topic}的学习闪卡
• 📝 帮我整理{relevant_topic}的学习笔记
• 🗺️ 画一个{relevant_topic}的思维导图

继续你的学习之旅吧！😊"""
                else:
                    default_response = """你好！我是 StudyX Agent，你的智能学习助手 🎓

我专注于帮助你学习，可以为你提供：
• 📝 **练习题**：各学科的针对性练习（例如："给我几道微积分题"）
• 📖 **概念讲解**：清晰的知识点讲解（例如："解释一下什么是导数"）
• 🎴 **学习闪卡**：帮助记忆的卡片（例如："给我一些光合作用的闪卡"）
• 📝 **学习笔记**：结构化笔记生成（例如："帮我整理物理知识点"）
• 🗺️ **思维导图**：知识点可视化（例如："画个化学反应的思维导图"）

试试问我一个学习相关的问题吧！😊"""
                
                processing_time = time.time() - start_time
                
                response = AgentChatResponse(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    response_content={"text": default_response},
                    content_type="text",
                    intent="other",
                    skill_id="conversation",
                    processing_time_ms=int(processing_time * 1000)
                )
        else:
            # 正常的学习意图，执行完整的技能编排管道
            # 支持混合请求：循环执行多个 intents
            all_results = []
            
            # ============= STEP 3: 技能执行 =============
            logger.info(f"🎯 STEP 3: Executing Skill(s) ({len(intent_results)} intent(s))...")
            
            for idx, intent_result in enumerate(intent_results):
                logger.info(f"━"*70)
                logger.info(f"🎯 Executing intent #{idx+1}/{len(intent_results)}: {intent_result.intent}")
                logger.info(f"📊 Topic: {intent_result.topic}, Confidence: {intent_result.confidence:.2f}")
                if intent_result.parameters:
                    logger.info(f"📋 Parameters: {intent_result.parameters}")
                
                skill_start = time.time()
                
                orchestrator_response = await orchestrator.execute(
                    intent_result=intent_result,
                    user_id=request.user_id,
                    session_id=request.session_id
                )
                
                skill_elapsed = time.time() - skill_start
                content_type = orchestrator_response.get("content_type", "unknown")
                logger.info(f"✅ Skill executed in {skill_elapsed:.2f}s (Content type: {content_type})")
                
                all_results.append(orchestrator_response)
            
            # 计算处理时间
            processing_time = time.time() - start_time
            
            # 构建响应
            if len(all_results) == 1:
                # 单个结果
                # 🆕 支持 Orchestrator 返回的特殊响应（onboarding/clarification）
                result = all_results[0]
                response_content = result.get("response_content") or result.get("content", {})
                
                response = AgentChatResponse(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    response_content=response_content,
                    content_type=result.get("content_type", "unknown"),
                    intent=result.get("intent", "unknown"),
                    skill_id=result.get("skill_id", "unknown"),
                    processing_time_ms=int(processing_time * 1000)
                )
            else:
                # 混合请求：多个结果
                response = AgentChatResponse(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    response_content={"results": all_results},
                    content_type="mixed_response",
                    intent="mixed",
                    skill_id="multiple",
                    processing_time_ms=int(processing_time * 1000)
                )
        
        logger.info(
            f"✅ Agent response generated: intent={response.intent}, "
            f"skill_id={response.skill_id}, processing_time={processing_time:.2f}s"
        )
        
        # ============= STEP 4: 记忆更新 =============
        logger.info("━"*70)
        logger.info("💾 STEP 4: Updating Memory Context...")
        memory_update_start = time.time()
        
        # 🆕 更新 session context（last_user_message + artifact_history）
        try:
            session_context = await orchestrator.memory_manager.get_session_context(
                session_id=request.session_id
            )
            
            if session_context:
                # 1️⃣ 更新 last_user_message（始终更新）
                session_context.last_user_message = request.message
                logger.info(f"✅ Updated last_user_message: '{request.message[:50]}...'")
                
                # 2️⃣ 记录 artifact 到历史（仅学习相关）
                learning_artifacts = ["explanation", "quiz_set", "flashcard_set", "notes", "mindmap", "learning_bundle", "mixed_response"]
                if response.content_type in learning_artifacts:
                    from app.models.memory import ArtifactRecord
                    
                    # 计算turn_number
                    turn_number = len(session_context.artifact_history) + 1
                    
                    # 生成summary
                    summary = _generate_artifact_summary(response.content_type, response.response_content)
                    
                    # 创建artifact record
                    artifact_record = ArtifactRecord(
                        artifact_id=f"artifact_{turn_number}",
                        turn_number=turn_number,
                        timestamp=datetime.now(),
                        artifact_type=response.content_type,
                        topic=session_context.current_topic,
                        summary=summary,
                        content=response.response_content
                    )
                    
                    session_context.artifact_history.append(artifact_record)
                    session_context.last_artifact_id = artifact_record.artifact_id
                    
                    logger.info(f"📦 Added artifact #{turn_number} to history (type: {response.content_type}, total: {len(session_context.artifact_history)})")
                else:
                    logger.info(f"⏭️  Skipping artifact recording for non-learning content: {response.content_type}")
                
                # 3️⃣ 保存更新后的 session context
                await orchestrator.memory_manager.update_session_context(
                    session_id=request.session_id,
                    context=session_context
                )
                memory_update_elapsed = time.time() - memory_update_start
                logger.info(f"✅ Session context updated in {memory_update_elapsed:.2f}s")
                
        except Exception as e:
            # 记录失败不影响主流程
            logger.warning(f"⚠️ Failed to update session context: {e}")
        
        logger.info("━"*70)
        logger.info(f"🎉 Request completed in {processing_time:.2f}s total")
        
        return response
        
    except ValueError as e:
        # 业务逻辑错误（如意图不明确）
        logger.warning(f"❌ Validation error for user {request.user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ValidationError",
                "message": str(e),
                "user_id": request.user_id,
                "session_id": request.session_id
            }
        )
        
    except FileNotFoundError as e:
        # Prompt 文件缺失
        logger.error(f"❌ File not found error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "PromptFileNotFound",
                "message": f"系统配置错误：{str(e)}",
                "user_id": request.user_id,
                "session_id": request.session_id
            }
        )
        
    except Exception as e:
        # 未预期的系统错误
        logger.exception(f"❌ Unexpected error in agent_chat for user {request.user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "InternalServerError",
                "message": "系统内部错误，请稍后再试",
                "user_id": request.user_id,
                "session_id": request.session_id
            }
        )


@router.get("/health", status_code=status.HTTP_200_OK)
async def agent_health() -> Dict[str, Any]:
    """
    Agent API 健康检查
    
    Returns:
        健康状态信息
    """
    try:
        # 检查关键组件是否可用
        memory_manager = get_memory_manager()
        gemini_client = get_gemini_client()
        
        return {
            "status": "healthy",
            "components": {
                "memory_manager": "ok" if memory_manager else "error",
                "gemini_client": "ok" if gemini_client else "error"
            },
            "message": "Agent API is operational"
        }
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "message": str(e)
            }
        )


@router.post("/chat-stream", status_code=status.HTTP_200_OK)
async def agent_chat_stream(
    request: ChatRequest,
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator),
    memory_manager: MemoryManager = Depends(get_memory_manager),
    gemini_client: GeminiClient = Depends(get_gemini_client)
):
    """
    🆕 流式聊天端点 (Server-Sent Events)
    
    实时展示思考过程和生成内容，提升用户体验
    
    Args:
        request: 聊天请求
    
    Returns:
        StreamingResponse: Server-Sent Events 流
    """
    async def event_generator():
        try:
            # Step 1: 意图识别
            yield f"data: {json.dumps({'type': 'status', 'message': '正在分析您的请求...'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.1)
            
            # 获取 memory context
            memory_summary = memory_manager.get_memory_summary(
                user_id=request.user_id,
                session_id=request.session_id
            )
            
            # 获取 last artifact summary
            session_context = memory_manager.get_session_context(request.session_id)
            last_artifact_summary = None
            if session_context and hasattr(session_context, 'last_artifact'):
                last_artifact_summary = f"User just interacted with: {session_context.last_artifact}"
            
            # Intent routing
            from app.core.intent_router import IntentRouter
            intent_router = IntentRouter(gemini_client=gemini_client)
            
            intent_results = await intent_router.parse(
                message=request.message,
                memory_summary=memory_summary,
                last_artifact_summary=last_artifact_summary
            )
            
            if not intent_results:
                yield f"data: {json.dumps({'type': 'error', 'message': '无法理解您的请求'}, ensure_ascii=False)}\n\n"
                return
            
            # Step 2: 执行技能（流式）
            intent_result = intent_results[0]
            yield f"data: {json.dumps({'type': 'status', 'message': f'开始{intent_result.intent}...'}, ensure_ascii=False)}\n\n"
            
            # 🆕 使用流式 execute
            async for chunk in orchestrator.execute_stream(
                intent_result=intent_result,
                user_id=request.user_id,
                session_id=request.session_id
            ):
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)  # 小延迟，避免前端处理过快
            
            # 完成
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            logger.error(f"❌ Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 nginx 缓冲
        }
    )


@router.get("/info", status_code=status.HTTP_200_OK)
async def agent_info(
    orchestrator: SkillOrchestrator = Depends(get_skill_orchestrator)
) -> Dict[str, Any]:
    """
    Agent 系统信息
    
    返回可用的技能、意图等信息
    
    Returns:
        系统信息和可用技能列表
    """
    try:
        all_skills = orchestrator.skill_registry.list_all_skills()
        all_intents = orchestrator.skill_registry.get_all_intents()
        
        skills_info = [
            {
                "id": skill.id,
                "display_name": skill.display_name,
                "intent_tags": skill.intent_tags,
                "version": skill.version
            }
            for skill in all_skills
        ]
        
        return {
            "total_skills": len(all_skills),
            "available_intents": all_intents,
            "skills": skills_info,
            "api_version": "1.0.0",
            "message": "Skill Agent Demo API"
        }
    except Exception as e:
        logger.error(f"❌ Failed to get agent info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "InfoRetrievalError",
                "message": str(e)
            }
        )

