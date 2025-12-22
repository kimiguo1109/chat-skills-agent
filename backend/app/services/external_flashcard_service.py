"""
External Flashcard Service - 外部闪卡生成API服务

调用外部 API 生成闪卡，替代 LLM 生成逻辑。
"""

import logging
import aiohttp
from typing import Dict, Any, Optional, List

from app.config import settings
from app.core.request_context import get_user_api_token

logger = logging.getLogger(__name__)


class ExternalFlashcardService:
    """外部闪卡生成服务"""
    
    def __init__(
        self, 
        api_url: Optional[str] = None,
        api_token: Optional[str] = None
    ):
        """
        初始化外部闪卡服务
        
        Args:
            api_url: API 端点 URL（默认从 settings 读取）
            api_token: API 认证 Token（默认从 settings 读取）
        """
        self.api_url = api_url or settings.EXTERNAL_FLASHCARD_API_URL
        self.api_token = api_token or settings.EXTERNAL_API_TOKEN
    
    async def create_flashcards(
        self,
        text: str,
        card_size: Optional[int] = None,
        output_language: Optional[str] = None,
        file_uri: Optional[str] = None,
        file_uris: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        调用外部 API 生成闪卡
        
        Args:
            text: 输入文本内容（用户的学习主题或参考内容）
            card_size: 生成闪卡数量（可选，不传则由 API 自动决定）
            output_language: 输出语言（可选，如 "中文"、"英语"、"印尼语"）
            file_uri: GCS 文件 URI（可选，如 "gs://kimi-dev/xxx.txt"）
        
        Returns:
            Dict: 闪卡结果，格式为:
                {
                    "title": "标题",
                    "cardList": [
                        {"front": "正面", "back": "背面"},
                        ...
                    ]
                }
        
        Raises:
            Exception: API 调用失败时抛出异常
        """
        # 构建请求体 - 支持 text 和多个 fileUri
        input_list = []
        
        # 添加文本输入
        if text:
            input_list.append({"text": text})
        
        # 🆕 支持多文件：合并 file_uri 和 file_uris 并去重
        all_file_uris = []
        if file_uri:
            all_file_uris.append(file_uri)
        if file_uris:
            all_file_uris.extend(file_uris)
        # 去重（保持顺序）
        all_file_uris = list(dict.fromkeys(all_file_uris))
        
        # 添加所有文件 URI
        for uri in all_file_uris:
            input_list.append({"fileUri": uri})
        
        # 至少需要一个输入
        if not input_list:
            input_list.append({"text": "生成闪卡"})
        
        request_body = {
            "inputList": input_list
        }
        
        # 如果指定了卡片数量，添加到请求中
        if card_size is not None:
            request_body["cardSize"] = card_size
        
        # 如果指定了输出语言，添加到请求中
        if output_language:
            request_body["outLanguage"] = output_language
        
        # 🆕 优先使用请求上下文中的用户 token，否则使用配置的默认 token
        user_token = get_user_api_token()
        effective_token = user_token or self.api_token
        
        headers = {
            "token": effective_token,
            "Content-Type": "application/json"
        }
        
        logger.info(f"{'='*60}")
        logger.info(f"🌐 EXTERNAL FLASHCARD API CALL")
        if user_token:
            logger.info(f"   • Using user token from headers")
        logger.info(f"{'='*60}")
        logger.info(f"📤 INPUT:")
        logger.info(f"   • Text: {text[:100] if text else 'N/A'}{'...' if text and len(text) > 100 else ''}")
        logger.info(f"   • FileUris: {all_file_uris if all_file_uris else 'N/A'}")
        logger.info(f"   • CardSize: {card_size if card_size else 'auto'}")
        logger.info(f"   • Language: {output_language if output_language else 'auto'}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    json=request_body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    response_data = await response.json()
                    
                    if response.status != 200:
                        logger.error(f"❌ External API error: {response.status} - {response_data}")
                        raise Exception(f"External API error: {response.status}")
                    
                    if response_data.get("code") != 0:
                        error_msg = response_data.get("msg", "Unknown error")
                        logger.error(f"❌ External API business error: {error_msg}")
                        raise Exception(f"External API business error: {error_msg}")
                    
                    # 提取 data 部分
                    data = response_data.get("data", {})
                    card_list = data.get("cardList", [])
                    
                    logger.info(f"{'─'*60}")
                    logger.info(f"📥 OUTPUT:")
                    logger.info(f"   • Title: {data.get('title', 'N/A')}")
                    logger.info(f"   • Cards: {len(card_list)} 张")
                    for i, card in enumerate(card_list, 1):
                        logger.info(f"   • Card {i}: {card.get('front', '')[:30]}...")
                    logger.info(f"{'='*60}")
                    logger.info(f"✅ EXTERNAL API SUCCESS")
                    logger.info(f"{'='*60}")
                    
                    return {
                        "title": data.get("title", ""),
                        "cardList": card_list
                    }
                    
        except aiohttp.ClientError as e:
            logger.error(f"❌ Network error calling external API: {e}")
            raise Exception(f"Network error: {e}")
        except Exception as e:
            logger.error(f"❌ Error calling external flashcard API: {e}")
            raise


# 全局单例
_service_instance: Optional[ExternalFlashcardService] = None


def get_external_flashcard_service() -> ExternalFlashcardService:
    """获取全局 ExternalFlashcardService 实例（单例模式）"""
    global _service_instance
    if _service_instance is None:
        _service_instance = ExternalFlashcardService()
    return _service_instance

