"""
Memory Token Tracker - 追踪 Memory 操作消耗的 Token

由于 Memory 压缩是后台异步任务，需要单独追踪其 token 消耗。
这些 token 会在下一次 API 调用时被汇总到统计中。
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
import threading

logger = logging.getLogger(__name__)


class MemoryTokenTracker:
    """追踪 Memory 操作的 Token 消耗"""
    
    def __init__(self):
        self._lock = threading.Lock()
        # 按 user_id 和 session_id 追踪
        self._pending_tokens: Dict[str, Dict[str, Any]] = {}
        # 累计统计（用于当次请求可能已经完成的压缩）
        self._session_totals: Dict[str, Dict[str, int]] = {}
    
    def record_compression(
        self,
        user_id: str,
        session_id: str,
        artifact_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        model: str = "gemini-2.5-flash"
    ):
        """
        记录一次压缩操作的 token 消耗
        
        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            artifact_id: Artifact ID
            prompt_tokens: 输入 tokens
            completion_tokens: 输出 tokens
            total_tokens: 总 tokens
            model: 使用的模型
        """
        with self._lock:
            key = f"{user_id}:{session_id}"
            
            if key not in self._pending_tokens:
                self._pending_tokens[key] = {
                    "records": [],
                    "total_compression_tokens": 0,
                    "total_compression_input": 0,
                    "total_compression_output": 0,
                    "total_summary_tokens": 0
                }
            
            record = {
                "timestamp": datetime.now().isoformat(),
                "artifact_id": artifact_id,
                "operation": "compression",
                "model": model,
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": total_tokens
            }
            
            self._pending_tokens[key]["records"].append(record)
            self._pending_tokens[key]["total_compression_tokens"] += total_tokens
            self._pending_tokens[key]["total_compression_input"] += prompt_tokens
            self._pending_tokens[key]["total_compression_output"] += completion_tokens
            
            logger.info(
                f"📊 Memory compression: artifact={artifact_id}, "
                f"input={prompt_tokens:,}, output={completion_tokens:,}, total={total_tokens:,}"
            )
    
    def record_summary_generation(
        self,
        user_id: str,
        session_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        model: str = "gemini-2.5-flash"
    ):
        """
        记录一次 Summary 生成的 token 消耗
        """
        with self._lock:
            key = f"{user_id}:{session_id}"
            
            if key not in self._pending_tokens:
                self._pending_tokens[key] = {
                    "records": [],
                    "total_compression_tokens": 0,
                    "total_summary_tokens": 0
                }
            
            record = {
                "timestamp": datetime.now().isoformat(),
                "operation": "summary_generation",
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens
            }
            
            self._pending_tokens[key]["records"].append(record)
            self._pending_tokens[key]["total_summary_tokens"] += total_tokens
            
            logger.info(
                f"📊 Memory summary tokens recorded: tokens={total_tokens}, model={model}"
            )
    
    def get_and_clear_tokens(self, user_id: str, session_id: str) -> Dict[str, int]:
        """
        获取并清除某个 session 的 pending tokens
        
        Returns:
            {
                "compression_tokens": int,
                "compression_input": int,
                "compression_output": int,
                "summary_tokens": int,
                "total_memory_tokens": int,
                "operations_count": int
            }
        """
        with self._lock:
            key = f"{user_id}:{session_id}"
            
            if key not in self._pending_tokens:
                return {
                    "compression_tokens": 0,
                    "compression_input": 0,
                    "compression_output": 0,
                    "summary_tokens": 0,
                    "total_memory_tokens": 0,
                    "operations_count": 0
                }
            
            data = self._pending_tokens.pop(key)
            
            return {
                "compression_tokens": data.get("total_compression_tokens", 0),
                "compression_input": data.get("total_compression_input", 0),
                "compression_output": data.get("total_compression_output", 0),
                "summary_tokens": data.get("total_summary_tokens", 0),
                "total_memory_tokens": (
                    data.get("total_compression_tokens", 0) + 
                    data.get("total_summary_tokens", 0)
                ),
                "operations_count": len(data.get("records", []))
            }
    
    def get_tokens(self, user_id: str, session_id: str) -> Dict[str, int]:
        """
        获取某个 session 的 pending tokens（不清除）
        """
        with self._lock:
            key = f"{user_id}:{session_id}"
            
            if key not in self._pending_tokens:
                return {
                    "compression_tokens": 0,
                    "summary_tokens": 0,
                    "total_memory_tokens": 0,
                    "operations_count": 0
                }
            
            data = self._pending_tokens[key]
            
            return {
                "compression_tokens": data.get("total_compression_tokens", 0),
                "summary_tokens": data.get("total_summary_tokens", 0),
                "total_memory_tokens": (
                    data.get("total_compression_tokens", 0) + 
                    data.get("total_summary_tokens", 0)
                ),
                "operations_count": len(data.get("records", []))
            }


# 单例
_memory_token_tracker: Optional[MemoryTokenTracker] = None


def get_memory_token_tracker() -> MemoryTokenTracker:
    """获取 MemoryTokenTracker 单例"""
    global _memory_token_tracker
    if _memory_token_tracker is None:
        _memory_token_tracker = MemoryTokenTracker()
    return _memory_token_tracker

