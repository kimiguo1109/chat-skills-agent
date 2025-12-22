# Quiz Skill - 练习题生成

**技能ID**: `quiz_skill`  
**显示名称**: 练习题生成  
**版本**: 1.0.0  
**类型**: atomic

---

## Intent Triggers

### Primary Keywords (主要关键词)
```
题, 题目, 练习, 测试, 考题, 测验, 做题, 刷题, 问题, 习题, 试题, quiz, test, question, exercise, exam
```

### Quantity Patterns (数量模式)
```regex
(\d+)\s*道\s*题     → quantity
(\d+)\s*个\s*问题   → quantity
(\d+)\s*道\s*练习   → quantity
(\d+)\s*questions?  → quantity
```

### Topic Patterns (主题提取模式)
```regex
(\d+)道(.+?)的题           → topic: group(2)
关于(.+?)的(题目|练习)      → topic: group(1)
(.+?)(题目|练习|quiz)      → topic: group(1) (after cleanup)
```

### Context Patterns (上下文引用)
```
根据.*出题          → use_last_artifact: true
基于.*生成题        → use_last_artifact: true
这些.*题            → use_last_artifact: true
```

---

## Confidence Scoring (置信度评分)

### High Confidence (0.95)
- 包含主要关键词 + 明确主题
- 示例: "给我5道二战历史的题"

### Medium Confidence (0.75)
- 包含主要关键词，但主题模糊
- 示例: "出题目"

### Low Confidence (0.50)
- 只有上下文引用，无明确关键词
- 示例: "根据这些内容"

---

## Input Schema

```json
{
  "type": "object",
  "properties": {
    "topic": {
      "type": "string",
      "description": "题目主题",
      "required": false
    },
    "num_questions": {
      "type": "integer",
      "description": "题目数量",
      "default": 5,
      "minimum": 1,
      "maximum": 10
    },
    "difficulty": {
      "type": "string",
      "enum": ["easy", "medium", "hard"],
      "default": "medium"
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
    "quiz_set_id": {"type": "string"},
    "subject": {"type": "string"},
    "topic": {"type": "string"},
    "questions": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "question_id": {"type": "string"},
          "question_type": {"type": "string"},
          "question_text": {"type": "string"},
          "options": {"type": "array"},
          "correct_answer": {"type": "string"},
          "explanation": {"type": "string"}
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
Input: "给我5道二战历史的题"
Match:
  - skill_id: quiz_skill
  - confidence: 0.95
  - parameters:
      topic: "二战历史"
      num_questions: 5
      difficulty: "medium"
```

### Example 2: Minimal Request
```
Input: "出题目"
Match:
  - skill_id: quiz_skill
  - confidence: 0.75
  - parameters:
      topic: null  # 触发 Clarification
      num_questions: 5  # default
```

### Example 3: Context Reference
```
Input: "根据这些例子出3道题"
Match:
  - skill_id: quiz_skill
  - confidence: 0.75
  - parameters:
      topic: null
      num_questions: 3
      use_last_artifact: true
```

### Example 4: Complex Request
```
Input: "关于光合作用的10道简单练习题"
Match:
  - skill_id: quiz_skill
  - confidence: 0.95
  - parameters:
      topic: "光合作用"
      num_questions: 10
      difficulty: "easy"
```

---

## Negative Examples (不应匹配的示例)

```
✗ "什么是光合作用" → explain_skill (没有"题"关键词)
✗ "给我10张闪卡" → flashcard_skill (关键词是"闪卡")
✗ "做笔记" → notes_skill (关键词是"笔记")
```

---

## Clarification Trigger (需要澄清的情况)

当以下条件满足时，触发澄清机制：
- `topic is None` 且 `use_last_artifact is False`
- `artifact_history` 有内容 (len >= 1)

澄清响应示例：
```
您想对哪个主题生成练习题呢？

[机器学习] [牛顿定律] [光合作用]
```

---

## Related Skills (相关技能)

- `explain_skill` - 可用于解释题目涉及的概念
- `flashcard_skill` - 可基于相同主题生成闪卡
- `notes_skill` - 可基于题目生成笔记

---

## Metadata

- **Cost**: Small (short prompts)
- **Thinking Budget**: 128 tokens
- **Temperature**: 1.0
- **Models**:
  - Primary: `moonshotai/kimi-k2-thinking`
  - Fallback: `gemini-2.0-flash-exp`

