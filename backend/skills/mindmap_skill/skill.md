# MindMap Skill - 思维导图生成

**技能ID**: `mindmap_skill`  
**显示名称**: 思维导图生成  
**版本**: 1.0.0  
**类型**: atomic

---

## Intent Triggers

### Primary Keywords (主要关键词)
```
思维导图, 导图, 脑图, 知识图谱, mindmap, mind map, concept map
```

### Quantity Patterns (数量模式)
_N/A - MindMap skill不涉及数量_

### Topic Patterns (主题提取模式)
```regex
(.+?)的?思维导图         → topic: group(1)
(.+?)的?导图             → topic: group(1)
(.+?)mindmap            → topic: group(1)
关于(.+?)的知识图谱      → topic: group(1)
```

### Context Patterns (上下文引用)
```
根据.*生成导图       → use_last_artifact: true
基于.*的思维导图     → use_last_artifact: true
```

---

## Confidence Scoring (置信度评分)

### High Confidence (0.95)
- 包含主要关键词 + 明确主题
- 示例: "给我二战历史的思维导图"

### Medium Confidence (0.75)
- 包含主要关键词，但主题模糊
- 示例: "生成思维导图"

---

## Input Schema

```json
{
  "type": "object",
  "properties": {
    "topic": {
      "type": "string",
      "description": "思维导图主题",
      "required": false
    },
    "subject": {
      "type": "string",
      "description": "学科领域",
      "required": false
    },
    "source_content": {
      "type": "object",
      "description": "基于的内容（可选）",
      "required": false
    },
    "use_last_artifact": {
      "type": "boolean",
      "description": "是否引用上一轮内容",
      "default": false
    }
  }
}
```

---

## Output Schema

```json
{
  "type": "object",
  "properties": {
    "mindmap_id": {"type": "string"},
    "root_concept": {"type": "string"},
    "nodes": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "id": {"type": "string"},
          "label": {"type": "string"},
          "parent_id": {"type": "string"},
          "level": {"type": "integer"}
        }
      }
    }
  }
}
```

---

## Matching Examples (匹配示例)

### Example 1: Simple Request
```
Input: "给我二战历史的思维导图"
Match:
  - skill_id: mindmap_skill
  - confidence: 0.95
  - parameters:
      topic: "二战历史"
      subject: "历史"
```

### Example 2: Minimal Request
```
Input: "生成思维导图"
Match:
  - skill_id: mindmap_skill
  - confidence: 0.75
  - parameters:
      topic: null  # 触发 Clarification
```

---

## Negative Examples (不应匹配的示例)

```
✗ "给我5道题" → quiz_skill (关键词是"题")
✗ "做笔记" → notes_skill (关键词是"笔记")
```

---

## Clarification Trigger (需要澄清的情况)

当以下条件满足时，触发澄清机制：
- `topic is None` 且 `use_last_artifact is False`
- `artifact_history` 有内容 (len >= 1)

---

## Related Skills (相关技能)

- `explain_skill` - 可先生成讲解，再基于讲解生成思维导图
- `notes_skill` - 可基于思维导图生成笔记

---

## Metadata

- **Cost**: Medium
- **Thinking Budget**: 128 tokens
- **Temperature**: 1.0
- **Models**:
  - Primary: `moonshotai/kimi-k2-thinking`
  - Fallback: `gemini-2.0-flash-exp`

