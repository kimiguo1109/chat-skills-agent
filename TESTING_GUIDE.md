# Skill Agent Demo 测试指南

## 📋 测试概览

本指南提供两个完整测试流程，帮助你快速验证 Skill Agent 的核心功能。

**核心功能：**
- ✅ 4个Skills：Quiz（练习题）、Explain（概念讲解）、Flashcard（抽认卡）、Learning Bundle（学习包）
- ✅ 数量控制：精确生成用户指定数量的题目/闪卡
- ✅ 偏好系统：根据用户学习习惯自动推荐最适合的学习方式
- ✅ 混合请求：支持一次性请求多种内容（如"5道化学题和3张物理闪卡"）

---

## 🚀 测试流程 1：全功能快速测试（15分钟）

### 目标
快速验证所有核心功能是否正常工作。

---

### Phase 1：基础 Skills 测试（5分钟）

**目的：** 验证4个核心技能是否都能正常生成内容。

```
1️⃣ "给我几道微积分练习题"
   → 测试 Quiz Skill
   → 应生成5道题（默认值），包含题干、选项、答案、解析

2️⃣ "解释一下什么是导数"
   → 测试 Explain Skill
   → 应生成结构化讲解：直观理解、正式定义、例子、常见错误

3️⃣ "给我一些光合作用的闪卡"
   → 测试 Flashcard Skill
   → 应生成5张闪卡，包含问题、答案、提示

4️⃣ "帮我准备电磁学的完整学习资料"
   → 测试 Learning Bundle Skill
   → 应生成综合学习包：讲解 + 练习题 + 闪卡
   → ⏱️ 这步耗时较长（15-20秒），请耐心等待
```

**验证要点：**
- ✅ 每个请求都能成功返回结果
- ✅ 内容格式正确，UI渲染正常
- ✅ 无报错信息

---

### Phase 2：数量控制测试（3分钟）

**目的：** 验证系统能否精确控制生成数量。

```
5️⃣ "给我3道二元一次方程练习题"
   → 应生成恰好3道题（不是5道）
   → 检查后端日志：📊 Extracted quantity: 3 for quiz_skill

6️⃣ "给我2张牛顿定律的闪卡"
   → 应生成恰好2张闪卡
   → 检查后端日志：📊 Extracted quantity: 2 for flashcard_skill
```

**验证要点：**
- ✅ 生成数量与用户请求完全一致
- ✅ 后端日志显示正确提取了数量参数

---

### Phase 3：偏好系统测试（7分钟）

**目的：** 验证系统能否学习用户偏好，并在模糊请求时自动应用偏好。

#### 步骤1：建立 Quiz 偏好（连续做题）

```
7️⃣ "给我2道历史题"
8️⃣ "给我2道化学题"
9️⃣ "给我2道物理题"
```

**预期：** 后端日志应显示：
```
✨ User preference detected: [User Preference: Very strongly prefers quiz practice for learning (100% of recent activities)]
```

#### 步骤2：测试偏好是否生效（模糊请求）

```
🔟 "化学反应"
   → 应触发 quiz_request（不是 explain_request）
   → 应生成5道化学题
   → 原因：用户只说了主题，没有明确说"解释"或"出题"，系统根据偏好自动选择quiz
```

**验证要点：**
- ✅ 模糊请求"化学反应"触发了 quiz（偏好生效）
- ✅ confidence >= 0.85（高置信度）

#### 步骤3：测试明确意图不被偏好覆盖

```
1️⃣1️⃣ "我想要学习化学反应"
   → 应触发 explain_request（不是 quiz_request）
   → 应生成概念讲解
   → 原因：用户明确说了"学习"，系统尊重明确意图，不应用偏好
```

**验证要点：**
- ✅ 明确的"学习"关键词触发了 explain（偏好未覆盖）
- ✅ 系统不会"过度智能"地改变用户明确意图

---

### ✅ 流程1 总结

如果以上11个测试都通过，说明系统的核心功能正常：
- ✅ 所有4个Skills都能工作
- ✅ 数量控制精确
- ✅ 偏好系统能学习并应用
- ✅ 明确意图优先级高于偏好

---

## 🎯 测试流程 2：偏好系统深度测试（20分钟）

### 目标
深入验证偏好系统的学习能力和动态切换能力。

---

### Phase 1：建立 Flashcard 偏好（5分钟）

**目的：** 测试系统能否识别用户偏好使用闪卡学习。

```
1️⃣ "给我一些光合作用的闪卡"
2️⃣ "帮我准备细胞结构的闪卡"
3️⃣ "闪卡：牛顿定律"
4️⃣ "化学反应的闪卡"
```

**预期后端日志：**
```
✨ User preference detected: [User Preference: Very strongly prefers flashcards for learning (100% of recent activities)]
```

---

### Phase 2：测试 Flashcard 偏好（5分钟）

**目的：** 验证偏好能否正确应用到模糊请求。

