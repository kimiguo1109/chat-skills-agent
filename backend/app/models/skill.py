"""
技能定义相关的 Pydantic 模型
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional


class SkillDefinition(BaseModel):
    """技能定义（从 YAML 配置加载）"""
    id: str = Field(..., description="技能唯一标识，如 quiz")
    
    display_name: str = Field(..., description="显示名称，如'练习题生成'")
    
    version: str = Field(default="1.0.0", description="版本号")
    
    intent_tags: List[str] = Field(
        ...,
        description="支持的意图标签列表，如 ['quiz']"
    )
    
    input_schema: Dict[str, Any] = Field(
        ...,
        description="输入参数的 JSON Schema"
    )
    
    output_schema: Dict[str, Any] = Field(
        ...,
        description="输出结果的 JSON Schema"
    )
    
    models: Dict[str, str] = Field(
        ...,
        description="使用的模型配置，包含 primary 和 fallback"
    )
    
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="上下文需求配置"
    )
    
    cost: Dict[str, Any] = Field(
        default_factory=dict,
        description="成本配置"
    )
    
    composable: bool = Field(
        default=True,
        description="是否可被组合使用"
    )
    
    dependencies: List[str] = Field(
        default_factory=list,
        description="依赖的其他技能 ID"
    )
    
    prompt_file: Optional[str] = Field(
        default=None,
        description="Prompt 模板文件名（位于 app/prompts/ 目录）"
    )
    
    # 🆕 新增字段
    skill_type: Optional[str] = Field(
        default=None,
        description="Skill 类型，如 'plan' 表示 Plan Skill"
    )
    
    thinking_budget: Optional[int] = Field(
        default=1024,
        description="思考预算（tokens），0-24576"
    )
    
    # 🆕 原始 YAML 配置（保存所有字段）
    raw_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="原始 YAML 配置（包含所有字段）",
        exclude=True
    )
    
    # 🆕 保存额外的配置字段（Pydantic v2）
    model_config = {
        "extra": "allow",  # 允许额外字段
        "json_schema_extra": {
            "example": {
                "id": "quiz",
                "display_name": "练习题生成",
                "version": "1.0.0",
                "intent_tags": ["quiz"],
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                        "num_questions": {"type": "integer", "minimum": 1, "maximum": 10}
                    },
                    "required": ["topic"]
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "questions": {"type": "array"}
                    }
                },
                "models": {
                    "primary": "gemini-2.5-flash",
                    "fallback": "gemini-2.0-flash-lite"
                },
                "context": {
                    "need_user_memory": True,
                    "need_content_store": False
                },
                "cost": {
                    "model_class": "small",
                    "context_size": "small"
                },
                "composable": True,
                "dependencies": []
            }
        }
    }

