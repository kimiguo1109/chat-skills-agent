"""
Kimi (Moonshot AI) API Service Wrapper
使用 Novita AI 提供的 Kimi API 代理

支持功能：
- 非流式生成
- 流式生成
- Reasoning 模式（类似 Gemini 的 thinking）
- OpenAI SDK 兼容
"""
import logging
from typing import Dict, Any, Optional, AsyncGenerator
import json
from openai import OpenAI, AsyncOpenAI
from ..config import settings

logger = logging.getLogger(__name__)


class KimiClient:
    """Kimi (Moonshot AI) API Client"""
    
    def __init__(self):
        """初始化 Kimi Client（通过 Novita AI）"""
        self.api_key = settings.KIMI_API_KEY
        self.base_url = settings.KIMI_BASE_URL
        self.model = settings.KIMI_MODEL
        
        # 同步客户端
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        # 异步客户端（用于流式）
        self.async_client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        
        logger.info(f"✅ Kimi client initialized via Novita AI")
        logger.info(f"📍 Base URL: {self.base_url}")
        logger.info(f"🤖 Model: {self.model}")
    
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        response_format: str = "text",
        temperature: float = 0.6,
        max_tokens: int = 4096,
        thinking_budget: Optional[int] = None,
        return_thinking: bool = True
    ) -> Dict[str, Any]:
        """
        生成内容（非流式）
        
        Args:
            prompt: 提示词（已格式化）
            model: 模型名称（可选，默认使用配置）
            response_format: 响应格式 ("text" or "json")
            temperature: 温度参数 [0, 1]（Kimi 范围）
            max_tokens: 最大 token 数
            thinking_budget: Thinking 预算（Kimi 通过 max_tokens 控制）
            return_thinking: 是否返回 thinking 过程
        
        Returns:
            Dict 包含: content, thinking, usage
        """
        model_to_use = model or self.model
        
        # ⚡⚡⚡ 应用 thinking_budget 控制（与流式保持一致）
        if thinking_budget:
            if thinking_budget <= 64:
                content_budget = 3500
            elif thinking_budget <= 128:
                content_budget = 4000
            else:
                content_budget = 5000
            actual_max_tokens = thinking_budget + content_budget
            logger.info(f"⚡ Token Budget: thinking={thinking_budget}, content={content_budget}, total={actual_max_tokens}")
        else:
            actual_max_tokens = max_tokens
        
        # ⚡⚡⚡ 添加系统级约束
        messages = []
        if thinking_budget and thinking_budget <= 128:
            system_constraint = (
                f"CRITICAL: Strict {thinking_budget}-token thinking limit. "
                f"Be EXTREMELY concise - 2-4 sentences MAX. "
                f"Skip verbose reasoning. Focus only on core logic."
            )
            messages.append({"role": "system", "content": system_constraint})
        
        messages.append({"role": "user", "content": prompt})
        
        logger.info(f"🚀 Generating: model={model_to_use}, temp={temperature}, max_tokens={actual_max_tokens}, thinking_budget={thinking_budget}")
        
        try:
            # Kimi API 调用（通过 Novita AI）
            response = self.client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                temperature=temperature,
                max_tokens=actual_max_tokens,  # ⚡⚡⚡ 使用实际计算的 max_tokens
                stream=False
            )
            
            choice = response.choices[0]
            content = choice.message.content or ""
            
            # 提取 reasoning_content（Kimi 的 thinking 模式）
            reasoning_content = getattr(choice.message, 'reasoning_content', None) or ""
            
            # 提取 token 使用信息
            usage = response.usage
            usage_stats = {
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
                "reasoning_tokens": 0  # Kimi 可能不单独计算
            }
            
            logger.info(f"✅ Generation complete: {len(content)} chars, {usage_stats['total_tokens']} tokens")
            if reasoning_content:
                logger.info(f"🧠 Reasoning: {len(reasoning_content)} chars")
            
            # JSON 解析（如果需要）
            result = content
            if response_format == "json":
                try:
                    # 尝试提取 JSON（可能包含在 markdown 代码块中）
                    json_str = content
                    if "```json" in content:
                        json_str = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        json_str = content.split("```")[1].split("```")[0].strip()
                    result = json.loads(json_str)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse JSON, returning raw content: {e}")
                    result = content
            
            return {
                "content": result,
                "thinking": reasoning_content if return_thinking else "",
                "usage": usage_stats
            }
        
        except Exception as e:
            logger.error(f"❌ Kimi generation error: {e}")
            raise
    
    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 1.0,  # ⚡⚡⚡ 参照在线版：1.0最大化速度
        max_tokens: int = 131072,  # ⚡⚡⚡ 参照在线版：131072
        thinking_budget: Optional[int] = None,
        return_thinking: bool = True,
        buffer_size: int = 1  # ⚡⚡⚡⚡ 极限优化：每个字符立即发送
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        生成内容（流式 + 优化缓冲）
        
        Args:
            prompt: 提示词
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数（总输出限制）
            thinking_budget: Thinking 预算（如果设置，会覆盖 max_tokens）
            return_thinking: 是否返回 thinking
            buffer_size: 缓冲区大小（默认1字符，极限流式）
        
        Yields:
            Dict: {"type": "thinking|content|done|error", ...}
        """
        model_to_use = model or self.model
        
        # ⚡⚡⚡ 真正的 Token 控制：根据 thinking_budget 动态调整 max_tokens
        # Thinking 模型的输出 = thinking_content + actual_content
        # 
        # 策略：
        # - thinking_budget 小 (64) → 快速思考，适合简单任务
        # - content_budget 中等 (3000-4000) → 确保输出质量不受影响
        # 
        # 实测数据：
        # - Explain Skill (简单概念): thinking ~200 tokens, content ~1500 tokens
        # - Quiz (3题): thinking ~150 tokens, content ~1200 tokens
        # - Flashcard (5张): thinking ~100 tokens, content ~800 tokens
        if thinking_budget:
            # 根据 thinking_budget 智能分配 content budget
            if thinking_budget <= 64:
                # 极速模式：适合简单任务
                content_budget = 3500  # 确保输出完整
            elif thinking_budget <= 128:
                # 标准模式：适合中等任务
                content_budget = 4000
            else:
                # 深度模式：适合复杂任务
                content_budget = 5000
            
            actual_max_tokens = thinking_budget + content_budget
            logger.info(f"⚡ Token Budget: thinking={thinking_budget}, content={content_budget}, total={actual_max_tokens}")
        else:
            actual_max_tokens = max_tokens
            logger.info(f"⚡ Using default max_tokens={actual_max_tokens}")
        
        # ⚡⚡⚡ 添加系统级约束来真正控制 thinking 长度
        # 这比在 prompt 中"建议"更有效，因为它作为系统指令
        messages = []
        
        if thinking_budget and thinking_budget <= 128:
            # 对于小 thinking_budget，添加强制的系统约束
            system_constraint = (
                f"CRITICAL: Strict {thinking_budget}-token thinking limit. "
                f"Be EXTREMELY concise - 2-4 sentences MAX. "
                f"Skip verbose reasoning. Focus only on core logic."
            )
            messages.append({"role": "system", "content": system_constraint})
        
        messages.append({"role": "user", "content": prompt})
        
        logger.info(f"🌊 Starting streaming: model={model_to_use}, max_tokens={actual_max_tokens}, thinking_budget={thinking_budget}")
        
        # 累加器
        content_accumulated = []
        reasoning_accumulated = []
        
        # 🆕 缓冲区（减少碎片化）
        content_buffer = []
        reasoning_buffer = []
        
        try:
            # Kimi 流式 API（使用OpenAI兼容参数）
            stream = await self.async_client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                temperature=temperature,
                max_tokens=actual_max_tokens,  # ⚡⚡⚡ 使用实际计算的 max_tokens
                top_p=1.0,  # ⚡ 控制采样范围
                presence_penalty=0.0,  # ⚡ 无重复惩罚
                frequency_penalty=0.0,  # ⚡ 无频率惩罚
                stream=True
                # ⚠️ 注意：top_k不被OpenAI API支持，已移除
            )
            
            async for chunk in stream:
                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                
                # 提取 reasoning_content（Kimi 的 thinking）
                reasoning_chunk = getattr(delta, 'reasoning_content', None)
                if reasoning_chunk and isinstance(reasoning_chunk, str):
                    reasoning_accumulated.append(reasoning_chunk)
                    
                    # 🔥 二次分块：确保thinking也是流式的
                    chunk_size = 5  # 每5个字符作为一个流式单位
                    for i in range(0, len(reasoning_chunk), chunk_size):
                        mini_chunk = reasoning_chunk[i:i+chunk_size]
                        reasoning_buffer.append(mini_chunk)
                        
                        # 立即发送
                        buffered_text = "".join(reasoning_buffer)
                        if len(buffered_text) >= buffer_size:
                            # logger.info(f"🧠 Thinking stream: {len(buffered_text)} chars")
                            yield {
                                "type": "thinking",
                                "text": buffered_text,
                                "accumulated": "".join(reasoning_accumulated)
                            }
                            reasoning_buffer = []
                
                # 提取 content
                content_chunk = delta.content
                if content_chunk and isinstance(content_chunk, str):
                    content_accumulated.append(content_chunk)
                    
                    # 🔥 二次分块：如果API返回的chunk太大，拆分成小块流式发送
                    # 这确保了即使API一次返回大块内容，用户也能看到流式效果
                    chunk_size = 5  # 每5个字符作为一个流式单位
                    for i in range(0, len(content_chunk), chunk_size):
                        mini_chunk = content_chunk[i:i+chunk_size]
                        content_buffer.append(mini_chunk)
                        
                        # 立即发送（buffer_size=1意味着不再累积）
                        buffered_text = "".join(content_buffer)
                        if len(buffered_text) >= buffer_size:
                            # logger.info(f"📝 Content stream: {len(buffered_text)} chars")
                            yield {
                                "type": "content",
                                "text": buffered_text,
                                "accumulated": "".join(content_accumulated)
                            }
                            content_buffer = []
            
            # 🆕 发送剩余缓冲区内容
            if reasoning_buffer:
                buffered_text = "".join(reasoning_buffer)
                # logger.info(f"🧠 Reasoning final flush: {len(buffered_text)} chars")
                yield {
                    "type": "thinking",
                    "text": buffered_text,
                    "accumulated": "".join(reasoning_accumulated)
                }
            
            if content_buffer:
                buffered_text = "".join(content_buffer)
                # logger.info(f"📝 Content final flush: {len(buffered_text)} chars")
                yield {
                    "type": "content",
                    "text": buffered_text,
                    "accumulated": "".join(content_accumulated)
                }
            
            # 完成
            full_thinking = "".join(reasoning_accumulated)
            full_content = "".join(content_accumulated)
            
            logger.info(f"✅ Streaming generation complete")
            logger.info(f"📊 Final content: {len(full_content)} chars")
            logger.info(f"🧠 Final reasoning: {len(full_thinking)} chars")
            
            # 🔥 不在这里发送done事件！
            # done事件应该由skill_orchestrator发送，包含解析后的content
            # 这里只是标记流式结束
            logger.info(f"🏁 Stream ended (orchestrator will send done event)")
        
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Streaming generation error: {e}")
            
            # 503 错误处理
            if "503" in error_msg or "overloaded" in error_msg.lower():
                yield {
                    "type": "error",
                    "error": "AI服务暂时过载，请等待几秒后重试 (503 Service Overloaded)",
                    "code": 503
                }
            else:
                yield {
                    "type": "error",
                    "error": error_msg,
                    "code": 500
                }
    
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.6,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        生成 JSON 格式内容
        
        Args:
            prompt: 提示词
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
        
        Returns:
            解析后的 JSON 对象
        """
        result = await self.generate(
            prompt=prompt,
            model=model,
            response_format="json",
            temperature=temperature,
            max_tokens=max_tokens,
            return_thinking=False
        )
        return result["content"]

