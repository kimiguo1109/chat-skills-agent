# Explain Skill - 概念讲解

**技能ID**: `explain_skill`  
**显示名称**: 概念讲解  
**版本**: 1.0.0  
**类型**: atomic

---

## Intent Triggers

### Primary Keywords (主要关键词)
```
讲解, 讲讲, 讲一讲, 讲下, 解释, 说明, 理解, 了解, 学习, 什么是, 介绍, 定义, 教我, 告诉我, 科普, 解读, explain, what is, define, introduce, understand, learn, tell me about, teach me
```

### Quantity Patterns (数量模式)
_N/A - Explanation skill不涉及数量_

### Topic Patterns (主题提取模式)
```regex
什么是(.+?)           → topic: group(1)
解释一?下?(.+?)       → topic: group(1)
讲解一?下?(.+?)       → topic: group(1)
理解一?下?(.+?)       → topic: group(1)
了解一?下?(.+?)       → topic: group(1)
学习一?下?(.+?)       → topic: group(1)
(.+?)是什么          → topic: group(1)
关于(.+?)的讲解      → topic: group(1)
```

### Context Patterns (上下文引用)
```
解释一下第(\d+)道题    → reference_type: "question", reference_index: group(1)
讲解.*这道题           → use_last_artifact: true
基于.*的讲解           → use_last_artifact: true
```

---

## Confidence Scoring (置信度评分)

### High Confidence (0.95)
- 包含主要关键词 + 明确主题
- 示例: "解释一下光合作用"

### Medium Confidence (0.75)
- 包含主要关键词，但主题模糊
- 示例: "讲解一下"

### Low Confidence (0.50)
- 只有上下文引用
- 示例: "解释一下这道题"

---

## Input Schema

```json
{
  "type": "object",
  "properties": {
    "concept_name": {
      "type": "string",
      "description": "要解释的概念",
      "required": false
    },
    "subject": {
      "type": "string",
      "description": "学科领域",
      "required": false
    },
    "source_content": {
      "type": "object",
      "description": "基于的内容（如题目）",
      "required": false
    },
    "use_last_artifact": {
      "type": "boolean",
      "description": "是否引用上一轮内容",
      "default": false
    },
    "reference_type": {
      "type": "string",
      "enum": ["question", "example", "content"],
      "required": false
    },
    "reference_index": {
      "type": "integer",
      "required": false
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
    "concept": {"type": "string"},
    "subject": {"type": "string"},
    "intuition": {"type": "string"},
    "formal_definition": {"type": "string"},
    "why_it_matters": {"type": "string"},
    "examples": {"type": "array"},
    "common_mistakes": {"type": "array"},
    "related_concepts": {"type": "array"},
    "difficulty": {"type": "string"},
    "reasoning_summary": {"type": "string"}
  }
}
```

---

## Matching Examples (匹配示例)

### Example 1: Simple Explanation Request
```
Input: "什么是光合作用"
Match:
  - skill_id: explain_skill
  - confidence: 0.95
  - parameters:
      concept_name: "光合作用"
      subject: null
```

### Example 2: Context Reference
```
Input: "解释一下第一道题"
Match:
  - skill_id: explain_skill
  - confidence: 0.90
  - parameters:
      concept_name: null
      use_last_artifact: true
      reference_type: "question"
      reference_index: 0
```

### Example 3: Detailed Request
```
Input: "讲解一下二战历史中的珍珠港事件"
Match:
  - skill_id: explain_skill
  - confidence: 0.95
  - parameters:
      concept_name: "珍珠港事件"
      subject: "历史"
```

---

## Negative Examples (不应匹配的示例)

```
✗ "给我5道题" → quiz_skill (没有"解释"关键词)
✗ "做笔记" → notes_skill (关键词是"笔记")
```

---

## Clarification Trigger (需要澄清的情况)

当以下条件满足时，触发澄清机制：
- `concept_name is None` 且 `use_last_artifact is False`

---

## Related Skills (相关技能)

- `quiz_skill` - 可基于解释生成练习题
- `flashcard_skill` - 可基于解释生成记忆卡
- `notes_skill` - 可基于解释生成结构化笔记

---

## Metadata

- **Cost**: Medium
- **Thinking Budget**: 128 tokens
- **Temperature**: 1.0
- **Models**:
  - Primary: `moonshotai/kimi-k2-thinking`
  - Fallback: `gemini-2.0-flash-exp`