```
5️⃣ "电磁学"
   → 应触发 flashcard_request（偏好生效）
   → 应生成闪卡

6️⃣ "光合作用"
   → 应触发 flashcard_request（偏好生效）
   → 应生成闪卡

7️⃣ "我想要学习电磁学"
   → 应触发 explain_request（明确意图优先）
   → 应生成讲解（不是闪卡）
```

**验证要点：**
- ✅ 步骤5-6：模糊请求自动使用闪卡
- ✅ 步骤7：明确"学习"关键词触发讲解

---

### Phase 3：切换到 Quiz 偏好（5分钟）

**目的：** 验证偏好能否动态更新。

```
8️⃣ "给我几道微积分题"
9️⃣ "给我几道物理题"
🔟 "给我几道化学题"
1️⃣1️⃣ "给我几道历史题"
1️⃣2️⃣ "给我几道生物题"
1️⃣3️⃣ "给我几道地理题"
```

**预期后端日志：**
```
✨ User preference detected: [User Preference: Strongly prefers quiz practice for learning (60% of recent activities)]
```

**解释：**
- 最近10次记录：4次闪卡 + 6次quiz = quiz占60%
- 偏好动态更新为 quiz

---

### Phase 4：测试新偏好（5分钟）

**目的：** 验证偏好切换是否成功。

```
1️⃣4️⃣ "化学反应"
   → 应触发 quiz_request（不再是 flashcard_request）
   → 应生成练习题

1️⃣5️⃣ "电磁学"
   → 应触发 quiz_request
   → 应生成练习题

1️⃣6️⃣ "解释一下化学反应"
   → 应触发 explain_request（明确意图优先）
   → 应生成讲解
```

**验证要点：**
- ✅ 步骤14-15：偏好已从flashcard切换到quiz
- ✅ 步骤16：明确意图仍然优先

---

### ✅ 流程2 总结

如果以上16个测试都通过，说明偏好系统非常智能：
- ✅ 能识别用户的学习习惯
- ✅ 能动态更新偏好（从闪卡切换到练习题）
- ✅ 模糊请求时自动应用偏好
- ✅ 明确请求时尊重用户意图

---

## 📊 如何验证测试结果

### 前端验证

**Quiz Card（练习题）**
- ✅ 题目数量正确
- ✅ 包含选项、答案、解析
- ✅ UI渲染正常，可以选择答案

**Explain Card（概念讲解）**
- ✅ 包含直观理解、正式定义
- ✅ 例子部分不为空
- ✅ UI结构清晰

**Flashcard（闪卡）**
- ✅ 闪卡数量正确
- ✅ 包含问题、答案、提示
- ✅ 可以翻转查看

**Learning Bundle（学习包）**
- ✅ 包含多个组件（讲解 + 练习 + 闪卡）
- ✅ 各组件独立渲染

---

### 后端日志验证

**Intent Router（意图识别）**
```
✅ 🔍 Parsing intent for message: ...
✅ ✅ Intent parsed: {intent} (confidence: X.XX, topic: {topic})
✅ 📊 Extracted quantity parameter: X（如有数量）
✅ ✨ User preference detected: [User Preference: ...]（如有偏好）
```

**Skill Orchestrator（技能编排）**
```
✅ 🎯 Orchestrating: intent={intent}, topic={topic}
✅ 📦 Selected skill: {skill_id}
✅ 📊 Extracted quantity: X for {skill_id}
✅ ✅ Orchestration complete
```

---

## 🔧 常见问题

### 问题1：偏好不生效

**症状：** 连续3次使用quiz，但"化学反应"仍然触发explain

**解决方法：**
1. 检查后端日志是否有 "✨ User preference detected"
2. 如果没有，可能需要重启后端（Python文件修改会自动重载，但YAML不会）
3. 确认用户输入是模糊的（如"化学反应"），不是明确的（如"解释化学反应"）

---

### 问题2：数量不对

**症状：** 请求3道题，但生成了5道

**解决方法：**
1. 检查后端日志是否有 "📊 Extracted quantity parameter: 3"
2. 检查后端日志是否有 "📊 Extracted quantity: 3 for quiz_skill"
3. 如果都有但数量仍不对，检查Gemini生成的JSON

---

### 问题3：Learning Bundle 报错

**症状：** "No skill found for intent: learning_bundle"

**解决方法：**
1. 重启后端（learning_bundle_skill.yaml修改后需要重启）
2. 检查后端启动日志：应显示 "✅ SkillRegistry initialized with 4 skills"
3. 如果只有3个skills，说明learning_bundle_skill.yaml加载失败

---

## 🎯 测试建议

### 初次测试
建议先完成 **流程1（15分钟）**，快速验证所有核心功能。

### 深度测试
如果流程1通过，再进行 **流程2（20分钟）**，深入测试偏好系统。

### 日常测试
每次修改代码后，至少运行流程1的前10个测试用例。

---
