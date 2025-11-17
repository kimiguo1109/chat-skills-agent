"""
Intent Router - 意图识别路由器

负责解析用户输入，识别学习意图并返回结构化结果。
"""
import logging
import json
from pathlib import Path
from typing import Optional

from ..services.gemini import GeminiClient
from ..models.intent import IntentResult, MemorySummary
from ..config import settings

logger = logging.getLogger(__name__)


class IntentRouter:
    """意图识别路由器"""
    
    # 置信度阈值
    CONFIDENCE_THRESHOLD = 0.6
    
    # Prompt 模板路径
    PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "intent_router.txt"
    
    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        """
        初始化 Intent Router
        
        Args:
            gemini_client: Gemini API 客户端，如果不提供则创建新实例
        """
        self.gemini_client = gemini_client or GeminiClient()
        self.prompt_template = self._load_prompt_template()
        logger.info("✅ IntentRouter initialized")
    
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
    
    def _format_prompt(
        self,
        message: str,
        memory_summary: Optional[str] = None
    ) -> str:
        """
        格式化 prompt
        
        Args:
            message: 用户消息
            memory_summary: 记忆摘要（字符串）
        
        Returns:
            str: 格式化后的 prompt
        """
        # memory_summary 现在是字符串，直接使用
        formatted = self.prompt_template.format(
            message=message,
            memory_summary=memory_summary or "No previous context available."
        )
        
        return formatted
    
    async def parse(
        self,
        message: str,
        memory_summary: Optional[str] = None
    ) -> list[IntentResult]:
        """
        解析用户消息，识别意图
        
        Args:
            message: 用户消息
            memory_summary: 可选的记忆摘要，用于增强识别准确度
        
        Returns:
            IntentResult: 意图识别结果
        
        Raises:
            Exception: 如果 API 调用失败
        """
        logger.info(f"🔍 Parsing intent for message: {message[:50]}...")
        
        # 格式化 prompt
        prompt = self._format_prompt(message, memory_summary)
        
        try:
            # 调用 Gemini API
            response_text = await self.gemini_client.generate(
                prompt=prompt,
                model=settings.GEMINI_MODEL,
                response_format="json",
                max_tokens=200,  # Intent recognition needs short output
                temperature=0.3   # Lower temperature for more consistent classification
            )
            
            # 解析 JSON 响应
            response_data = json.loads(response_text)
            
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

