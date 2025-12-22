"""
Intent Router - 意图识别路由器 (Phase 4)

负责解析用户输入，识别学习意图并返回结构化结果。

Phase 4 架构：100% 0-Token Intent Matching
- 使用 Skill Registry 进行基于关键词的智能匹配
- 支持复杂意图（学习包、混合请求）
- 无需 LLM，完全节省 tokens
- 未匹配请求返回 'other' intent（闲聊/不明确请求）

Token 节省：100% (相比 Phase 1/2)
"""
import logging
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

from ..models.intent import IntentResult, MemorySummary
from ..config import settings
from .rule_based_classifier import RuleBasedIntentClassifier
from .skill_registry import SkillRegistry, get_skill_registry
from .reference_resolver import get_reference_resolver

logger = logging.getLogger(__name__)


class IntentRouter:
    """意图识别路由器"""
    
    # 置信度阈值
    CONFIDENCE_THRESHOLD = 0.6
    
    # Prompt 模板路径
    PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "intent_router.txt"
    
    # Intent Router JSON 输出保存路径
    INTENT_OUTPUT_PATH = Path(__file__).parent.parent.parent / "memory_storage" / "intent_router_output.json"
    
    def __init__(
        self,
        save_output: bool = True
    ):
        """
        初始化 Intent Router (Phase 4)
        
        Args:
            save_output: 是否保存 Intent Router 的 JSON 输出（默认 True）
        """
        self.save_output = save_output
        
        # 🆕 Phase 4: 初始化 Skill Registry (0-token matching)
        self.skill_registry = get_skill_registry()
        logger.info("✅ IntentRouter initialized with Skill Registry (Phase 4, 100% 0-token)")
        
        self.prompt_template = self._load_prompt_template()
        
        # 统计数据 - 从文件加载历史统计
        self.stats = self._load_stats_from_file()
        
        # 确保保存目录存在
        if self.save_output:
            self.INTENT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    def _load_prompt_template(self) -> str:
        """
        加载 prompt 模板
        
        Returns:
            str: Prompt 模板内容
        
        Raises:
            FileNotFoundError: 如果模板文件不存在
        """
        try:
            with open(self.PROMPT_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                template = f.read()
            logger.debug(f"📄 Loaded prompt template: {self.PROMPT_TEMPLATE_PATH}")
            return template
        except FileNotFoundError:
            logger.error(f"❌ Prompt template not found: {self.PROMPT_TEMPLATE_PATH}")
            raise
    
    def _load_stats_from_file(self) -> Dict[str, int]:
        """从文件加载历史统计数据"""
        try:
            if self.INTENT_OUTPUT_PATH.exists():
                with open(self.INTENT_OUTPUT_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "stats" in data:
                        stats = data["stats"]
                        # 提取数值（去掉百分号等）
                        return {
                            "total_requests": stats.get("total_requests", 0),
                            "rule_based_success": stats.get("rule_based_success", 0),
                            "llm_fallback": stats.get("llm_fallback", 0)
                        }
        except Exception as e:
            logger.warning(f"⚠️  Failed to load stats from file: {e}")
        
        # 默认值
        return {
            "total_requests": 0,
            "rule_based_success": 0,
            "llm_fallback": 0
        }
    
    def _save_intent_output(
        self,
        user_message: str,
        intent_results: list[IntentResult],
        method: str,
        tokens_used: int = 0
    ):
        """
        保存 Intent Router 的输出到 JSON 文件
        
        Args:
            user_message: 用户输入消息
            intent_results: Intent Router 识别的结果列表
            method: 识别方法 ("rule_engine" 或 "llm_fallback")
            tokens_used: 消耗的 token 数量
        """
        if not self.save_output:
            return
        
        try:
            # 构建输出数据
            output_data = {
                "timestamp": datetime.now().isoformat(),
                "user_message": user_message,
                "method": method,
                "tokens_used": tokens_used,
                "results": []
            }
            
            # 添加每个 intent result
            for result in intent_results:
                result_dict = {
                    "intent": result.intent,
                    "topic": result.topic,
                    "confidence": result.confidence,
                    "parameters": result.parameters
                }
                output_data["results"].append(result_dict)
            
            # 读取现有历史（保留最近10条）
            history = []
            if self.INTENT_OUTPUT_PATH.exists():
                try:
                    with open(self.INTENT_OUTPUT_PATH, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                        history = existing_data.get("history", [])
                except Exception as e:
                    logger.warning(f"⚠️  Failed to load existing intent output history: {e}")
            
            # 添加当前结果到历史
            history.append(output_data)
            
            # 只保留最近10条记录
            history = history[-10:]
            
            # 构建完整数据结构
            full_data = {
                "description": "Intent Router 实时输出记录 (Phase 3 架构)",
                "latest": output_data,
                "history": history,
                "stats": {
                    "total_requests": self.stats["total_requests"],
                    "rule_based_success": self.stats["rule_based_success"],
                    "llm_fallback": self.stats["llm_fallback"],
                    "rule_success_rate": f"{self.stats['rule_based_success']/self.stats['total_requests']*100:.1f}%" if self.stats['total_requests'] > 0 else "0%"
                }
            }
            
            # 保存到文件
            with open(self.INTENT_OUTPUT_PATH, 'w', encoding='utf-8') as f:
                json.dump(full_data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"💾 Intent output saved to {self.INTENT_OUTPUT_PATH}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save intent output: {e}")
    
    def _format_prompt(
        self,
        message: str,
        memory_summary: Optional[str] = None,
        last_artifact_summary: Optional[str] = None
    ) -> str:
        """
        格式化 prompt (Phase 3: Minimal Context)
        
        Phase 3 优化：只传递最小化上下文标记，不传递完整内容
        
        Args:
            message: 用户消息
            memory_summary: 记忆摘要（字符串）- 从中提取 top preference
            last_artifact_summary: 上一轮 artifact 摘要 - 只检查是否存在
        
        Returns:
            str: 格式化后的 prompt
        """
        # Phase 3: 提取最小化上下文标记
        
        # 1. 提取用户偏好（top preference only, ~2 tokens）
        user_preference_top = "null"
        if memory_summary and "prefers" in memory_summary:
            # 从 memory_summary 中提取偏好
            # 示例: "[User Preference: prefers flashcards (75%)]"
            try:
                if "flashcard" in memory_summary.lower():
                    user_preference_top = "flashcard"
                elif "quiz" in memory_summary.lower():
                    user_preference_top = "quiz"
                elif "explain" in memory_summary.lower():
                    user_preference_top = "explain"
                elif "mindmap" in memory_summary.lower():
                    user_preference_top = "mindmap"
                elif "notes" in memory_summary.lower():
                    user_preference_top = "notes"
            except Exception as e:
                logger.warning(f"⚠️ Failed to extract preference: {e}")
        
        # 2. 检查是否有上一轮内容（~1 token）
        has_last_artifact = "false"
        if last_artifact_summary and last_artifact_summary != "No previous interaction.":
            has_last_artifact = "true"
        
        # 3. 格式化 prompt（使用最小化标记）
        formatted = self.prompt_template.format(
            message=message,
            user_preference_top=user_preference_top,
            has_last_artifact=has_last_artifact
        )
        
        logger.debug(f"📝 Context flags: preference={user_preference_top}, has_artifact={has_last_artifact}")
        
        return formatted
    
    def _topic_needs_llm_extraction(
        self,
        extracted_topic: Optional[str],
        current_topic: Optional[str],
        message: str
    ) -> bool:
        """
        检查提取的 topic 是否需要 LLM 辅助提取
        
        返回 True 的情况：
        1. topic 为空且 current_topic 也为空
        2. topic 包含垃圾字符（如顿号、逗号分隔的列表）
        3. topic 太短（< 2 字符）
        4. topic 包含技能关键词（说明提取错误）
        """
        # 如果有 current_topic，不需要 LLM（直接 fallback 到 current_topic）
        if current_topic:
            return False
        
        # 如果 topic 为空，需要 LLM
        if not extracted_topic:
            return True
        
        # 检查垃圾字符
        garbage_indicators = ['、', '，', ',', '  ', '。', '.']
        if any(g in extracted_topic for g in garbage_indicators):
            return True
        
        # 检查 topic 太短
        if len(extracted_topic.strip()) < 2:
            return True
        
        # 检查 topic 包含技能关键词
        skill_keywords = ['闪卡', '测验', '笔记', '题', '导图', '解释', '讲解', '学习包', '提供']
        if any(kw in extracted_topic for kw in skill_keywords):
            return True
        
        return False
    
    async def _llm_extract_topic(
        self,
        message: str,
        current_topic: Optional[str],
        session_topics: Optional[list]
    ) -> Optional[str]:
        """
        使用 Gemini LLM 辅助提取 topic
        
        这是一个轻量级调用，只用于提取 topic
        """
        try:
            from ..services.gemini import GeminiClient
            import json
            
            gemini = GeminiClient()
            
            # 构建简洁的 prompt
            context_hint = ""
            if current_topic:
                context_hint = f"当前对话主题是：{current_topic}\n"
            if session_topics:
                context_hint += f"历史主题：{', '.join(session_topics[:3])}\n"
            
            prompt = f"""你是一个 topic 提取助手。从用户消息中提取学习主题。

{context_hint}
用户消息：{message}

规则：
1. 提取用户想要学习的**核心主题**（如"好莱坞历史"、"牛顿第二定律"）
2. 不要包含动作词（如"给我"、"帮我"、"生成"）
3. 不要包含技能词（如"闪卡"、"测验"、"笔记"、"学习包"）
4. 如果消息中没有明确主题，但有历史主题上下文，返回最相关的历史主题
5. 如果完全无法确定主题，返回 null

仅返回 JSON：{{"topic": "提取的主题" 或 null}}"""

            response = await gemini.generate(
                prompt=prompt,
                model="gemini-2.5-flash",
                response_format="json",
                max_tokens=100,
                temperature=0.3
            )
            
            if response and "content" in response:
                content = response["content"]
                if isinstance(content, str):
                    result = json.loads(content)
                elif isinstance(content, dict):
                    result = content
                else:
                    return None
                
                topic = result.get("topic")
                if topic and isinstance(topic, str) and len(topic) >= 2:
                    logger.info(f"🤖 LLM topic extraction: '{topic}'")
                    return topic
            
            return None
            
        except Exception as e:
            logger.warning(f"⚠️  LLM topic extraction failed: {e}")
            return None
    
    async def parse(
        self,
        message: str,
        memory_summary: Optional[str] = None,
        last_artifact_summary: Optional[str] = None,
        current_topic: Optional[str] = None,
        session_topics: Optional[list] = None,
        has_files: bool = False
    ) -> list[IntentResult]:
        """
        解析用户消息，识别意图 (Phase 4)
        
        Phase 4 流程：
        1. 使用 Skill Registry 进行0-token关键词匹配
        2. 如果无法匹配，返回 'other' intent（不使用LLM）
        
        Args:
            message: 用户消息
            memory_summary: 可选的记忆摘要，用于增强识别准确度
            last_artifact_summary: 上一轮 artifact 摘要（用于上下文引用）
            current_topic: 当前对话主题（从 session_context）
            session_topics: 历史topics列表（从 session_context）
            has_files: 是否有文件附件
        
        Returns:
            list[IntentResult]: 意图识别结果列表
        
        Raises:
            Exception: 如果 API 调用失败
        """
        logger.info(f"🔍 Parsing intent for message: {message[:50]}...")
        if current_topic:
            logger.info(f"📚 Current topic from context: {current_topic}")
        if session_topics:
            logger.info(f"📚 Session topics: {session_topics}")
        if has_files:
            logger.info(f"📎 Has file attachments")
        
        # 统计
        self.stats["total_requests"] += 1
        
        # ============= 🚀 Phase 4: 优先使用 Skill Registry (0 tokens) =============
        skill_match = self.skill_registry.match_message(message, current_topic, session_topics, has_files)
        
        # 🔥 处理 clarification needed 情况
        if skill_match and skill_match.skill_id == "clarification_needed":
            logger.warning(f"⚠️  Clarification needed: {skill_match.parameters.get('clarification_reason')}")
            
            # 返回 clarification intent
            clarification_result = IntentResult(
                intent="clarification_needed",
                topic=None,
                target_artifact=None,
                confidence=1.0,
                raw_text=message,
                parameters=skill_match.parameters
            )
            
            return [clarification_result]
        
        if skill_match and skill_match.confidence >= 0.7:
            # Skill Registry 成功匹配！
            logger.info(
                f"✅ Skill Registry Match: {skill_match.skill_id} "
                f"(confidence: {skill_match.confidence:.2f}) | "
                f"Keywords: {skill_match.matched_keywords}"
            )
            
            # 将 skill_id 转换为 intent（保持向后兼容）
            intent_mapping = {
                "quiz_skill": "quiz_request",
                "explain_skill": "explain_request",
                "flashcard_skill": "flashcard_request",
                "notes_skill": "notes",
                "mindmap_skill": "mindmap_request",
                "learning_plan_skill": "learning_bundle"
            }
            
            intent = intent_mapping.get(skill_match.skill_id, skill_match.skill_id)
            
            # 🆕 检测引用（0 token，本地正则）
            reference_resolver = get_reference_resolver()
            has_reference = reference_resolver.has_references(message)
            if has_reference:
                logger.info(f"🔗 Reference detected in message, will resolve in orchestrator")
            
            # 🆕 获取 topic 并检查是否需要 LLM 辅助提取
            extracted_topic = skill_match.parameters.get('topic')
            
            # 🔥 对于 'other' intent（闲聊/问候），跳过 topic 提取（节省 token）
            if intent == "other":
                logger.info(f"💬 Skipping topic extraction for 'other' intent (conversation)")
                extracted_topic = None  # 闲聊不需要 topic
            else:
                # 检查 topic 是否有效（如果无效，需要 LLM 辅助提取）
                topic_needs_llm = self._topic_needs_llm_extraction(extracted_topic, current_topic, message)
                
                if topic_needs_llm:
                    logger.info(f"⚠️  Topic extraction uncertain: '{extracted_topic}', using LLM assist")
                    # 🔥 调用 Gemini LLM 辅助提取 topic
                    llm_topic = await self._llm_extract_topic(message, current_topic, session_topics)
                    if llm_topic:
                        extracted_topic = llm_topic
                        skill_match.parameters['topic'] = llm_topic
                        logger.info(f"✅ LLM extracted topic: '{llm_topic}'")
                    elif current_topic:
                        # LLM 也无法提取，使用 current_topic
                        extracted_topic = current_topic
                        skill_match.parameters['topic'] = current_topic
                        logger.info(f"📚 Fallback to current_topic: '{current_topic}'")
            
            # 构建 IntentResult
            intent_result = IntentResult(
                intent=intent,
                topic=extracted_topic,
                target_artifact=None,
                confidence=skill_match.confidence,
                raw_text=message,
                parameters=skill_match.parameters,
                has_reference=has_reference  # 🆕 标记是否包含引用
            )
            
            logger.info(
                f"📊 Token Usage (Skill Registry) | Input: 0 | Output: 0 | Total: 0 | "
                f"Time: <0.001s | Method: Skill Registry (Phase 4)"
            )
            logger.info(f"💰 Tokens Saved: ~3,000 | 100% savings")
            
            # 💾 保存 Intent Router 输出
            self._save_intent_output(
                user_message=message,
                intent_results=[intent_result],
                method="skill_registry",
                tokens_used=0
            )
            
            return [intent_result]
        
        # ============= 🆕 LLM Fallback: 使用便宜的 Gemini 2.0 Flash Exp =============
        # Skill Registry 未匹配时，使用 Gemini（不是直接返回 other）
        # 场景：罕见需求、复杂表述、未注册的技能
        
        if skill_match:
            logger.info(
                f"⚠️  Skill Registry low confidence: {skill_match.skill_id} "
                f"({skill_match.confidence:.2f} < 0.7), trying LLM fallback"
            )
        else:
            logger.info("⚠️  No Skill Registry match, trying LLM fallback (Gemini 2.0 Flash Exp)")
        
        # 尝试使用 Gemini LLM
        try:
            from ..services.gemini import GeminiClient
            
            gemini = GeminiClient()
            
            # 🆕 使用更简洁的 prompt（提高成功率）
            simple_prompt = f"""你是一个意图分类器。分析用户消息并返回 JSON。

用户消息：{message}

请分析用户想要做什么，返回以下 JSON 格式：
{{
  "intent": "quiz|flashcard|explain|notes|mindmap|learning_bundle|other",
  "topic": "提取的主题或null",
  "confidence": 0.85
}}

意图说明：
- quiz: 用户想要练习题/测验/做题
- flashcard: 用户想要闪卡/记忆卡
- explain: 用户想要讲解/解释/了解某个概念
- notes: 用户想要笔记/总结
- mindmap: 用户想要思维导图
- learning_bundle: 用户想要学习计划/学习包
- other: 其他对话/闲聊/问候

只返回 JSON，不要其他内容："""
            
            # 调用 Gemini（便宜且快速）
            import time
            start_time = time.time()
            
            response = await gemini.generate(
                prompt=simple_prompt,
                model="gemini-2.5-flash",  # 便宜的模型
                response_format="json",
                temperature=0.3,  # 🆕 降低温度以提高一致性
                max_tokens=200,  # 🆕 限制输出长度
                thinking_budget=0,  # 🔧 禁用思考以确保完整输出
                return_thinking=False
            )
            
            elapsed_time = time.time() - start_time
            
            # 解析 LLM 响应
            if response and "content" in response:
                content = response["content"]
                
                # 🆕 增强的解析逻辑
                llm_result = None
                
                # 处理 content 可能是 str 或 dict
                if isinstance(content, str):
                    import json
                    # 清理可能的 markdown 代码块
                    content_clean = content.strip()
                    if content_clean.startswith("```"):
                        content_clean = content_clean.split("```")[1]
                        if content_clean.startswith("json"):
                            content_clean = content_clean[4:]
                        content_clean = content_clean.strip()
                    
                    # 尝试解析 JSON
                    try:
                        llm_result = json.loads(content_clean)
                    except json.JSONDecodeError:
                        # 🆕 如果解析失败，尝试提取 JSON 部分
                        import re
                        json_match = re.search(r'\{[^{}]*\}', content_clean)
                        if json_match:
                            llm_result = json.loads(json_match.group())
                        else:
                            raise ValueError(f"Cannot parse JSON from: {content_clean[:100]}")
                elif isinstance(content, dict):
                    llm_result = content
                else:
                    raise ValueError(f"Unexpected content type: {type(content)}")
                
                # 🆕 验证必要字段
                if not llm_result or "intent" not in llm_result:
                    raise ValueError(f"Missing 'intent' field in response: {llm_result}")
                
                # 提取 intent 信息
                intent = llm_result.get("intent", "other")
                topic = llm_result.get("topic", current_topic)
                confidence = llm_result.get("confidence", 0.7)
                parameters = llm_result.get("parameters", {})
                
                intent_result = IntentResult(
                    intent=intent,
                    topic=topic,
                    target_artifact=None,
                    confidence=confidence,
                    raw_text=message,
                    parameters=parameters
                )
                
                # 统计
                self.stats["llm_fallback"] += 1
                
                # 估算 token 使用（Gemini Flash 更便宜）
                estimated_tokens = len(simple_prompt) // 4 + len(str(content)) // 4  # 粗略估算
                
                logger.info(
                    f"✅ LLM Fallback Success (Gemini): intent={intent}, topic={topic}, confidence={confidence:.2f}"
                )
                logger.info(
                    f"📊 Token Usage (LLM Fallback) | Estimated: ~{estimated_tokens} | "
                    f"Time: {elapsed_time:.2f}s | Cost: ~1/10 of Kimi"
                )
                
                # 💾 保存 Intent Router 输出
                self._save_intent_output(
                    user_message=message,
                    intent_results=[intent_result],
                    method="llm_fallback_gemini",
                    tokens_used=estimated_tokens
                )
                
                return [intent_result]
            
        except Exception as e:
            logger.warning(f"⚠️  LLM fallback failed: {e}, returning 'other' intent")
        
        # ============= 最终 Fallback: 返回 other =============
        # 如果 Gemini 也失败了，返回 other
        
        logger.info("⚠️  All methods failed, returning 'other' intent as final fallback")
        
        other_result = IntentResult(
            intent="other",
            topic=current_topic,  # 保持当前topic，便于上下文对话
            target_artifact=None,
            confidence=0.5,
            raw_text=message,
            parameters={}
        )
        
        # 💾 保存 Intent Router 输出
        self._save_intent_output(
            user_message=message,
            intent_results=[other_result],
            method="final_fallback",
            tokens_used=0
        )
        
        return [other_result]
        
        # ============= 🚀 DEPRECATED: 规则引擎 (Phase 3, 已废弃) =============
        # Phase 4 不再使用规则引擎，Skill Registry 已完全替代
        if False and self.use_rule_engine and self.rule_classifier:
            rule_result = self.rule_classifier.classify(message, memory_summary)
            
            if rule_result:
                # 规则引擎成功识别！
                self.stats["rule_based_success"] += 1
                
                # 计算节省的 tokens（估算）
                estimated_saved_tokens = 3000  # Intent Router 平均消耗
                
                logger.info(
                    f"📊 Token Usage (Rule-Based) | Input: 0 | Output: 0 | Total: 0 | "
                    f"Time: <0.01s | Method: Rule Engine"
                )
                logger.info(
                    f"💰 Tokens Saved: ~{estimated_saved_tokens:,} | "
                    f"Success rate: {self.stats['rule_based_success']}/{self.stats['total_requests']} "
                    f"({self.stats['rule_based_success']/self.stats['total_requests']*100:.1f}%)"
                )
                
                # 转换为 IntentResult 对象
                intent_result = IntentResult(
                    intent=rule_result["intent"],
                    topic=rule_result["topic"],
                    target_artifact=rule_result["target_artifact"],
                    confidence=rule_result["confidence"],
                    raw_text=rule_result["raw_text"],
                    parameters=rule_result.get("parameters", {})
                )
                
                logger.info(f"✅ Intent parsed: {intent_result.intent} (confidence: {intent_result.confidence:.2f}, topic: {intent_result.topic})")
                
                # 💾 保存 Intent Router 输出
                self._save_intent_output(
                    user_message=message,
                    intent_results=[intent_result],
                    method="rule_engine",
                    tokens_used=0
                )
                
                return [intent_result]
        
        # ============= 规则引擎失败，回退到 LLM =============
        self.stats["llm_fallback"] += 1
        logger.info(
            f"⚠️  Rule-based classification FAILED, falling back to LLM | "
            f"Fallback rate: {self.stats['llm_fallback']}/{self.stats['total_requests']} "
            f"({self.stats['llm_fallback']/self.stats['total_requests']*100:.1f}%)"
        )
        
        # 格式化 prompt
        prompt = self._format_prompt(message, memory_summary, last_artifact_summary)
        
        try:
            # 调用 LLM API（🔧 全部使用 Gemini）
            response = await self.gemini_client.generate(
                prompt=prompt,
                model="gemini-2.5-flash",  # 🔧 统一使用 Gemini 2.5 Flash
                response_format="json",
                max_tokens=200,  # Intent recognition needs short output
                temperature=0.3,   # Lower temperature for more consistent classification
                thinking_budget=0,  # 🔥 Intent routing 不需要 thinking（节省 tokens）
                return_thinking=False
            )
            
            # 🔥 兼容新版 generate 返回格式：Dict["content", "thinking", "usage"]
            # 对于 Intent Router，JSON 可能在 thinking 字段中（thinking 模型特性）
            if isinstance(response, dict):
                thinking_text = response.get("thinking", "")
                content_text = response.get("content", "")
                
                logger.info(f"📊 thinking: {len(thinking_text)} chars, preview: {thinking_text[:200]}")
                logger.info(f"📊 content: {len(content_text)} chars, preview: {content_text[:200]}")
                
                # 判断哪个字段更可能包含JSON（通过简单启发式）
                thinking_has_json = thinking_text and (thinking_text.strip().startswith('{') or '{"intent"' in thinking_text)
                content_has_json = content_text and (content_text.strip().startswith('{') or '{"intent"' in content_text)
                
                if thinking_has_json:
                    logger.info(f"⚡ Using thinking field (detected JSON)")
                    response_text = thinking_text
                elif content_has_json:
                    logger.info(f"⚡ Using content field (detected JSON)")
                    response_text = content_text
                else:
                    # 两个都不像JSON，尝试thinking优先（thinking模型特性）
                    logger.warning(f"⚠️ Neither field looks like JSON, trying thinking first")
                    response_text = thinking_text if thinking_text else content_text
            else:
                response_text = response
            
            # 🐛 DEBUG: Log the raw LLM response
            response_preview = response_text[:500] if isinstance(response_text, str) else str(response_text)[:500]
            logger.info(f"🔍 LLM Response preview: {response_preview}")
            
            # 解析 JSON 响应
            response_data = json.loads(response_text)
            logger.debug(f"🔍 LLM Response (parsed): {response_data}")
            
            # 意图映射：统一化不同的表达
            intent_mapping = {
                "quiz": "quiz_request",
                "explain": "explain_request",
                "flashcard": "flashcard_request",
                "learning_bundle": "learning_bundle",  # 保持原样，与skill配置一致
                "mindmap": "mindmap_request",  # 思维导图
                "other": "other"
            }
            
            # 检查是否为混合请求（有 "intents" 数组）
            if "intents" in response_data:
                logger.info(f"🔀 Detected MIXED REQUEST with {len(response_data['intents'])} intents")
                results = []
                
                for idx, intent_data in enumerate(response_data["intents"]):
                    intent = intent_data.get("intent", "other")
                    topic = intent_data.get("topic")
                    target_artifact = intent_data.get("target_artifact")
                    confidence = float(intent_data.get("confidence", 0.5))
                    parameters = intent_data.get("parameters", {})
                    
                    # 标准化 intent
                    normalized_intent = intent_mapping.get(intent, intent)
                    
                    # 如果提取了 quantity 参数，记录日志
                    if parameters.get("quantity"):
                        logger.info(f"📊 Intent {idx+1}: Extracted quantity parameter: {parameters['quantity']}")
                    
                    # 创建结果对象
                    result = IntentResult(
                        intent=normalized_intent,
                        topic=topic,
                        target_artifact=target_artifact,
                        confidence=confidence,
                        raw_text=message,
                        parameters=parameters
                    )
                    
                    results.append(result)
                    logger.info(f"✅ Intent {idx+1} parsed: {result.intent} (confidence: {result.confidence:.2f}, topic: {result.topic})")
                
                # 💾 保存 Intent Router 输出 (混合请求)
                self._save_intent_output(
                    user_message=message,
                    intent_results=results,
                    method="llm_fallback",
                    tokens_used=1487  # 估算值，Phase 3 优化后的 LLM Fallback token 消耗
                )
                
                return results
            else:
                # 单个请求
                intent = response_data.get("intent", "other")
                topic = response_data.get("topic")
                target_artifact = response_data.get("target_artifact")
                confidence = float(response_data.get("confidence", 0.5))
                parameters = response_data.get("parameters", {})
                
                # 应用置信度阈值逻辑
                if confidence < self.CONFIDENCE_THRESHOLD:
                    logger.warning(
                        f"⚠️ Low confidence ({confidence:.2f} < {self.CONFIDENCE_THRESHOLD}), "
                        f"falling back to 'other'"
                    )
                    intent = "other"
                    target_artifact = None
                
                # 标准化 intent
                normalized_intent = intent_mapping.get(intent, intent)
                
                # 如果提取了 quantity 参数，记录日志
                if parameters.get("quantity"):
                    logger.info(f"📊 Extracted quantity parameter: {parameters['quantity']}")
                
                # 🐛 DEBUG: Log all extracted parameters
                logger.debug(f"📊 All extracted parameters: {parameters}")
                
                # 创建结果对象
                result = IntentResult(
                    intent=normalized_intent,
                    topic=topic,
                    target_artifact=target_artifact,
                    confidence=confidence,
                    raw_text=message,
                    parameters=parameters
                )
                
                logger.info(f"✅ Intent parsed: {result.intent} (confidence: {result.confidence:.2f}, topic: {result.topic})")
                
                # 💾 保存 Intent Router 输出 (单个请求)
                self._save_intent_output(
                    user_message=message,
                    intent_results=[result],
                    method="llm_fallback",
                    tokens_used=1487  # 估算值，Phase 3 优化后的 LLM Fallback token 消耗
                )
                
                return [result]  # 返回单元素列表，保持接口一致
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse JSON response: {e}")
            # 返回默认的 "other" 意图（列表形式）
            return [IntentResult(
                intent="other",
                topic=None,
                target_artifact=None,
                confidence=0.0,
                raw_text=message
            )]
        
        except Exception as e:
            logger.error(f"❌ Intent parsing failed: {e}")
            raise
    
    async def parse_batch(
        self,
        messages: list[str],
        memory_summary: Optional[MemorySummary] = None
    ) -> list[IntentResult]:
        """
        批量解析多个消息
        
        Args:
            messages: 消息列表
            memory_summary: 记忆摘要
        
        Returns:
            list[IntentResult]: 意图识别结果列表
        """
        results = []
        for message in messages:
            result = await self.parse(message, memory_summary)
            results.append(result)
        
        return results
    
    def get_optimization_stats(self) -> dict:
        """
        获取优化统计信息
        
        Returns:
            统计信息字典
        """
        total = self.stats["total_requests"]
        rule_success = self.stats["rule_based_success"]
        llm_fallback = self.stats["llm_fallback"]
        
        if total == 0:
            return {
                "total_requests": 0,
                "rule_based_success": 0,
                "llm_fallback": 0,
                "rule_success_rate": 0.0,
                "estimated_tokens_saved": 0,
                "average_tokens_per_request": 0
            }
        
        # 估算 token 节省
        # 规则引擎: 0 tokens
        # LLM: ~3,000 tokens
        estimated_saved = rule_success * 3000
        average_per_request = llm_fallback * 3000 / total
        
        return {
            "total_requests": total,
            "rule_based_success": rule_success,
            "llm_fallback": llm_fallback,
            "rule_success_rate": rule_success / total * 100 if total > 0 else 0,
            "estimated_tokens_saved": estimated_saved,
            "average_tokens_per_request": int(average_per_request)
        }

