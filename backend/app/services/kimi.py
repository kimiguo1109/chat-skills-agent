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
        temperature: float = 1.0,  # ⚡ 提高到 1.0 加快生成速度
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
            temperature: 温度参数 [0, 1]（Kimi 范围，1.0 最快）
            max_tokens: 最大 token 数
            thinking_budget: Thinking 预算（Kimi 通过 max_tokens 控制）
            return_thinking: 是否返回 thinking 过程
        
        Returns:
            Dict 包含: content, thinking, usage
        """
        model_to_use = model or self.model
        
        # ⚡⚡⚡ 应用 thinking_budget 控制（优化版，加快响应）
        if thinking_budget:
            if thinking_budget <= 32:
                # 🚀 极速模式：快速响应，紧凑输出
                content_budget = 2500
            elif thinking_budget <= 48:
                # ⚡ 快速模式：平衡速度和质量
                content_budget = 3000
            elif thinking_budget <= 64:
                # 标准模式
                content_budget = 3500
            elif thinking_budget <= 96:
                # 平衡模式
                content_budget = 4000
            else:
                # 深度模式
                content_budget = 4500
            actual_max_tokens = thinking_budget + content_budget
            logger.info(f"⚡ Token Budget: thinking={thinking_budget}, content={content_budget}, total={actual_max_tokens}")
        else:
            actual_max_tokens = max_tokens
        
        # ⚡⚡⚡ 不再添加 system message - 约束已在 skill prompt 中定义
        # Skill prompt 已包含：
        # - 思维限制 (Thinking): STOP THINKING. OUTPUT JSON DIRECTLY.
        # - 数量要求、格式要求、内容一致性等
        # 
        # 避免重复约束导致 thinking 过于复杂
        messages = [{"role": "user", "content": prompt}]
        
        logger.info(f"🚀 Generating: model={model_to_use}, temp={temperature}, max_tokens={actual_max_tokens}, thinking_budget={thinking_budget}")
        logger.info(f"⏳ Waiting for LLM response... (expected ~15-30s, max 60s)")
        
        try:
            # Kimi API 调用（通过 Novita AI）
            import time
            start_time = time.time()
            last_log_time = start_time
            
            response = self.client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                temperature=temperature,
                max_tokens=actual_max_tokens,  # ⚡⚡⚡ 使用实际计算的 max_tokens
                stream=False
            )
            
            elapsed = time.time() - start_time
            logger.info(f"✅ LLM response received in {elapsed:.1f}s")
            
            choice = response.choices[0]
            content = choice.message.content or ""
            
            # 提取 reasoning_content（Kimi 的 thinking 模式）
            reasoning_content = getattr(choice.message, 'reasoning_content', None) or ""
            
            # 提取 token 使用信息
            usage = response.usage
            
            # 🆕 估算 thinking tokens：reasoning_content 的字符数 / 2（中文约2字符/token）
            estimated_thinking_tokens = len(reasoning_content) // 2 if reasoning_content else 0
            
            usage_stats = {
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
                "thinking_tokens": estimated_thinking_tokens,  # 🆕 从 reasoning_content 估算
                "thinking_chars": len(reasoning_content) if reasoning_content else 0,
                "content_chars": len(content)
            }
            
            logger.info(f"✅ Generation complete: {len(content)} chars, {usage_stats['total_tokens']} tokens")
            if reasoning_content:
                logger.info(f"🧠 Reasoning: {len(reasoning_content)} chars (~{estimated_thinking_tokens} tokens)")
                logger.debug(f"🧠 Reasoning content preview: {reasoning_content[:500]}")
            
            # JSON 解析（如果需要）
            result = content
            if response_format == "json":
                try:
                    # 🔥 对于 thinking 模型，JSON 可能在 reasoning_content 中
                    json_source = content if content.strip() else reasoning_content
                    if not json_source.strip():
                        logger.warning("⚠️ Both content and reasoning_content are empty, cannot parse JSON")
                        result = content
                    else:
                        logger.debug(f"🔍 Attempting JSON parse from {'content' if content.strip() else 'reasoning_content'}: {json_source[:300]}")
                        # 尝试提取 JSON（可能包含在 markdown 代码块中）
                        json_str = json_source
                        if "```json" in json_source:
                            json_str = json_source.split("```json")[1].split("```")[0].strip()
                        elif "```" in json_source:
                            json_str = json_source.split("```")[1].split("```")[0].strip()
                        
                        # 🔧 修复 LaTeX 转义问题（如 \vec, \frac）
                        json_str = self._fix_latex_escapes(json_str)
                        
                        result = json.loads(json_str)
                        logger.info(f"✅ JSON parsed successfully from {'content' if content.strip() else 'reasoning_content'}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse JSON, returning raw content: {e}")
                    result = content if content.strip() else reasoning_content
            
            return {
                "content": result,
                "thinking": reasoning_content if return_thinking else "",
                "usage": usage_stats
            }
        
        except Exception as e:
            logger.error(f"❌ Kimi generation error: {e}")
            raise
    
    def _fix_latex_escapes(self, json_str: str) -> str:
        """
        修复 JSON 字符串中 LaTeX 公式的转义问题
        
        LaTeX 公式中的反斜杠（如 \vec, \frac）在 JSON 字符串中需要转义为 \\
        
        Args:
            json_str: JSON 字符串
        
        Returns:
            修复后的 JSON 字符串
        """
        import re
        
        # 匹配 JSON 字符串值（"..."）
        def fix_string_with_latex(match):
            full_match = match.group(0)
            content = match.group(1)
            
            # 如果内容中不包含 $，说明可能没有 LaTeX，直接返回
            if '$' not in content:
                return full_match
            
            # 修复 LaTeX 命令：\letter -> \\letter
            result = []
            i = 0
            while i < len(content):
                char = content[i]
                
                if char == '\\' and i + 1 < len(content):
                    next_char = content[i + 1]
                    # 如果下一个字符是字母（LaTeX 命令），需要转义
                    if next_char.isalpha():
                        # 检查前面是否已经是转义的反斜杠
                        if i > 0 and content[i - 1] == '\\':
                            result.append(char)
                            result.append(next_char)
                        else:
                            # 需要转义：添加额外的反斜杠
                            result.append('\\\\')
                            result.append(next_char)
                        i += 2
                        continue
                    else:
                        result.append(char)
                        result.append(next_char)
                        i += 2
                        continue
                else:
                    result.append(char)
                
                i += 1
            
            fixed_content = ''.join(result)
            return f'"{fixed_content}"'
        
        # 匹配 JSON 字符串值（包括转义的引号）
        pattern = r'"((?:[^"\\]|\\.)*)"'
        fixed_json = re.sub(pattern, fix_string_with_latex, json_str)
        
        return fixed_json
    
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
        # - thinking_budget: 控制推理长度（64-96 tokens）
        # - content_budget: 确保输出质量（3500-4000 tokens）
        # - 自然约束 + max_tokens 限制，不使用过度刻意的 system message
        # 
        # 实测数据：
        # - Explain Skill: thinking ~150-200 tokens, content ~1500 tokens
        # - Quiz (3题): thinking ~100-150 tokens, content ~1200 tokens
        # - Flashcard (5张): thinking ~80-120 tokens, content ~800 tokens
        if thinking_budget:
            # 根据 thinking_budget 智能分配 content budget
            # 🚀 优化版：降低 budget，加快响应速度
            if thinking_budget <= 32:
                # 🚀 极速模式：快速响应
                content_budget = 2500
            elif thinking_budget <= 48:
                # ⚡ 快速模式：平衡速度和质量
                content_budget = 3000
            elif thinking_budget <= 64:
                # 标准模式
                content_budget = 3500
            elif thinking_budget <= 96:
                # 平衡模式
                content_budget = 4000
            elif thinking_budget <= 128:
                # 深度模式
                content_budget = 4500
            else:
                # 超深度模式
                content_budget = 5000
            
            actual_max_tokens = thinking_budget + content_budget
            logger.info(f"⚡ Token Budget: thinking={thinking_budget}, content={content_budget}, total={actual_max_tokens}")
        else:
            actual_max_tokens = max_tokens
            logger.info(f"⚡ Using default max_tokens={actual_max_tokens}")
        
        # ⚡⚡⚡ 不再添加 system message - 约束已在 skill prompt 中定义
        # Skill prompt 已包含：
        # - 思维限制 (Thinking): STOP THINKING. OUTPUT JSON DIRECTLY.
        # - 数量要求、格式要求、内容一致性等
        # 
        # 避免重复约束导致 thinking 过于复杂
        messages = [{"role": "user", "content": prompt}]
        
        logger.info(f"🌊 Starting streaming: model={model_to_use}, max_tokens={actual_max_tokens}, thinking_budget={thinking_budget}")
        logger.info(f"⏳ Connecting to LLM stream... (thinking will appear first, then content)")
        
        # 累加器
        content_accumulated = []
        reasoning_accumulated = []
        
        # 🆕 缓冲区（减少碎片化）
        content_buffer = []
        reasoning_buffer = []
        
        # 🆕 进度追踪
        import time
        start_time = time.time()
        first_chunk_time = None
        thinking_complete_time = None
        
        try:
            # Kimi 流式 API（使用OpenAI兼容参数）
            # 🆕 尝试启用 stream_options 以获取 usage 信息
            stream = await self.async_client.chat.completions.create(
                model=model_to_use,
                messages=messages,
                temperature=temperature,
                max_tokens=actual_max_tokens,  # ⚡⚡⚡ 使用实际计算的 max_tokens
                top_p=1.0,  # ⚡ 控制采样范围
                presence_penalty=0.0,  # ⚡ 无重复惩罚
                frequency_penalty=0.0,  # ⚡ 无频率惩罚
                stream=True,
                stream_options={"include_usage": True}  # 🆕 请求返回 usage 信息
                # ⚠️ 注意：top_k不被OpenAI API支持，已移除
            )
            
            # 用于存储最终的 usage 信息
            final_usage = None
            
            async for chunk in stream:
                # 🆕 检查是否有 usage 信息（通常在最后一个 chunk）
                if hasattr(chunk, 'usage') and chunk.usage:
                    final_usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens
                    }
                    logger.info(f"📊 Received usage from API: {final_usage}")
                
                if not chunk.choices:
                    continue
                
                # 🆕 记录首个 chunk 到达时间
                if first_chunk_time is None:
                    first_chunk_time = time.time()
                    logger.info(f"✅ First chunk received in {first_chunk_time - start_time:.1f}s")
                
                delta = chunk.choices[0].delta
                
                # 提取 reasoning_content（Kimi 的 thinking）
                reasoning_chunk = getattr(delta, 'reasoning_content', None)
                if reasoning_chunk and isinstance(reasoning_chunk, str):
                    reasoning_accumulated.append(reasoning_chunk)
                    
                    # 🔥 二次分块：确保thinking也是流式的
                    chunk_size = 20  # 🚀 增加到20个字符，提高流式速度
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
                    # 🆕 记录 thinking 完成时间（第一次收到 content）
                    if thinking_complete_time is None and len(reasoning_accumulated) > 0:
                        thinking_complete_time = time.time()
                        logger.info(f"🧠 Thinking complete in {thinking_complete_time - start_time:.1f}s, content streaming started")
                    
                    content_accumulated.append(content_chunk)
                    
                    # 🔥 二次分块：如果API返回的chunk太大，拆分成小块流式发送
                    # 这确保了即使API一次返回大块内容，用户也能看到流式效果
                    chunk_size = 20  # 🚀 增加到20个字符，提高流式速度
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
            
            # 计算流式生成的时间
            total_time = time.time() - start_time
            
            logger.info(f"✅ Streaming generation complete")
            logger.info(f"📊 Final content: {len(full_content)} chars")
            logger.info(f"🧠 Final reasoning: {len(full_thinking)} chars")
            
            # 🆕 Token 使用统计（优先使用 API 返回的精确数据）
            if final_usage:
                # 使用 API 返回的精确数据
                prompt_tokens = final_usage.get("prompt_tokens", 0)
                completion_tokens = final_usage.get("completion_tokens", 0)
                total_tokens = final_usage.get("total_tokens", 0)
                
                logger.info(f"📊 Token Usage (Kimi Stream - EXACT)")
                logger.info(f"   • Input:  {prompt_tokens:,} tokens")
                logger.info(f"   • Output: {completion_tokens:,} tokens")
                logger.info(f"   • Total:  {total_tokens:,} tokens")
                logger.info(f"   • Time:   {total_time:.1f}s | Model: {model_to_use}")
                
                # 🔥 发送精确的 usage 信息给 orchestrator
                yield {
                    "type": "usage",
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                        "thinking_chars": len(full_thinking),
                        "content_chars": len(full_content),
                        "generation_time": total_time,
                        "model": model_to_use,
                        "source": "api"
                    }
                }
            else:
                # 回退到估算（流式API可能不返回usage）
                # 估算方法：中文约1.5字符/token，英文约4字符/token
                # 这里使用保守估算：平均2字符/token
                estimated_thinking_tokens = len(full_thinking) // 2
                estimated_content_tokens = len(full_content) // 2
                estimated_total_output = estimated_thinking_tokens + estimated_content_tokens
                
                logger.info(f"📊 Token Usage (Kimi Stream - ESTIMATED)")
                logger.info(f"   • Thinking: ~{estimated_thinking_tokens:,} tokens")
                logger.info(f"   • Content:  ~{estimated_content_tokens:,} tokens")
                logger.info(f"   • Total:    ~{estimated_total_output:,} tokens")
                logger.info(f"   • Time:     {total_time:.1f}s | Model: {model_to_use}")
                
                # 🔥 发送估算的 usage 信息给 orchestrator
                yield {
                    "type": "usage",
                    "usage": {
                        "thinking_tokens": estimated_thinking_tokens,
                        "content_tokens": estimated_content_tokens,
                        "total_output_tokens": estimated_total_output,
                        "thinking_chars": len(full_thinking),
                        "content_chars": len(full_content),
                        "generation_time": total_time,
                        "model": model_to_use,
                        "source": "estimated"
                    }
                }
            
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
        temperature: float = 1.0,  # ⚡ 提高到 1.0 加快生成速度
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        生成 JSON 格式内容
        
        Args:
            prompt: 提示词
            model: 模型名称
            temperature: 温度参数（1.0 最快）
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

