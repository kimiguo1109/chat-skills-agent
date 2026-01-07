"""
意图识别相关的 Pydantic 模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Union


class MemorySummary(BaseModel):
    """记忆摘要 - 供 Intent Router 使用"""
    topic_hint: Optional[str] = Field(
        None, 
        description="当前主题提示，如'微积分-极限'"
    )
    user_mastery_hint: Optional[str] = Field(
        None,
        description="用户掌握度提示：weak/medium/strong"
    )
    recent_behavior: str = Field(
        default="",
        description="最近行为描述，如'用户刚做过极限练习题'"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "topic_hint": "微积分-极限",
                "user_mastery_hint": "weak",
                "recent_behavior": "用户刚做过极限练习题，正确率40%"
            }
        }
    }


class IntentResult(BaseModel):
    """意图识别结果"""
    intent: Union[str, List[str]] = Field(
        ...,
        description="意图标签，如 quiz, explain, other。可以是单个或多个"
    )
    topic: Optional[str] = Field(
        None,
        description="提取的主题，如'微积分-极限'"
    )
    target_artifact: Optional[str] = Field(
        None,
        description="目标产物类型，如 quiz_set, explanation"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="识别置信度，0-1之间"
    )
    raw_text: str = Field(
        ...,
        description="原始用户输入"
    )
    parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="额外参数，如 quantity（数量）、difficulty（难度）等"
    )
    # 🆕 引用解析结果
    referenced_content: Optional[str] = Field(
        None,
        description="从历史 artifacts 中解析的引用内容，如'第二题的内容'"
    )
    has_reference: bool = Field(
        default=False,
        description="是否包含对历史 artifacts 的引用"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "intent": "quiz",
                "topic": "微积分-极限",
                "target_artifact": "quiz_set",
                "confidence": 0.86,
                "raw_text": "给我几道极限练习题"
            }
        }
    }

