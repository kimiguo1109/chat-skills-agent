"""
Token 统计服务 - 持久化存储 Token 使用记录

功能：
- 按天切分存储 JSON 文件
- 记录每次 API 调用的 token 消耗
- 支持汇总统计
"""

import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, Optional, List
import threading
import asyncio

logger = logging.getLogger(__name__)


class TokenStatsService:
    """Token 统计服务"""
    
    def __init__(self, stats_dir: Optional[str] = None):
        """
        初始化 Token 统计服务
        
        Args:
            stats_dir: 统计文件存储目录，默认为 backend/token_stats/
        """
        if stats_dir:
            self.stats_dir = Path(stats_dir)
        else:
            # 默认存储在 backend/token_stats/
            self.stats_dir = Path(__file__).parent.parent.parent / "token_stats"
        
        # 确保目录存在
        self.stats_dir.mkdir(parents=True, exist_ok=True)
        
        # 线程锁（确保并发安全）
        self._lock = threading.Lock()
        
        logger.info(f"✅ TokenStatsService initialized, stats_dir: {self.stats_dir}")
    
    def _get_today_file(self) -> Path:
        """获取今天的统计文件路径"""
        today = date.today().isoformat()  # 2025-11-27
        return self.stats_dir / f"token_stats_{today}.json"
    
    def _load_today_stats(self) -> Dict[str, Any]:
        """加载今天的统计数据"""
        file_path = self._get_today_file()
        
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"❌ Failed to load stats file: {e}")
                return self._create_empty_stats()
        else:
            return self._create_empty_stats()
    
    def _create_empty_stats(self) -> Dict[str, Any]:
        """创建空的统计结构"""
        return {
            "date": date.today().isoformat(),
            "summary": {
                "total_requests": 0,
                "total_internal_tokens": 0,
                "intent_router_tokens": 0,
                "skill_execution_tokens": 0,
                "memory_operation_tokens": 0,
                "external_api_calls": 0,
                "llm_calls": 0,
                "thinking_model_calls": 0,  # 🆕 思考模型调用次数
                "total_generation_time": 0,  # 🆕 总生成耗时
                "models_used": {}  # 🆕 各模型使用统计
            },
            "records": []
        }
    
    def _save_stats(self, stats: Dict[str, Any]):
        """保存统计数据到文件"""
        file_path = self._get_today_file()
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            logger.debug(f"📝 Saved stats to {file_path.name}")
        except IOError as e:
            logger.error(f"❌ Failed to save stats file: {e}")
    
    def record_usage(
        self,
        user_id: str,
        session_id: str,
        message: str,
        intent: str,
        content_type: str,
        token_usage: Dict[str, Any],
        file_uris: Optional[List[str]] = None
    ):
        """
        记录一次 API 调用的 token 使用
        
        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            message: 用户消息
            intent: 识别的意图
            content_type: 内容类型
            token_usage: Token 使用统计
            file_uris: 附件列表
        """
        with self._lock:
            stats = self._load_today_stats()
            
            # 构建记录
            record = {
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "session_id": session_id,
                "message": message[:100] + ("..." if len(message) > 100 else ""),
                "intent": intent,
                "content_type": content_type,
                "has_files": bool(file_uris),
                "file_count": len(file_uris) if file_uris else 0,
                "token_usage": token_usage
            }
            
            # 添加记录
            stats["records"].append(record)
            
            # 更新汇总
            summary = stats["summary"]
            summary["total_requests"] += 1
            summary["total_internal_tokens"] += token_usage.get("total_internal_tokens", 0)
            summary["intent_router_tokens"] += token_usage.get("intent_router", {}).get("tokens", 0)
            
            skill_exec = token_usage.get("skill_execution", {})
            summary["skill_execution_tokens"] += skill_exec.get("total_tokens", 0)
            
            if skill_exec.get("source") == "external_api":
                summary["external_api_calls"] += 1
            elif skill_exec.get("source") == "llm":
                summary["llm_calls"] += 1
                
                # 🆕 统计思考模型调用
                if skill_exec.get("thinking_mode"):
                    summary["thinking_model_calls"] += 1
                
                # 🆕 统计生成耗时
                summary["total_generation_time"] += skill_exec.get("generation_time", 0)
                
                # 🆕 统计各模型使用情况
                model_name = skill_exec.get("model", "unknown")
                if "models_used" not in summary:
                    summary["models_used"] = {}
                if model_name not in summary["models_used"]:
                    summary["models_used"][model_name] = {"calls": 0, "tokens": 0}
                summary["models_used"][model_name]["calls"] += 1
                summary["models_used"][model_name]["tokens"] += skill_exec.get("total_tokens", 0)
            
            memory_ops = token_usage.get("memory_operations", {})
            summary["memory_operation_tokens"] += (
                memory_ops.get("compression_tokens", 0) + 
                memory_ops.get("summary_tokens", 0)
            )
            
            # 保存
            self._save_stats(stats)
            
            logger.info(
                f"📊 Token usage recorded: user={user_id}, "
                f"intent={intent}, tokens={token_usage.get('total_internal_tokens', 0)}"
            )
    
    def get_today_summary(self) -> Dict[str, Any]:
        """获取今天的汇总统计"""
        stats = self._load_today_stats()
        return {
            "date": stats["date"],
            "summary": stats["summary"]
        }
    
    def get_today_records(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取今天的详细记录"""
        stats = self._load_today_stats()
        records = stats.get("records", [])
        # 返回最近的记录
        return records[-limit:] if len(records) > limit else records
    
    def get_stats_by_date(self, target_date: str) -> Optional[Dict[str, Any]]:
        """
        获取指定日期的统计数据
        
        Args:
            target_date: 日期字符串，格式 YYYY-MM-DD
        
        Returns:
            统计数据，或 None（如果不存在）
        """
        file_path = self.stats_dir / f"token_stats_{target_date}.json"
        
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"❌ Failed to load stats for {target_date}: {e}")
                return None
        else:
            return None
    
    def list_available_dates(self) -> List[str]:
        """列出所有有统计数据的日期"""
        dates = []
        for file in self.stats_dir.glob("token_stats_*.json"):
            # 从文件名提取日期
            date_str = file.stem.replace("token_stats_", "")
            dates.append(date_str)
        return sorted(dates, reverse=True)  # 最新的在前


# 单例模式
_token_stats_service: Optional[TokenStatsService] = None


def get_token_stats_service() -> TokenStatsService:
    """获取 TokenStatsService 单例"""
    global _token_stats_service
    if _token_stats_service is None:
        _token_stats_service = TokenStatsService()
    return _token_stats_service

