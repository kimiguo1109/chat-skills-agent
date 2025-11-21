"""
Intent Router - 意图识别路由器

负责解析用户输入，识别学习意图并返回结构化结果。

优化策略：规则引擎 + LLM Fallback
- 70% 明确请求: 使用规则引擎 (0 tokens)
- 30% 模糊请求: 使用 LLM (精简 prompt)
- 平均 token 节省: ~86%
"""
import logging
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

from ..services.gemini import GeminiClient
from ..models.intent import IntentResult, MemorySummary
from ..config import settings
from .rule_based_classifier import RuleBasedIntentClassifier
from .skill_registry import SkillRegistry, get_skill_registry

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
        gemini_client: Optional[GeminiClient] = None,
        use_rule_engine: bool = True,
        save_output: bool = True
    ):
        """
        初始化 Intent Router
        
        Args:
            gemini_client: Gemini API 客户端，如果不提供则创建新实例
            use_rule_engine: 是否启用规则引擎优化（默认 True）
            save_output: 是否保存 Intent Router 的 JSON 输出（默认 True）
        """
        self.gemini_client = gemini_client or GeminiClient()
        self.use_rule_engine = use_rule_engine
        self.save_output = save_output
        
        # 🆕 Phase 4: 初始化 Skill Registry (0-token matching)
        self.skill_registry = get_skill_registry()
        
        # 初始化规则引擎
        if self.use_rule_engine:
            self.rule_classifier = RuleBasedIntentClassifier()
            logger.info("✅ IntentRouter initialized with Skill Registry + Rule Engine (Phase 4)")
        else:
            self.rule_classifier = None
            logger.info("✅ IntentRouter initialized with Skill Registry only (Phase 4)")
        
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
    
    async def parse(
        self,
        message: str,
        memory_summary: Optional[str] = None,
        last_artifact_summary: Optional[str] = None,
        current_topic: Optional[str] = None,
        session_topics: Optional[list] = None
    ) -> list[IntentResult]:
        """
        解析用户消息，识别意图
        
        优化流程：
        1. 先尝试规则引擎 (0 tokens)
        2. 失败则回退到 LLM (精简 prompt)
        
        Args:
            message: 用户消息
            memory_summary: 可选的记忆摘要，用于增强识别准确度
            last_artifact_summary: 上一轮 artifact 摘要（用于上下文引用）
            current_topic: 当前对话主题（从 session_context）
            session_topics: 历史topics列表（从 session_context）
        
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
        
        # 统计
        self.stats["total_requests"] += 1
        
        # ============= 🚀 Phase 4: 优先使用 Skill Registry (0 tokens) =============
        skill_match = self.skill_registry.match_message(message, current_topic, session_topics)
        
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
        
        if skill_match and skill_match.confidence >= 0.8:
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
            
            # 构建 IntentResult
            intent_result = IntentResult(
                intent=intent,
                topic=skill_match.parameters.get('topic'),
                target_artifact=None,
                confidence=skill_match.confidence,
                raw_text=message,
                parameters=skill_match.parameters
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
        else:
            if skill_match:
                logger.debug(
                    f"⚠️  Skill Registry low confidence: {skill_match.skill_id} "
                    f"({skill_match.confidence:.2f}), falling back..."
                )
            else:
                logger.debug("⚠️  No Skill Registry match, falling back...")
        
        # ============= 🚀 Fallback 1: 规则引擎 (0 tokens) =============
        if self.use_rule_engine and self.rule_classifier:
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
            # 调用 LLM API（支持 Gemini 或 Kimi）
            response = await self.gemini_client.generate(
                prompt=prompt,
                model=settings.KIMI_MODEL if settings.KIMI_API_KEY else settings.GEMINI_MODEL,
                response_format="json",
                max_tokens=200,  # Intent recognition needs short output
                temperature=0.3,   # Lower temperature for more consistent classification
                thinking_budget=0,  # 🔥 Intent routing 不需要 thinking（节省 tokens）
                return_thinking=False
            )
            
            # 🔥 兼容新版 generate 返回格式：Dict["content", "thinking", "usage"]
            response_text = response.get("content", response) if isinstance(response, dict) else response
            
            # 🐛 DEBUG: Log the raw LLM response
            logger.debug(f"🔍 LLM Response (raw): {response_text[:500]}")  # First 500 chars
            
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

