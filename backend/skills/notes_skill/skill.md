# Notes Skill - 笔记生成

**技能ID**: `notes_skill`  
**显示名称**: 笔记生成  
**版本**: 1.0.0  
**类型**: atomic

---

## Intent Triggers

### Primary Keywords (主要关键词)
```
笔记, 总结, 归纳, 整理, 提炼, 梳理, 要点, notes, summary, summarize, outline
```

### Quantity Patterns (数量模式)
_N/A - Notes skill不涉及数量_

### Topic Patterns (主题提取模式)
```regex
(.+?)的?笔记            → topic: group(1)
做(.+?)笔记             → topic: group(1)
总结(.+?)              → topic: group(1)
关于(.+?)的总结         → topic: group(1)
```

### Context Patterns (上下文引用)
```
根据.*做笔记         → use_last_artifact: true
基于.*的笔记         → use_last_artifact: true
总结刚才.*          → use_last_artifact: true
```

---

## Confidence Scoring (置信度评分)

### High Confidence (0.95)
- 包含主要关键词 + 明确主题
- 示例: "做二战历史的笔记"

### Medium Confidence (0.75)
- 包含主要关键词，但主题模糊
- 示例: "做笔记"

### Low Confidence (0.50)
- 只有上下文引用
- 示例: "总结一下刚才的内容"

---

## Input Schema

```json
{
  "type": "object",
  "properties": {
    "topic": {
      "type": "string",
      "description": "笔记主题",
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
    "structured_notes": {
      "type": "object",
      "properties": {
        "title": {"type": "string"},
        "topic": {"type": "string"},
        "subject": {"type": "string"},
        "sections": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "section_title": {"type": "string"},
              "bullet_points": {"type": "array"}
            }
          }
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
Input: "做二战历史的笔记"
Match:
  - skill_id: notes_skill
  - confidence: 0.95
  - parameters:
      topic: "二战历史"
      subject: "历史"
```

### Example 2: Minimal Request
```
Input: "做笔记"
Match:
  - skill_id: notes_skill
  - confidence: 0.75
  - parameters:
      topic: null  # 触发 Clarification
```

### Example 3: Context Reference
```
Input: "总结一下刚才讲解的内容"
Match:
  - skill_id: notes_skill
  - confidence: 0.80
  - parameters:
      topic: null
      use_last_artifact: true
```

---

## Negative Examples (不应匹配的示例)

```
✗ "给我5道题" → quiz_skill (关键词是"题")
✗ "什么是光合作用" → explain_skill (关键词是"什么是")
✗ "生成闪卡" → flashcard_skill (关键词是"闪卡")
```

---

## Clarification Trigger (需要澄清的情况)

当以下条件满足时，触发澄清机制：
- `topic is None` 且 `use_last_artifact is False`
- `artifact_history` 有内容 (len >= 1)

---

## Related Skills (相关技能)

- `explain_skill` - 可先生成讲解，再基于讲解生成笔记
- `quiz_skill` - 可基于笔记生成练习题
- `flashcard_skill` - 可基于笔记生成记忆卡

---

## Metadata

- **Cost**: Medium
- **Thinking Budget**: 128 tokens
- **Temperature**: 1.0
- **Models**:
  - Primary: `moonshotai/kimi-k2-thinking`
  - Fallback: `gemini-2.0-flash-exp`

