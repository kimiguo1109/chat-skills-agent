"""
Learning History API
提供学习历史记录的查询接口
"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel

from app.core.memory_manager import MemoryManager

router = APIRouter()

# 全局 Memory Manager 实例（从 agent.py 导入或共享）
memory_manager = MemoryManager()


class ArtifactResponse(BaseModel):
    """单个 Artifact 响应"""
    id: str
    turn: int
    timestamp: str
    artifact_type: str
    topic: str
    summary: str
    content: Dict[str, Any]


class ArtifactsListResponse(BaseModel):
    """Artifacts 列表响应"""
    artifacts: List[ArtifactResponse]
    total: int
    has_more: bool


@router.get("/api/sessions/{session_id}/artifacts", response_model=ArtifactsListResponse)
async def get_artifacts(
    session_id: str,
    page: int = Query(1, ge=1, description="页码（从1开始）"),
    limit: int = Query(50, ge=1, le=100, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词（按 topic/summary 搜索）"),
    artifact_type: Optional[str] = Query(None, description="筛选类型")
):
    """
    获取会话的历史 artifacts
    
    参数:
    - session_id: 会话 ID
    - page: 页码（从1开始）
    - limit: 每页数量
    - search: 搜索关键词（按 topic/summary 搜索）
    - artifact_type: 筛选类型
    
    返回:
    - artifacts: List[ArtifactRecord]
    - total: int (总数)
    - has_more: bool (是否有更多)
    """
    try:
        # 获取 session context
        session_context = await memory_manager.get_session_context(session_id)
        artifacts = session_context.artifact_history or []
        
        # 筛选
        if search:
            search_lower = search.lower()
            artifacts = [
                a for a in artifacts 
                if search_lower in a.topic.lower() or search_lower in a.summary.lower()
            ]
        
        if artifact_type:
            artifacts = [a for a in artifacts if a.artifact_type == artifact_type]
        
        # 排序（最新的在前）
        artifacts.sort(key=lambda x: x.timestamp, reverse=True)
        
        # 分页
        total = len(artifacts)
        start = (page - 1) * limit
        end = start + limit
        paginated = artifacts[start:end]
        
        # 转换为响应格式
        artifact_responses = [
            ArtifactResponse(
                id=a.id,
                turn=a.turn,
                timestamp=a.timestamp.isoformat() if isinstance(a.timestamp, datetime) else a.timestamp,
                artifact_type=a.artifact_type,
                topic=a.topic,
                summary=a.summary,
                content=a.content
            )
            for a in paginated
        ]
        
        return ArtifactsListResponse(
            artifacts=artifact_responses,
            total=total,
            has_more=end < total
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load artifacts: {str(e)}")


@router.get("/api/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact_detail(artifact_id: str):
    """
    获取单个 artifact 的完整内容
    用于回溯显示
    
    参数:
    - artifact_id: Artifact ID
    
    返回:
    - ArtifactResponse
    """
    try:
        # 从所有 sessions 中查找该 artifact
        artifact = await memory_manager.find_artifact_by_id(artifact_id)
        
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        
        return ArtifactResponse(
            id=artifact.id,
            turn=artifact.turn,
            timestamp=artifact.timestamp.isoformat() if isinstance(artifact.timestamp, datetime) else artifact.timestamp,
            artifact_type=artifact.artifact_type,
            topic=artifact.topic,
            summary=artifact.summary,
            content=artifact.content
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load artifact: {str(e)}")

