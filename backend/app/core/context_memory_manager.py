"""
Context Engineering - Memory Manager
上下文缩减和修剪管理器

核心理念:
1. Pruning: 定期清理历史中的冗余 tool calls 和输出
2. Condensation: 递归摘要早期对话轮次
3. Adaptive Loading: 只加载 artifact 索引，不加载完整内容
"""

import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ContextMemoryManager:
    """
    上下文感知的记忆管理器
    
    职责:
    1. 监控 context window 使用率
    2. 修剪(Prune)旧的 tool calls
    3. 递归摘要(Condense)早期对话
    4. 构建轻量级 context（只加载索引）
    """
    
    # Context 使用率阈值
    CONDENSATION_THRESHOLD = 0.7  # 70%
    HARD_LIMIT_THRESHOLD = 0.9    # 90%
    
    # 最多保留几轮完整对话
    MAX_FULL_TURNS = 3
    
    # Token 限制（Kimi k2-thinking 约 128K）
    MAX_CONTEXT_TOKENS = 100000
    
    def __init__(
        self,
        artifact_manager: Any,
        llm_client: Optional[Any] = None
    ):
        """
        初始化 Memory Manager
        
        Args:
            artifact_manager: ContextArtifactManager 实例
            llm_client: LLM 客户端（用于生成摘要）
        """
        self.artifact_manager = artifact_manager
        self.llm_client = llm_client
        
        logger.info("✅ ContextMemoryManager initialized")
    
    def condense_history(
        self,
        messages: List[Dict[str, Any]],
        current_tokens: int
    ) -> List[Dict[str, Any]]:
        """
        压缩历史消息（Pruning + Condensation）
        
        Args:
            messages: 当前的消息历史
            current_tokens: 当前 context token 数
        
        Returns:
            压缩后的消息历史
        """
        utilization = current_tokens / self.MAX_CONTEXT_TOKENS
        
        if utilization < self.CONDENSATION_THRESHOLD:
            # 低于阈值，不需要压缩
            logger.info(f"📊 Context utilization: {utilization:.1%} (< {self.CONDENSATION_THRESHOLD:.0%}) - No condensation needed")
            return messages
        
        logger.info(f"🔄 Context utilization: {utilization:.1%} - Starting condensation...")
        
        # 1. 保留最近 N 轮完整对话
        recent_messages = messages[-self.MAX_FULL_TURNS * 2:]  # 每轮约 2 条消息 (user + assistant)
        
        # 2. 处理早期消息
        early_messages = messages[:-self.MAX_FULL_TURNS * 2]
        
        if not early_messages:
            logger.info("No early messages to condense")
            return recent_messages
        
        # 3. 修剪 tool calls（移除冗长的 tool outputs）
        pruned_messages = self._prune_tool_calls(early_messages)
        
        # 4. 如果仍然太大，进行递归摘要
        if utilization > self.HARD_LIMIT_THRESHOLD:
            logger.info(f"⚠️  Hard limit reached ({utilization:.1%}), performing recursive summarization...")
            summary_message = self._create_recursive_summary(pruned_messages)
            condensed_messages = [summary_message] + recent_messages
        else:
            condensed_messages = pruned_messages + recent_messages
        
        logger.info(f"✅ Condensed {len(messages)} → {len(condensed_messages)} messages")
        return condensed_messages
    
    def _prune_tool_calls(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        修剪 tool calls（保留意图，移除冗长输出）
        
        策略:
        - 保留 user/assistant 消息
        - 对于 tool_call: 保留函数名和参数概要
        - 对于 tool_result: 只保留状态摘要，移除完整输出
        """
        pruned = []
        
        for msg in messages:
            role = msg.get("role")
            
            if role in ["user", "system"]:
                # 保留用户和系统消息
                pruned.append(msg)
            
            elif role == "assistant":
                # 保留 assistant 消息，但简化 tool_calls
                if "tool_calls" in msg:
                    simplified_msg = msg.copy()
                    simplified_msg["tool_calls"] = [
                        {
                            "id": tc.get("id"),
                            "function": {
                                "name": tc.get("function", {}).get("name"),
                                "arguments": "(pruned)"  # 移除详细参数
                            }
                        }
                        for tc in msg["tool_calls"]
                    ]
                    pruned.append(simplified_msg)
                else:
                    pruned.append(msg)
            
            elif role == "tool":
                # 简化 tool 结果
                tool_call_id = msg.get("tool_call_id")
                content = msg.get("content", "")
                
                # 估算大小
                content_len = len(str(content))
                
                if content_len > 500:  # 如果输出很长
                    simplified_content = f"[Tool output: {content_len} chars] Use read_artifact if needed."
                else:
                    simplified_content = content
                
                pruned.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": simplified_content
                })
        
        logger.info(f"✂️  Pruned tool calls: {len(messages)} → {len(pruned)} messages")
        return pruned
    
    def _create_recursive_summary(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        创建递归摘要（将早期对话压缩为一条 narrative summary）
        
        Args:
            messages: 要摘要的消息列表
        
        Returns:
            摘要消息 (role=system)
        """
        if not self.llm_client:
            # 如果没有 LLM，使用简单的规则摘要
            return {
                "role": "system",
                "content": f"[Previous conversation summary: {len(messages)} messages]"
            }
        
        # 构造摘要 prompt
        conversation_text = "\n\n".join([
            f"{msg.get('role')}: {msg.get('content', '')[:500]}"
            for msg in messages
            if msg.get('role') in ['user', 'assistant']
        ])
        
        summary_prompt = f"""Summarize the following conversation into a concise narrative (< 200 tokens):

{conversation_text}

Summary:"""
        
        try:
            response = self.llm_client.generate(
                prompt=summary_prompt,
                temperature=0.3,
                max_tokens=200
            )
            
            summary_content = response.get("content", "") if isinstance(response, dict) else str(response)
            
            logger.info(f"📝 Generated recursive summary: {len(summary_content)} chars")
            
            return {
                "role": "system",
                "content": f"[Conversation Summary]\n{summary_content}"
            }
        
        except Exception as e:
            logger.error(f"❌ Failed to generate summary: {e}")
            return {
                "role": "system",
                "content": f"[Previous conversation: {len(messages)} messages]"
            }
    
    def build_lightweight_context(
        self,
        session_id: str,
        user_query: str
    ) -> Dict[str, Any]:
        """
        构建轻量级 context（只加载 artifact 索引，不加载完整内容）
        
        Args:
            session_id: 会话 ID
            user_query: 用户查询
        
        Returns:
            轻量级 context 字典
        """
        # 获取 artifact 索引
        artifact_index = self.artifact_manager.get_artifact_index(session_id=session_id)
        
        # 构造 context
        context = {
            "session_id": session_id,
            "artifacts_available": len(artifact_index),
            "artifact_index": artifact_index,
            "_note": """
You have access to the following artifacts (indexes only, content not loaded):
- To read full content: use read_artifact(artifact_id)
- To search: use search_artifacts(query)
- To list all: use list_artifacts()
            """.strip()
        }
        
        logger.info(f"📦 Built lightweight context: {len(artifact_index)} artifacts indexed")
        return context
    
    def estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """
        估算消息列表的 token 数
        
        简化估算: 字符数 * 0.8
        """
        total_chars = sum(
            len(str(msg.get("content", ""))) for msg in messages
        )
        return int(total_chars * 0.8)

