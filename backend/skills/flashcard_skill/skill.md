# Flashcard Skill - 闪卡生成

**技能ID**: `flashcard_skill`  
**显示名称**: 闪卡生成  
**版本**: 1.0.0  
**类型**: atomic

---

## Intent Triggers

### Primary Keywords (主要关键词)
```
闪卡, 卡片, 记忆卡, 抽认卡, flashcard, card, anki
```

### Quantity Patterns (数量模式)
```regex
(\d+)\s*张\s*闪卡    → quantity
(\d+)\s*张\s*卡片    → quantity
(\d+)\s*个\s*flashcards? → quantity
(\d+)\s*cards?      → quantity
```

### Topic Patterns (主题提取模式)
```regex
(\d+)张(.+?)的闪卡        → topic: group(2)
关于(.+?)的(闪卡|卡片)    → topic: group(1)
(.+?)(闪卡|卡片)         → topic: group(1) (after cleanup)
```

### Context Patterns (上下文引用)
```
根据.*生成?闪卡      → use_last_artifact: true
基于.*的卡片         → use_last_artifact: true
这些.*闪卡          → use_last_artifact: true
```

---

## Confidence Scoring (置信度评分)

### High Confidence (0.95)
- 包含主要关键词 + 明确主题
- 示例: "给我10张二战历史的闪卡"

### Medium Confidence (0.75)
- 包含主要关键词，但主题模糊
- 示例: "生成闪卡"

### Low Confidence (0.50)
- 只有上下文引用
- 示例: "根据这些内容"

---

## Input Schema

```json
{
  "type": "object",
  "properties": {
    "topic": {
      "type": "string",
      "description": "闪卡主题",
      "required": false
    },
    "num_cards": {
      "type": "integer",
      "description": "闪卡数量",
      "default": 5,
      "minimum": 1,
      "maximum": 20
    },
    "difficulty": {
      "type": "string",
      "enum": ["easy", "medium", "hard"],
      "default": "medium"
    },
    "card_type": {
      "type": "string",
      "enum": ["basic", "cloze", "definition"],
      "default": "basic"
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
    "flashcard_set_id": {"type": "string"},
    "subject": {"type": "string"},
    "topic": {"type": "string"},
    "cards": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "card_id": {"type": "string"},
          "front": {"type": "string"},
          "back": {"type": "string"},
          "card_type": {"type": "string"},
          "hints": {"type": "array"},
          "related_concepts": {"type": "array"}
        }
      }
    }
  }
}
```

---

## Matching Examples (匹配示例)

### Example 1: Explicit Request
```
Input: "给我10张二战历史的闪卡"
Match:
  - skill_id: flashcard_skill
  - confidence: 0.95
  - parameters:
      topic: "二战历史"
      num_cards: 10
      difficulty: "medium"
```

### Example 2: Minimal Request
```
Input: "生成闪卡"
Match:
  - skill_id: flashcard_skill
  - confidence: 0.75
  - parameters:
      topic: null  # 触发 Clarification
      num_cards: 5  # default
```

### Example 3: Context Reference
```
Input: "根据这些例子生成5张卡片"
Match:
  - skill_id: flashcard_skill
  - confidence: 0.85
  - parameters:
      topic: null
      num_cards: 5
      use_last_artifact: true
```

---

## Negative Examples (不应匹配的示例)

```
✗ "给我5道题" → quiz_skill (关键词是"题")
✗ "什么是光合作用" → explain_skill (没有"闪卡"关键词)
✗ "做笔记" → notes_skill (关键词是"笔记")
```

---

## Clarification Trigger (需要澄清的情况)

当以下条件满足时，触发澄清机制：
- `topic is None` 且 `use_last_artifact is False`
- `artifact_history` 有内容 (len >= 1)

---

## Related Skills (相关技能)

- `explain_skill` - 可用于解释闪卡涉及的概念
- `quiz_skill` - 可基于相同主题生成练习题
- `notes_skill` - 可基于闪卡生成笔记

---

## Metadata

- **Cost**: Small
- **Thinking Budget**: 128 tokens
- **Temperature**: 1.0
- **Models**:
  - Primary: `moonshotai/kimi-k2-thinking`
  - Fallback: `gemini-2.0-flash-exp`

