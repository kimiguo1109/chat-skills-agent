"""
Context Engineering - Retrieval Tools
为 Agent 提供按需检索能力

提供的工具:
1. read_artifact: 读取指定 artifact 的完整内容
2. search_artifacts: 基于主题/类型搜索 artifacts
3. list_artifacts: 列出所有可用的 artifacts
"""

import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class RetrievalTools:
    """
    检索工具集（供 Agent 使用）
    """
    
    def __init__(self, artifact_manager: Any):
        """
        初始化 Retrieval Tools
        
        Args:
            artifact_manager: ContextArtifactManager 实例
        """
        self.artifact_manager = artifact_manager
        logger.info("✅ RetrievalTools initialized")
    
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        获取工具定义（用于 LLM Function Calling）
        
        Returns:
            工具定义列表（OpenAI Function Calling 格式）
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_artifact",
                    "description": "Read the full content of a specific artifact. Use this when you need detailed information from a previous interaction.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "artifact_id": {
                                "type": "string",
                                "description": "The ID of the artifact to read (e.g., 'artifact_123456')"
                            },
                            "lines": {
                                "type": "object",
                                "description": "Optional: specific line range to read (to save tokens)",
                                "properties": {
                                    "start": {"type": "integer"},
                                    "end": {"type": "integer"}
                                }
                            }
                        },
                        "required": ["artifact_id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "search_artifacts",
                    "description": "Search for artifacts by topic or type. Returns a list of matching artifact IDs and summaries.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query (topic keyword, e.g., '光合作用', 'photosynthesis')"
                            },
                            "artifact_type": {
                                "type": "string",
                                "enum": ["explanation", "quiz_set", "flashcard_set", "notes"],
                                "description": "Optional: filter by artifact type"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_artifacts",
                    "description": "List all available artifacts in the current session. Returns a lightweight index with IDs, topics, and sizes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Session ID to list artifacts for"
                            }
                        },
                        "required": ["session_id"]
                    }
                }
            }
        ]
    
    def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行工具调用
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
        
        Returns:
            工具执行结果
        """
        if tool_name == "read_artifact":
            return self.read_artifact(**arguments)
        elif tool_name == "search_artifacts":
            return self.search_artifacts(**arguments)
        elif tool_name == "list_artifacts":
            return self.list_artifacts(**arguments)
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    
    def read_artifact(
        self,
        artifact_id: str,
        lines: Optional[Dict[str, int]] = None
    ) -> Dict[str, Any]:
        """
        读取 artifact 完整内容
        
        Args:
            artifact_id: Artifact ID
            lines: 可选的行范围 {"start": 0, "end": 100}
        
        Returns:
            {"content": ..., "metadata": ...}
        """
        logger.info(f"🔍 read_artifact: {artifact_id}")
        
        # 转换 lines 参数
        line_range = None
        if lines:
            line_range = (lines.get("start", 0), lines.get("end", -1))
        
        # 从 artifact manager 读取
        content = self.artifact_manager.read_artifact(artifact_id, line_range)
        
        if content is None:
            return {
                "error": f"Artifact {artifact_id} not found or not accessible",
                "suggestion": "Use list_artifacts() to see available artifacts"
            }
        
        return {
            "artifact_id": artifact_id,
            "content": content,
            "note": "Full content loaded. This consumes tokens."
        }
    
    def search_artifacts(
        self,
        query: str,
        artifact_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        搜索 artifacts
        
        Args:
            query: 搜索关键词
            artifact_type: 可选的类型过滤
        
        Returns:
            {"results": [...], "count": ...}
        """
        logger.info(f"🔍 search_artifacts: query={query}, type={artifact_type}")
        
        # 从 artifact manager 获取索引
        index = self.artifact_manager.get_artifact_index(
            topic=query,
            artifact_type=artifact_type
        )
        
        return {
            "query": query,
            "artifact_type": artifact_type,
            "count": len(index),
            "results": index,
            "note": "This is a lightweight index. Use read_artifact(id) to load full content."
        }
    
    def list_artifacts(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        列出所有 artifacts
        
        Args:
            session_id: 会话 ID
        
        Returns:
            {"artifacts": [...], "count": ...}
        """
        logger.info(f"📋 list_artifacts: session_id={session_id}")
        
        # 从 artifact manager 获取索引
        index = self.artifact_manager.get_artifact_index(session_id=session_id)
        
        return {
            "session_id": session_id,
            "count": len(index),
            "artifacts": index,
            "note": "This is a lightweight index. Use read_artifact(id) to load full content."
        }

