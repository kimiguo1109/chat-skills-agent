"""
Google Gemini API 服务封装

提供统一的 LLM API 调用接口，支持：
- 文本生成
- JSON 格式化输出
- 错误处理和重试
- Token 限制
"""
import logging
import json
import time
from typing import Optional, Dict, Any, List
from google import genai  # 恢复 Gemini，用于快速压缩任务
from google.genai import types

from ..config import settings

logger = logging.getLogger(__name__)


class GeminiClient:
    """Gemini API 客户端封装（使用最新 SDK）"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        """
        初始化 Gemini 客户端
        
        Args:
            api_key: Gemini API Key，如果不提供则从 settings 读取
            model: 默认模型名称
        """
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model  # 🔧 添加 model 属性，与 KimiClient 保持一致
        
        # 创建客户端（使用最新 SDK）
        self.client = genai.Client(api_key=self.api_key)
        self.async_client = self.client.aio
        
        logger.info(f"✅ Gemini client initialized with model: {self.model}")
    
    async def generate_stream(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash",
        max_tokens: int = 2000,
        temperature: float = 0.7,
        thinking_budget: Optional[int] = 1024,
        return_thinking: bool = True,
        buffer_size: int = 1  # 兼容参数，Gemini 不使用
    ):
        """
        流式生成内容（用于实时展示思考过程）
        
        Args:
            prompt: 提示词
            model: 模型名称
            max_tokens: 最大token数
            temperature: 温度参数
            thinking_budget: 思考预算
            return_thinking: 是否返回思考过程
            
        Yields:
            Dict: 包含 type (thinking/content) 和 text 的字典
        """
        config_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "response_modalities": ["TEXT"],
        }
        
        # ⚠️ 思考配置仅支持 Gemini 2.5 Flash (Thinking)，2.0 Flash Exp 不支持
        # 为保持兼容性，暂时关闭思考配置
        # 未来可根据 model 名称判断是否支持 thinking
        # if thinking_budget is not None and thinking_budget > 0 and "thinking" in model.lower():
        #     config_kwargs["thinkingConfig"] = types.ThinkingConfig(
        #         thinkingBudget=thinking_budget,
        #         includeThoughts=return_thinking
        #     )
        
        config = types.GenerateContentConfig(**config_kwargs)
        
        try:
            logger.info(f"🌊 Starting streaming generation: model={model}")
            
            # 使用流式 API
            stream = await self.async_client.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=config
            )
            
            thinking_accumulated = []
            content_accumulated = []
            usage_metadata = {}  # 🆕 收集 usage 元数据
            
            async for chunk in stream:
                logger.debug(f"🔍 Received chunk: {type(chunk)}")
                
                # 🆕 捕获 usage metadata（通常在最后一个 chunk）
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    um = chunk.usage_metadata
                    usage_metadata = {
                        "prompt_tokens": getattr(um, 'prompt_token_count', 0),
                        "completion_tokens": getattr(um, 'candidates_token_count', 0),
                        "total_tokens": getattr(um, 'total_token_count', 0),
                        "thoughts_tokens": getattr(um, 'thoughts_token_count', 0) if hasattr(um, 'thoughts_token_count') else 0
                    }
                    logger.info(f"📊 Gemini usage captured: {usage_metadata}")
                
                if hasattr(chunk, 'candidates') and chunk.candidates:
                    candidate = chunk.candidates[0]
                    logger.debug(f"🔍 Candidate has content: {hasattr(candidate, 'content')}")
                    
                    if hasattr(candidate, 'content') and candidate.content:
                        has_parts = hasattr(candidate.content, 'parts')
                        parts_count = len(candidate.content.parts) if has_parts and candidate.content.parts else 0
                        logger.debug(f"🔍 Content has {parts_count} parts")
                        
                        if not has_parts or not candidate.content.parts:
                            # 🔧 修复：最后一个chunk可能没有parts，这是正常的
                            # 它只包含metadata（usage等），继续等待stream完成
                            logger.debug(f"ℹ️  Chunk has no parts (likely final metadata chunk), skipping")
                            continue
                            
                        for part in candidate.content.parts:
                            # 🔧 修复：正确区分thinking和content
                            # Gemini API: 当有thought属性时，表示这是thinking部分
                            has_thought_attr = hasattr(part, 'thought')
                            
                            # 🔧 关键修复：当thought=True时，表示这是带thinking的常规内容
                            # 只有thought是非空字符串时才是纯thinking部分
                            thought = getattr(part, 'thought', None)
                            text = getattr(part, 'text', None)
                            
                            # 🔍 调试日志
                            logger.debug(f"🔍 Part - has_thought: {has_thought_attr}, thought type: {type(thought)}, thought value: {thought}, text preview: {text[:50] if text else None}")
                            
                            if isinstance(thought, str) and thought:
                                # thought是非空字符串，这是纯thinking内容
                                logger.info(f"🧠 Thinking chunk: {len(thought)} chars, preview: {thought[:50]}")
                                thinking_accumulated.append(thought)
                                
                                # 🔥 流式发送 thinking（支持实时显示）
                                import asyncio
                                chunk_size = 30
                                for i in range(0, len(thought), chunk_size):
                                    mini_chunk = thought[i:i+chunk_size]
                                    yield {
                                        "type": "thinking",
                                        "content": mini_chunk,  # 🔧 统一使用 "content"
                                        "accumulated": "".join(thinking_accumulated)
                                    }
                                    await asyncio.sleep(0.02)  # 🆕 打字机效果
                            elif text:
                                # 🔍 检查text是否是markdown thinking（以**开头）
                                if text.strip().startswith('**') and not text.strip().startswith('```'):
                                    # 这是markdown格式的thinking内容
                                    logger.info(f"🧠 Thinking chunk (from text): {len(text)} chars, preview: {text[:50]}")
                                    thinking_accumulated.append(text)
                                    
                                    # 🔥 流式发送 thinking（带延迟）
                                    import asyncio
                                    chunk_size = 30
                                    for i in range(0, len(text), chunk_size):
                                        mini_chunk = text[i:i+chunk_size]
                                        yield {
                                            "type": "thinking",
                                            "content": mini_chunk,  # 🔧 统一使用 "content"
                                            "accumulated": "".join(thinking_accumulated)
                                        }
                                        await asyncio.sleep(0.02)  # 🆕 打字机效果
                                else:
                                    # 有text内容，这是实际输出
                                    logger.info(f"📝 Content chunk: {len(text)} chars, preview: {text[:50]}")
                                    content_accumulated.append(text)
                                    
                                    # 🔥 流式发送 content（带打字机延迟效果）
                                    import asyncio
                                    chunk_size = 30  # 每次发送的字符数
                                    for i in range(0, len(text), chunk_size):
                                        mini_chunk = text[i:i+chunk_size]
                                        yield {
                                            "type": "content",
                                            "content": mini_chunk,  # 🔧 修复：使用 "content" 而不是 "text"
                                            "accumulated": "".join(content_accumulated)
                                        }
                                        # 🆕 添加小延迟实现打字机效果 (约 30ms)
                                        await asyncio.sleep(0.03)
            
            # 🔧 关键修复：确保 done 事件一定会发送
            logger.info(f"🏁 Stream loop completed, sending done event")
            logger.info(f"📊 Final accumulated - thinking: {len(''.join(thinking_accumulated))} chars, content: {len(''.join(content_accumulated))} chars")
            
            # 🆕 发送 usage 事件（与 Kimi 格式统一）
            final_thinking = "".join(thinking_accumulated)
            final_content = "".join(content_accumulated)
            
            # 使用实际的 usage metadata（如果有），否则从 chars 估算
            if usage_metadata:
                yield {
                    "type": "usage",
                    "usage": {
                        "prompt_tokens": usage_metadata.get("prompt_tokens", 0),
                        "completion_tokens": usage_metadata.get("completion_tokens", 0),
                        "total_tokens": usage_metadata.get("total_tokens", 0),
                        "thinking_chars": len(final_thinking),
                        "content_chars": len(final_content),
                        "model": model,
                        "source": "api"  # 标记为 API 精确数据
                    }
                }
                logger.info(f"📊 Token Usage (Gemini Stream - EXACT)")
                logger.info(f"   • Input:  {usage_metadata.get('prompt_tokens', 0):,} tokens")
                logger.info(f"   • Output: {usage_metadata.get('completion_tokens', 0):,} tokens")
                logger.info(f"   • Total:  {usage_metadata.get('total_tokens', 0):,} tokens")
            else:
                # Fallback: 从 chars 估算 tokens（中文约 0.5 token/char）
                estimated_output = int((len(final_thinking) + len(final_content)) * 0.5)
                yield {
                    "type": "usage",
                    "usage": {
                        "prompt_tokens": 0,  # 无法估算
                        "completion_tokens": estimated_output,
                        "total_tokens": estimated_output,
                        "thinking_chars": len(final_thinking),
                        "content_chars": len(final_content),
                        "model": model,
                        "source": "estimated"
                    }
                }
                logger.info(f"📊 Token Usage (Gemini Stream - ESTIMATED from {len(final_content)} chars)")
                logger.info(f"   • Output: ~{estimated_output:,} tokens (estimated)")
            
            # 完成标记
            yield {
                "type": "done",
                "thinking": final_thinking,
                "content": final_content
            }
            
            logger.info(f"✅ Streaming generation complete")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Streaming generation error: {e}")
            
            # 检测503错误（API过载）
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
    
    async def generate(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash",  # 🆕 使用 2.5 Flash 支持思考模型
        response_format: str = "text",
        max_tokens: int = 2000,
        temperature: float = 0.7,
        max_retries: int = 3,
        thinking_budget: Optional[int] = 1024,  # 🆕 思考预算，默认 1024 tokens
        return_thinking: bool = True,  # 🆕 是否返回思考过程
        file_uris: Optional[List[str]] = None  # 🆕 支持多模态输入（图片/文档 URI）
    ) -> Dict[str, Any]:
        """
        生成文本内容（异步）- 🆕 支持思考模型和多模态输入
        
        Args:
            prompt: 提示词
            model: 模型名称，默认 gemini-2.5-flash （2.0 Flash Exp）
            response_format: 响应格式，"text" 或 "json"
            max_tokens: 最大 token 数
            temperature: 温度参数（0-1），越高越随机
            max_retries: 最大重试次数
            thinking_budget: 思考预算（tokens），0 = 无思考，1024 = 中等，最大 24576
            return_thinking: 是否返回思考过程
            file_uris: GCS 文件 URI 列表，支持图片和文档
        
        Returns:
            Dict[str, Any]: 包含以下键：
                - "content": 生成的文本或 JSON 字符串
                - "thinking": 思考过程（如果有）
                - "usage": Token 使用统计
        
        Raises:
            Exception: API 调用失败
        """
        # 如果请求 JSON 格式，在 prompt 中明确说明
        if response_format == "json":
            prompt = self._enhance_json_prompt(prompt)
        
        # 配置生成参数
        config_kwargs = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        
        # 🆕 思考配置：当 thinking_budget=0 时禁用思考模式
        # 这对于需要更多输出 tokens 的场景很重要（如复杂数学题解答）
        if "2.5" in model and thinking_budget is not None:
            try:
                if thinking_budget == 0:
                    # 禁用思考模式
                    config_kwargs["thinking_config"] = types.ThinkingConfig(
                        thinking_budget=0
                    )
                    logger.info(f"🧠 Thinking disabled (budget=0)")
                elif thinking_budget > 0:
                    # 启用思考模式并设置预算
                    config_kwargs["thinking_config"] = types.ThinkingConfig(
                        thinking_budget=thinking_budget
                    )
                    logger.info(f"🧠 Thinking enabled (budget={thinking_budget})")
            except Exception as e:
                logger.warning(f"⚠️ ThinkingConfig not supported in this SDK version: {e}")
        
        config = types.GenerateContentConfig(**config_kwargs)
        
        # 🆕 构建多模态内容（支持图片/文档 + 文字）
        contents = self._build_multimodal_contents(prompt, file_uris)
        
        # 重试逻辑
        for attempt in range(max_retries):
            try:
                if file_uris:
                    logger.info(f"🤖 Calling Gemini API: model={model}, tokens<={max_tokens}, files={len(file_uris)}")
                else:
                    logger.info(f"🤖 Calling Gemini API: model={model}, tokens<={max_tokens}")
                start_time = time.time()
                
                # 使用异步客户端调用 API（支持多模态）
                response = await self.async_client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config
                )
                
                # 🆕 改进的响应检查
                raw_text = getattr(response, 'text', None) or ""
                
                if not raw_text or not raw_text.strip():
                    # 🆕 空响应时，检查是否有 candidates
                    if hasattr(response, 'candidates') and response.candidates:
                        # 尝试从 candidates 提取内容
                        for candidate in response.candidates:
                            if hasattr(candidate, 'content') and candidate.content:
                                parts = getattr(candidate.content, 'parts', [])
                                for part in parts:
                                    if hasattr(part, 'text') and part.text:
                                        raw_text = part.text
                                        break
                    
                    if not raw_text or not raw_text.strip():
                        logger.warning(f"⚠️ Empty response from Gemini (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue  # 重试
                        raise ValueError("Empty response from Gemini API after all retries")
                
                result = raw_text.strip()
                elapsed = time.time() - start_time
                
                # 🆕 提取思考过程
                thinking_process = None
                if return_thinking:
                    thinking_process = self._extract_thinking(response)
                
                # ============= Token 使用统计 =============
                usage_metadata = getattr(response, 'usage_metadata', None)
                usage_stats = {}
                
                if usage_metadata:
                    # 🔧 使用 `or 0` 确保值不为 None（API 有时返回 None 而非 0）
                    input_tokens = getattr(usage_metadata, 'prompt_token_count', 0) or 0
                    output_tokens = getattr(usage_metadata, 'candidates_token_count', 0) or 0
                    total_tokens = getattr(usage_metadata, 'total_token_count', 0) or 0
                    thoughts_tokens = getattr(usage_metadata, 'thoughts_token_count', 0) or 0  # 🆕 思考 tokens
                    
                    usage_stats = {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "thoughts_tokens": thoughts_tokens,
                        "total_tokens": total_tokens
                    }
                    
                    log_msg = (
                        f"📊 Token Usage | Input: {input_tokens:,} | Output: {output_tokens:,}"
                    )
                    if thoughts_tokens > 0:
                        log_msg += f" | Thoughts: {thoughts_tokens:,} 🧠"
                    log_msg += f" | Total: {total_tokens:,} | Time: {elapsed:.2f}s | Model: {model}"
                    
                    logger.info(log_msg)
                else:
                    logger.info(f"✅ Gemini response received in {elapsed:.2f}s, length={len(result)}")
                
                # 如果是 JSON 格式，尝试解析验证
                if response_format == "json":
                    # 🆕 先检查是否为空
                    if not result or not result.strip():
                        logger.warning(f"⚠️ Empty result before JSON extraction (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue  # 重试
                        raise ValueError("Empty response cannot be parsed as JSON")
                    
                    result = self._extract_json(result)
                    
                    # 🆕 提取后再次检查
                    if not result or not result.strip():
                        logger.warning(f"⚠️ Empty result after JSON extraction (attempt {attempt + 1}/{max_retries})")
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue  # 重试
                        raise ValueError("No valid JSON found in response")
                    
                    try:
                        # 验证是否为有效 JSON
                        json.loads(result)
                        # ✅ 验证成功，继续到最后返回字典格式
                    except json.JSONDecodeError as json_err:
                        # JSON解析失败，记录原始响应
                        logger.warning(f"⚠️ JSON parsing failed (attempt {attempt + 1}/{max_retries}): {json_err}")
                        logger.warning(f"📝 Raw response ({len(result)} chars): {repr(result[:100])}")
                        
                        # 🔧 首先尝试修复 JSON（处理无效转义字符等问题）
                        try:
                            fixed_result = self._try_fix_json(result)
                            json.loads(fixed_result)
                            logger.info(f"✅ JSON auto-fixed successfully (invalid escape chars etc.)")
                            result = fixed_result
                            # 修复成功，跳过后续的垃圾响应检测
                        except Exception as fix_err:
                            logger.warning(f"⚠️ JSON fix attempt failed: {fix_err}")
                            
                            # 🆕 检测垃圾响应（更宽松的检测逻辑）
                            is_garbage = (
                                len(result.strip()) < 15 or  # 太短
                                result.strip().count('{') != result.strip().count('}')  # 括号不匹配
                                # 移除字段检测，因为不同的 skill 有不同的字段
                            )
                            
                            if is_garbage:
                                logger.warning(f"🗑️ Detected garbage response (len={len(result)}), using fallback directly")
                                logger.debug(f"📝 Garbage content: {repr(result[:50])}")
                                
                                # 🆕 对于垃圾响应，安全地返回 'other' 意图
                                result = json.dumps({
                                    "intent": "other",
                                    "topic": None,
                                    "confidence": 0.70,
                                    "note": "Fallback due to garbage LLM response"
                                })
                                logger.info(f"✅ Using fallback intent: other (garbage response)")
                                return {
                                    "content": result,
                                    "thinking": thinking_process if 'thinking_process' in dir() else None,
                                    "usage": usage_stats if 'usage_stats' in dir() else {}
                                }
                            
                            # 不是垃圾响应，继续重试
                            if attempt < max_retries - 1:
                                time.sleep(2)
                                continue
                        
                        if attempt == max_retries - 1:
                            logger.warning(f"⚠️ Final attempt: trying to fix JSON...")
                            try:
                                fixed_result = self._try_fix_json(result)
                                json.loads(fixed_result)
                                logger.info(f"✅ JSON auto-fixed successfully")
                                result = fixed_result
                            except Exception as fix_err:
                                logger.error(f"❌ Failed to fix JSON: {fix_err}")
                                # 🆕 最后一招：返回一个默认的 JSON 结构
                                logger.warning(f"⚠️ Returning fallback JSON response")
                                result = json.dumps({
                                    "intent": "other",
                                    "topic": None,
                                    "confidence": 0.70,  # 🆕 足够高的置信度，避免触发 clarification
                                    "error": "JSON parsing failed"
                                })
                        else:
                            time.sleep(2)
                            continue  # 重试
                
                # 🆕 返回字典格式（包含思考过程）
                return {
                    "content": result,
                    "thinking": thinking_process,
                    "usage": usage_stats
                }
                
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ JSON parsing failed (attempt {attempt + 1}/{max_retries}): {e}")
                logger.debug(f"Raw result (last 200 chars): ...{result[-200:]}")
                if attempt == max_retries - 1:
                    logger.error("❌ Failed to parse JSON after all retries")
                    raise ValueError(f"Invalid JSON response: {str(e)}")
                time.sleep(2 * (attempt + 1))  # 指数退避
                
            except Exception as e:
                logger.error(f"❌ Gemini API error (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {e}")
                if attempt == max_retries - 1:
                    raise
                
                # 指数退避
                wait_time = 2 ** attempt
                logger.info(f"⏳ Retrying in {wait_time}s...")
                time.sleep(wait_time)
        
        raise Exception("Failed to generate content after all retries")
    
    def _download_file(self, uri: str) -> Optional[bytes]:
        """
        🆕 统一的文件下载方法（自动识别 HTTP URL 或 GCS URI）
        
        Args:
            uri: 文件 URL 或 GCS URI
        
        Returns:
            文件二进制数据或 None
        """
        # 检测 URI 类型
        if uri.startswith(("http://", "https://")):
            # HTTP/HTTPS URL（如 StudyX OSS）
            return self._download_from_url(uri)
        elif uri.startswith("gs://"):
            # GCS URI
            return self._download_file_from_gcs(uri)
        else:
            logger.warning(f"⚠️ Unknown URI scheme: {uri}")
            return None
    
    def _build_multimodal_contents(self, prompt: str, file_uris: Optional[List[str]] = None) -> Any:
        """
        🆕 构建多模态内容（支持图片/文档 + 文字）
        
        支持的 URI 类型：
        - HTTP/HTTPS URL (如 https://media2.studyxapp.com/xxx.png)
        - GCS URI (如 gs://bucket/path/file.jpg)
        
        Args:
            prompt: 文字提示
            file_uris: 文件 URL/URI 列表
        
        Returns:
            内容列表或纯文字
        """
        if not file_uris:
            return prompt
        
        # 构建多模态内容
        parts = []
        
        for uri in file_uris:
            # 根据文件扩展名确定 MIME 类型
            mime_type = self._get_mime_type(uri)
            
            if mime_type and mime_type.startswith("image/"):
                try:
                    # 🆕 使用统一下载方法（自动识别 HTTP 或 GCS）
                    image_data = self._download_file(uri)
                    if image_data:
                        # 使用 PIL Image 或直接用 bytes
                        part = types.Part.from_bytes(data=image_data, mime_type=mime_type)
                        parts.append(part)
                        logger.info(f"📎 Added image to multimodal content: {uri[:60]}... ({mime_type}, {len(image_data)} bytes)")
                    else:
                        logger.warning(f"⚠️ Failed to download image: {uri}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to add image {uri}: {e}")
            elif mime_type and mime_type == "application/pdf":
                # 🆕 支持 PDF 文件
                try:
                    pdf_data = self._download_file(uri)
                    if pdf_data:
                        part = types.Part.from_bytes(data=pdf_data, mime_type=mime_type)
                        parts.append(part)
                        logger.info(f"📎 Added PDF to multimodal content: {uri[:60]}... ({mime_type}, {len(pdf_data)} bytes)")
                    else:
                        logger.warning(f"⚠️ Failed to download PDF: {uri}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to add PDF {uri}: {e}")
            elif mime_type and mime_type in ["text/plain", "application/msword", 
                                              "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
                # 🆕 支持文本文件和 Word 文档
                try:
                    file_data = self._download_file(uri)  # 🔧 使用统一下载方法
                    if file_data:
                        # 对于文本文件，尝试解码并作为文本添加
                        if mime_type == "text/plain":
                            try:
                                text_content = file_data.decode('utf-8')
                                parts.append(f"[文件内容 - {uri.split('/')[-1]}]:\n{text_content}")
                                logger.info(f"📎 Added text file to content: {uri[:60]}... ({len(text_content)} chars)")
                            except:
                                part = types.Part.from_bytes(data=file_data, mime_type=mime_type)
                                parts.append(part)
                                logger.info(f"📎 Added text file as binary: {uri[:60]}...")
                        else:
                            # Word 文档作为二进制处理
                            part = types.Part.from_bytes(data=file_data, mime_type=mime_type)
                            parts.append(part)
                            logger.info(f"📎 Added document to multimodal content: {uri[:60]}... ({mime_type}, {len(file_data)} bytes)")
                    else:
                        logger.warning(f"⚠️ Failed to download file: {uri}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to add file {uri}: {e}")
            elif mime_type:
                # 其他文件类型 - 尝试通用处理
                try:
                    file_data = self._download_file(uri)  # 🔧 使用统一下载方法
                    if file_data:
                        part = types.Part.from_bytes(data=file_data, mime_type=mime_type)
                        parts.append(part)
                        logger.info(f"📎 Added file to multimodal content: {uri[:60]}... ({mime_type}, {len(file_data)} bytes)")
                    else:
                        logger.warning(f"⚠️ Failed to download file: {uri}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to add file {uri}: {e}")
            else:
                logger.warning(f"⚠️ Unsupported file type: {uri}")
        
        # 添加文字提示
        parts.append(prompt)
        
        return parts
    
    def _convert_gcs_to_https(self, gcs_uri: str) -> Optional[str]:
        """
        将 GCS URI 转换为 HTTPS URL
        
        Args:
            gcs_uri: GCS URI (gs://studyx_test/temp/xxx/yyy.jpg)
        
        Returns:
            HTTPS URL (https://files.istudyx.com/temp/xxx/yyy.jpg)
        """
        if not gcs_uri.startswith("gs://"):
            return None
        
        # gs://studyx_test/temp/8c77f68a/xxx.jpg -> temp/8c77f68a/xxx.jpg
        path = gcs_uri[5:]  # 去掉 "gs://"
        parts = path.split("/", 1)
        if len(parts) < 2:
            return None
        
        bucket_name = parts[0]
        blob_path = parts[1]
        
        # 🆕 特殊处理 studyx_test bucket -> files.istudyx.com
        if bucket_name == "studyx_test":
            return f"https://files.istudyx.com/{blob_path}"
        
        # 其他 bucket 使用 Google Cloud Storage 公开 URL
        return f"https://storage.googleapis.com/{bucket_name}/{blob_path}"
    
    def _download_from_url(self, url: str) -> Optional[bytes]:
        """
        🆕 从 HTTP/HTTPS URL 下载文件（支持 StudyX OSS 等外部 URL）
        
        Args:
            url: HTTP/HTTPS URL (如 https://media2.studyxapp.com/temp/xxx.png)
        
        Returns:
            文件二进制数据或 None
        """
        import requests
        
        try:
            logger.info(f"📥 Downloading from HTTP URL: {url[:80]}...")
            response = requests.get(url, timeout=60, headers={
                "User-Agent": "Mozilla/5.0 (compatible; SkillAgent/1.0)"
            })
            if response.status_code == 200:
                file_data = response.content
                logger.info(f"✅ Downloaded file from URL: {url[:50]}... ({len(file_data)} bytes)")
                return file_data
            else:
                logger.warning(f"⚠️ HTTP download failed ({response.status_code}): {url}")
                return None
        except Exception as e:
            logger.error(f"❌ Failed to download from URL: {url}, error: {e}")
            return None
    
    def _download_file_from_gcs(self, gcs_uri: str) -> Optional[bytes]:
        """
        从 GCS 下载文件（优先使用 HTTPS URL，无需认证）
        支持图片、PDF、文档等各种文件类型
        
        Args:
            gcs_uri: GCS URI (gs://bucket/path/to/file)
        
        Returns:
            文件二进制数据或 None
        """
        import requests
        
        try:
            # 🆕 优先转换为 HTTPS URL 下载（无需 GCS 认证）
            https_url = self._convert_gcs_to_https(gcs_uri)
            if https_url:
                logger.info(f"🔄 Converting GCS URI to HTTPS: {gcs_uri} -> {https_url}")
                response = requests.get(https_url, timeout=60)  # 文件可能较大，增加超时
                if response.status_code == 200:
                    file_data = response.content
                    logger.info(f"✅ Downloaded file via HTTPS: {https_url} ({len(file_data)} bytes)")
                    return file_data
                else:
                    logger.warning(f"⚠️ HTTPS download failed ({response.status_code}), trying GCS client...")
            
            # Fallback: 使用 GCS 客户端（需要认证）
            from google.cloud import storage
            
            # 解析 GCS URI
            if not gcs_uri.startswith("gs://"):
                logger.error(f"❌ Invalid GCS URI: {gcs_uri}")
                return None
            
            path = gcs_uri[5:]  # 去掉 "gs://"
            parts = path.split("/", 1)
            if len(parts) < 2:
                logger.error(f"❌ Invalid GCS path: {gcs_uri}")
                return None
            
            bucket_name = parts[0]
            blob_name = parts[1]
            
            # 下载文件
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            
            file_data = blob.download_as_bytes()
            logger.info(f"✅ Downloaded file from GCS: {gcs_uri} ({len(file_data)} bytes)")
            return file_data
            
        except Exception as e:
            logger.error(f"❌ Failed to download file: {gcs_uri}, error: {e}")
            return None
    
    def _download_gcs_image(self, gcs_uri: str) -> Optional[bytes]:
        """
        从 GCS 下载图片（调用通用文件下载方法）
        
        Args:
            gcs_uri: GCS URI (gs://bucket/path/to/image.jpg)
        
        Returns:
            图片二进制数据或 None
        """
        return self._download_file_from_gcs(gcs_uri)
    
    def _get_mime_type(self, uri: str) -> Optional[str]:
        """
        根据文件 URI 获取 MIME 类型
        
        Args:
            uri: 文件 URI
        
        Returns:
            MIME 类型或 None
        """
        uri_lower = uri.lower()
        
        # 图片类型
        if uri_lower.endswith('.jpg') or uri_lower.endswith('.jpeg'):
            return "image/jpeg"
        elif uri_lower.endswith('.png'):
            return "image/png"
        elif uri_lower.endswith('.gif'):
            return "image/gif"
        elif uri_lower.endswith('.webp'):
            return "image/webp"
        
        # 文档类型
        elif uri_lower.endswith('.pdf'):
            return "application/pdf"
        elif uri_lower.endswith('.txt'):
            return "text/plain"
        
        # 未知类型 - 尝试作为文本处理
        else:
            logger.warning(f"⚠️ Unknown file type for {uri}, treating as text/plain")
            return "text/plain"
    
    def _enhance_json_prompt(self, prompt: str) -> str:
        """
        增强 prompt 以获得 JSON 格式输出
        
        Args:
            prompt: 原始 prompt
        
        Returns:
            str: 增强后的 prompt
        """
        if "JSON" in prompt.upper() or "json" in prompt:
            # 已经包含 JSON 指示
            return prompt
        
        return f"""{prompt}

IMPORTANT: You must respond with valid JSON only. Do not include any text before or after the JSON object.
Example format: {{"key": "value"}}

Your JSON response:"""
    
    def _try_fix_json(self, text: str) -> str:
        """
        尝试修复常见的 JSON 错误（增强版）
        
        处理的错误类型：
        1. Markdown 代码块
        2. 注释 (// 和 /* */)
        3. 尾随逗号
        4. 单引号
        5. 未终止的字符串 (Unterminated string)
        6. 不完整的 JSON
        7. 🆕 无效的转义字符 (Invalid \escape)
        """
        import re
        
        original_text = text  # 保存原始文本用于调试
        
        # 🆕 修复无效的转义字符 (Invalid \escape)
        # JSON 只允许: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
        # 其他的 \x 需要转换为 \\x 或直接移除反斜杠
        def fix_invalid_escapes(s):
            """修复 JSON 字符串中的无效转义字符"""
            result = []
            i = 0
            while i < len(s):
                if s[i] == '\\' and i + 1 < len(s):
                    next_char = s[i + 1]
                    # 有效的转义字符
                    if next_char in '"\\\/bfnrt':
                        result.append(s[i:i+2])
                        i += 2
                    # Unicode 转义
                    elif next_char == 'u' and i + 5 < len(s):
                        result.append(s[i:i+6])
                        i += 6
                    else:
                        # 无效的转义字符，移除反斜杠或转换为双反斜杠
                        # 直接保留原字符，移除反斜杠
                        result.append(next_char)
                        i += 2
                        logger.debug(f"🔧 Fixed invalid escape: \\{next_char} -> {next_char}")
                else:
                    result.append(s[i])
                    i += 1
            return ''.join(result)
        
        text = fix_invalid_escapes(text)
        
        # 移除可能的 markdown 代码块
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        # 尝试移除 JSON 中的注释（// 和 /* */）
        # 移除单行注释
        text = re.sub(r'//[^\n]*\n', '\n', text)
        # 移除多行注释
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        
        # 移除尾随逗号（JSON 中最常见的错误）
        # 1. 对象中的尾随逗号: , }
        text = re.sub(r',(\s*})', r'\1', text)
        # 2. 数组中的尾随逗号: , ]
        text = re.sub(r',(\s*\])', r'\1', text)
        
        # 修复单引号为双引号（如果有的话）
        # 但要小心不要改变字符串内部的单引号
        # 简单策略：只替换键名的单引号
        text = re.sub(r"'([^']*)'(\s*):", r'"\1"\2:', text)
        
        # 🆕 处理 Unterminated string 错误
        # 常见情况：JSON 被截断，字符串没有结束引号
        # 尝试在合适的位置补充引号和括号
        
        # 检查是否有未闭合的字符串
        in_string = False
        escape_next = False
        last_quote_pos = -1
        
        for i, char in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if char == '\\':
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                if in_string:
                    last_quote_pos = i
        
        # 如果字符串未闭合，尝试修复
        if in_string and last_quote_pos >= 0:
            # 找到最后一个有效的位置（非转义字符）
            # 在字符串末尾添加引号
            text = text.rstrip()
            # 移除末尾可能的不完整转义字符
            while text.endswith('\\'):
                text = text[:-1]
            text += '"'
            logger.debug(f"🔧 Fixed unterminated string by adding closing quote")
        
        # 尝试找到最后一个完整的 JSON 对象或数组
        # 从后往前找最后一个 } 或 ]
        last_brace = text.rfind('}')
        last_bracket = text.rfind(']')
        
        if last_brace > last_bracket:
            # 对象
            text = text[:last_brace + 1]
        elif last_bracket > last_brace:
            # 数组
            text = text[:last_bracket + 1]
        else:
            # 🆕 没有找到完整的括号，尝试补充
            # 检查开始是对象还是数组
            first_brace = text.find('{')
            first_bracket = text.find('[')
            
            if first_brace >= 0 and (first_bracket < 0 or first_brace < first_bracket):
                # 是对象，计算需要补充的 }
                open_count = text.count('{') - text.count('}')
                if open_count > 0:
                    text += '}' * open_count
                    logger.debug(f"🔧 Added {open_count} closing braces")
            elif first_bracket >= 0:
                # 是数组，计算需要补充的 ]
                open_count = text.count('[') - text.count(']')
                if open_count > 0:
                    text += ']' * open_count
                    logger.debug(f"🔧 Added {open_count} closing brackets")
        
        # 🆕 特殊情况：如果文本非常短且像是被截断的 intent 响应
        # 直接构造一个默认响应
        if len(text) < 20 and '{' not in text:
            logger.warning(f"⚠️ Text too short to be valid JSON: {text[:50]}")
            # 尝试从原始文本中提取可能的 intent 关键词
            text_lower = original_text.lower()
            if 'quiz' in text_lower or '题' in original_text:
                return '{"intent": "quiz_request", "topic": null, "confidence": 0.6}'
            elif 'flashcard' in text_lower or '闪卡' in original_text or '卡片' in original_text:
                return '{"intent": "flashcard_request", "topic": null, "confidence": 0.6}'
            elif 'explain' in text_lower or '讲解' in original_text or '解释' in original_text:
                return '{"intent": "explain_request", "topic": null, "confidence": 0.6}'
            else:
                return '{"intent": "other", "topic": null, "confidence": 0.5}'
        
        return text
    
    def _extract_json(self, text: str) -> str:
        """
        从文本中提取 JSON 内容（改进版，处理多余内容）
        
        Args:
            text: 可能包含 JSON 的文本
        
        Returns:
            str: 提取的 JSON 字符串
        """
        text = text.strip()
        
        # 移除可能的 markdown 代码块标记
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        
        text = text.strip()
        
        # 尝试找到完整的 JSON 对象或数组
        # 使用简单的括号匹配来找到完整的 JSON
        
        # 优先检查对象
        if "{" in text:
            start = text.find("{")
            depth = 0
            in_string = False
            escape_next = False
            
            for i in range(start, len(text)):
                char = text[i]
                
                # 处理字符串中的引号
                if char == '"' and not escape_next:
                    in_string = not in_string
                elif char == '\\' and not escape_next:
                    escape_next = True
                    continue
                
                if not in_string:
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            # 找到完整的 JSON 对象
                            return text[start:i+1]
                
                escape_next = False
        
        # 如果没有找到对象，检查数组
        if "[" in text:
            start = text.find("[")
            depth = 0
            in_string = False
            escape_next = False
            
            for i in range(start, len(text)):
                char = text[i]
                
                if char == '"' and not escape_next:
                    in_string = not in_string
                elif char == '\\' and not escape_next:
                    escape_next = True
                    continue
                
                if not in_string:
                    if char == '[':
                        depth += 1
                    elif char == ']':
                        depth -= 1
                        if depth == 0:
                            # 找到完整的 JSON 数组
                            return text[start:i+1]
                
                escape_next = False
        
        # 如果都没找到，返回原始文本
        return text
    
    async def generate_json(
        self,
        prompt: str,
        model: str = "gemini-2.5-flash",
        max_tokens: int = 2000,
        temperature: float = 0.7,
        max_retries: int = 3
    ) -> str:
        """
        生成 JSON 格式内容（快捷方法）
        
        Args:
            prompt: 提示词
            model: 模型名称
            max_tokens: 最大 token 数
            temperature: 温度参数
            max_retries: 最大重试次数
        
        Returns:
            str: JSON 字符串
        """
        return await self.generate(
            prompt=prompt,
            model=model,
            response_format="json",
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=max_retries
        )
    
    async def generate_batch(
        self,
        prompts: List[str],
        model: str = "gemini-2.5-flash",
        **kwargs
    ) -> List[str]:
        """
        批量生成（串行执行）
        
        Args:
            prompts: prompt 列表
            model: 模型名称
            **kwargs: 其他参数
        
        Returns:
            List[str]: 生成结果列表
        """
        results = []
        for i, prompt in enumerate(prompts):
            logger.info(f"📝 Processing batch {i + 1}/{len(prompts)}")
            result = await self.generate(prompt, model=model, **kwargs)
            results.append(result)
        
        return results
    
    def get_model_info(self, model_name: str = "gemini-2.5-flash") -> Dict[str, Any]:
        """
        获取模型信息
        
        Args:
            model_name: 模型名称
        
        Returns:
            Dict: 模型信息
        """
        try:
            # 使用新 SDK 的方式
            return {
                "name": model_name,
                "status": "available",
                "note": "Using new google.genai SDK"
            }
        except Exception as e:
            logger.error(f"❌ Failed to get model info: {e}")
            return {"error": str(e)}
    
    def _extract_thinking(self, response) -> Optional[str]:
        """
        从 Gemini 响应中提取思考过程
        
        Args:
            response: Gemini API 响应对象
        
        Returns:
            Optional[str]: 思考过程文本，如果没有则返回 None
        """
        try:
            # 尝试从响应中提取 candidates
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                
                # 检查 content.parts
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    for part in candidate.content.parts:
                        # 查找 thought 属性（可能是字符串或布尔）
                        if hasattr(part, 'thought'):
                            thought = part.thought
                            # 检查是否为字符串类型
                            if isinstance(thought, str) and thought:
                                logger.info(f"🧠 Thinking process found: {len(thought)} chars")
                                return thought
                            # 如果是布尔值 True，查找 text
                            elif thought is True and hasattr(part, 'text'):
                                text = part.text
                                if text:
                                    logger.info(f"🧠 Thinking process found (via text): {len(text)} chars")
                                    return text
                        
                        # 备选方案：检查 part 的其他属性
                        if hasattr(part, 'text') and part.text:
                            # 如果 text 包含思考标记
                            text = part.text
                            if text.startswith("<thinking>") or text.startswith("思考过程:"):
                                logger.info(f"🧠 Thinking process found in text: {len(text)} chars")
                                return text
            
            # 如果没有找到，返回 None
            logger.debug("ℹ️  No thinking process found in response")
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to extract thinking process: {e}")
            return None
    
    async def close(self):
        """关闭异步客户端"""
        try:
            if hasattr(self, 'async_client') and hasattr(self.async_client, 'aclose'):
                await self.async_client.aclose()
                logger.info("✅ Async client closed")
            else:
                logger.info("ℹ️  Async client does not require explicit close")
        except Exception as e:
            logger.warning(f"⚠️ Error closing async client: {e}")
