# Learning Plan Skill - 学习包生成

**技能ID**: `learning_plan_skill`  
**显示名称**: 学习包  
**版本**: 1.0.0  
**类型**: composite (Plan Skill)

---

## Intent Triggers

### Primary Keywords (主要关键词)
```
学习资料, 学习包, 学习材料, 套餐, 综合资料, learning bundle, learning package, study pack
```

### Quantity Patterns (数量模式)
```regex
(\d+)\s*张\s*闪?卡     → flashcard_quantity: group(1)
(\d+)\s*道\s*题        → quiz_quantity: group(1)
```

### Topic Patterns (主题提取模式)
```regex
(.+?)的?学习资料        → topic: group(1)
(.+?)学习包            → topic: group(1)
关于(.+?)的综合资料     → topic: group(1)
```

### Mixed Intent Detection (混合意图检测)
当用户消息包含多个技能的关键词时，识别为 learning_plan_skill：
```
讲解.*题目            → learning_plan_skill (explain + quiz)
闪卡.*题              → learning_plan_skill (flashcard + quiz)
解释.*生成.*题         → learning_plan_skill (explain + quiz)
```

---

## Confidence Scoring (置信度评分)

### High Confidence (0.95)
- 明确提到"学习包"或"学习资料"
- 示例: "二战历史的学习资料"

### Medium Confidence (0.85)
- 检测到混合意图（多个技能关键词）
- 示例: "讲解光合作用然后出题"

### Low Confidence (0.70)
- 模糊的学习请求
- 示例: "帮我学习一下"

---

## Input Schema

```json
{
  "type": "object",
  "properties": {
    "topic": {
      "type": "string",
      "description": "学习主题",
      "required": false
    },
    "subject": {
      "type": "string",
      "description": "学科领域",
      "required": false
    },
    "difficulty": {
      "type": "string",
      "enum": ["easy", "medium", "hard"],
      "default": "medium"
    },
    "flashcard_quantity": {
      "type": "integer",
      "description": "闪卡数量",
      "default": 5
    },
    "quiz_quantity": {
      "type": "integer",
      "description": "题目数量",
      "default": 3
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
    "topic": {"type": "string"},
    "subject": {"type": "string"},
    "components": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": {"type": "string"},
          "content": {"type": "object"}
        }
      }
    }
  }
}
```

---

## Plan Execution Steps

Learning Plan Skill 会串联执行以下子技能：

1. **Step 1: Explanation** (`explain_skill`)
   - 生成核心概念讲解
   - 输出传递给后续步骤

2. **Step 2: Flashcard** (`flashcard_skill`)
   - 基于讲解生成记忆卡
   - 数量由 `flashcard_quantity` 控制（默认5张）

3. **Step 3: Quiz** (`quiz_skill`)
   - 基于讲解和闪卡生成练习题
   - 数量由 `quiz_quantity` 控制（默认3道）

---

## Matching Examples (匹配示例)

### Example 1: Explicit Learning Bundle
```
Input: "二战历史的学习资料"
Match:
  - skill_id: learning_plan_skill
  - confidence: 0.95
  - parameters:
      topic: "二战历史"
      flashcard_quantity: 5 (default)
      quiz_quantity: 3 (default)
```

### Example 2: Mixed Intent (Explain + Quiz)
```
Input: "讲解光合作用然后出3道题"
Match:
  - skill_id: learning_plan_skill
  - confidence: 0.85
  - parameters:
      topic: "光合作用"
      quiz_quantity: 3
      flashcard_quantity: 5 (default)
```

### Example 3: With Quantities
```
Input: "生成二战的讲解，5张闪卡和3道题"
Match:
  - skill_id: learning_plan_skill
  - confidence: 0.90
  - parameters:
      topic: "二战"
      flashcard_quantity: 5
      quiz_quantity: 3
```

### Example 4: Flashcard + Quiz
```
Input: "3张闪卡，3道题目"
Match:
  - skill_id: learning_plan_skill
  - confidence: 0.85
  - parameters:
      topic: null  # 需要澄清
      flashcard_quantity: 3
      quiz_quantity: 3
```

---

## Negative Examples (不应匹配的示例)

```
✗ "给我5道题" → quiz_skill (单一技能，不是混合)
✗ "什么是光合作用" → explain_skill (单一技能)
✗ "生成闪卡" → flashcard_skill (单一技能)
```

---

## Clarification Trigger (需要澄清的情况)

当以下条件满足时，触发澄清机制：
- `topic is None` 且 `use_last_artifact is False`
- `artifact_history` 有内容 (len >= 1)

---

## Related Skills (相关技能)

- `explain_skill` - Sub-skill (Step 1)
- `flashcard_skill` - Sub-skill (Step 2)
- `quiz_skill` - Sub-skill (Step 3)

---

## Metadata

- **Cost**: Large (composite skill)
- **Thinking Budget**: 128 tokens (per sub-skill)
- **Temperature**: 1.0
- **Models**:
  - Primary: `moonshotai/kimi-k2-thinking`
  - Fallback: `gemini-2.0-flash-exp`
- **Execution**: Sequential (串联执行)

