# Conversation-Based Markdown Storage Design

## 设计理念

**核心思想**：按照连续对话 session 生成一个 Markdown 文档，而不是多个 `step_artifact_xxx.json`。

**优势**：
- ✅ 上下文连贯：一个 MD = 一段完整对话
- ✅ 人类可读：Markdown 格式，易于理解
- ✅ 减少文件数量：从 N 个 JSON → 1 个 MD（每个 session）
- ✅ LLM 友好：直接加载完整对话历史

---

## Session 分割策略

### 规则
- **时间间隔 <= 5 分钟**：追加到当前 session 的 MD 文件
- **时间间隔 > 5 分钟**：创建新 session 的 MD 文件

### 文件命名
```
session_{user_id}_{start_timestamp}.md
```

示例：
```
backend/artifacts/user_kimi/
├── session_20251121_140530.md    # 14:05 开始的对话
├── session_20251121_152200.md    # 15:22 开始的对话（距离上次17分钟）
└── session_20251121_170000.md    # 17:00 开始的对话（距离上次38分钟）
```

---

## Markdown 文件格式

### 文件头部（Metadata）
```markdown
# Learning Session - 2025-11-21 14:05:30

**User**: user_kimi
**Session ID**: session_20251121_140530
**Started**: 2025-11-21 14:05:30
**Last Updated**: 2025-11-21 14:23:45
**Status**: active

---
```

### 每个对话轮次（Turn）

```markdown
## Turn 1 - 14:05:35

### 👤 User Query
什么是光合作用

### 🤖 Agent Response
**Type**: Explanation  
**Topic**: 光合作用  
**Skill**: explain_skill

#### 📚 直觉理解
光合作用是植物的"食物制造工厂"。就像人类通过吃饭获取能量一样，植物通过光合作用把阳光、水和二氧化碳"烹饪"成自己需要的养分（葡萄糖）和氧气。

#### 📖 正式定义
光合作用是绿色植物、藻类和某些细菌利用叶绿素，在光能的驱动下，将二氧化碳（CO₂）和水（H₂O）转化为葡萄糖（C₆H₁₂O₆）并释放氧气（O₂）的过程。

总反应式：
```
6CO₂ + 6H₂O + 光能 → C₆H₁₂O₆ + 6O₂
```

#### 💡 为什么重要
光合作用是地球生态系统的能量来源，几乎所有食物链都始于此。它提供了大气中的氧气，维持了地球的碳氧平衡，是生命存在的基础。

#### 🌟 实例
1. **为什么叶子是绿色的**：叶绿素吸收红光和蓝光用于光合作用，反射绿光，所以叶子看起来是绿色的。

2. **植物白天和晚上的气体交换不同**：白天光合作用占主导，吸收CO₂释放O₂；晚上只有呼吸作用，吸收O₂释放CO₂。

#### ⚠️ 常见误区
1. **误区**：植物只进行光合作用，不进行呼吸作用
   **纠正**：植物24小时都在呼吸，只是白天光合作用产生的氧气远多于呼吸消耗的氧气

2. **误区**：所有植物细胞都能进行光合作用
   **纠正**：只有含有叶绿体的细胞（主要是叶肉细胞和某些茎细胞）才能进行光合作用

#### 🔗 相关概念
- 叶绿体
- 细胞呼吸
- 碳循环
- 生态系统能量流动

---
```

```markdown
## Turn 2 - 14:08:15

### 👤 User Query
给我三道题

### 🤖 Agent Response
**Type**: Quiz Set  
**Topic**: 光合作用  
**Skill**: quiz_skill  
**Quantity**: 3 questions  
**Context**: Based on previous explanation

#### Question 1 (选择题)
**题目**：光合作用的主要产物是什么？

**选项**：
- A. 氧气和水
- B. 葡萄糖和氧气 ✅
- C. 二氧化碳和葡萄糖
- D. 水和葡萄糖

**答案**：B

**解析**：光合作用的化学方程式为 6CO₂ + 6H₂O + 光能 → C₆H₁₂O₆ + 6O₂，主要产物是葡萄糖（C₆H₁₂O₆）和氧气（O₂）。

---

#### Question 2 (选择题)
**题目**：下列关于叶绿体的说法，正确的是？

**选项**：
- A. 所有植物细胞都含有叶绿体
- B. 叶绿体只存在于叶片中
- C. 叶绿体是光合作用的场所 ✅
- D. 叶绿体不参与呼吸作用

**答案**：C

**解析**：叶绿体是光合作用的场所，含有叶绿素，能够捕获光能。并非所有植物细胞都有叶绿体（如根细胞），叶绿体也可以存在于茎等绿色部位。

---

#### Question 3 (判断题)
**题目**：植物在夜间不进行光合作用，但仍然进行呼吸作用。

**答案**：正确 ✅

**解析**：光合作用需要光能，因此只在有光的条件下进行（主要是白天）。而呼吸作用是生物体获取能量的过程，植物24小时都在进行呼吸作用，无论白天还是夜晚。

---
```

```markdown
## Turn 3 - 14:12:30

### 👤 User Query
再来两张闪卡

### 🤖 Agent Response
**Type**: Flashcard Set  
**Topic**: 光合作用  
**Skill**: flashcard_skill  
**Quantity**: 2 cards  
**Context**: Based on previous explanation and quiz

#### 🃏 Flashcard 1

**正面**：
```
光合作用的化学方程式是什么？
```

**背面**：
```
6CO₂ + 6H₂O + 光能 → C₆H₁₂O₆ + 6O₂

记忆技巧：
- 6个二氧化碳 + 6个水 + 光能
- → 1个葡萄糖 + 6个氧气
- "6+6光→1+6氧"
```

---

#### 🃏 Flashcard 2

**正面**：
```
植物的叶子为什么是绿色的？
```

**背面**：
```
因为叶绿素吸收红光和蓝光用于光合作用，
反射绿光，所以我们看到的叶子是绿色的。

记忆技巧：
- 吸收红蓝光（用于光合作用）
- 反射绿光（我们看到绿色）
- "吸红蓝，反绿光"
```

---
```

### 文件尾部（Summary）

```markdown
---

## 📊 Session Summary

**Duration**: 18 minutes (14:05:30 - 14:23:45)  
**Total Turns**: 3  
**Topics Discussed**: 光合作用  
**Skills Used**: 
- explain_skill (1 time)
- quiz_skill (1 time)
- flashcard_skill (1 time)

**Learning Progress**:
- ✅ Understood: 光合作用基本概念
- ✅ Practiced: 3 quiz questions
- ✅ Memorized: 2 flashcards

**Next Session Suggestion**:
- 可以继续学习：叶绿体的结构、碳循环、生态系统能量流动
- 或者切换新主题

---

*Last saved: 2025-11-21 14:23:45*  
*Storage: S3 (skill-agent-demo/user_kimi/session_20251121_140530.md)*
```

---

## 实现要点

### 1. Session 管理器（新模块）

```python
class ConversationSessionManager:
    """管理连续对话 session"""
    
    SESSION_TIMEOUT = 300  # 5分钟（秒）
    
    def __init__(self, user_id: str, storage_path: str):
        self.user_id = user_id
        self.storage_path = storage_path
        self.current_session_id = None
        self.last_activity_time = None
    
    async def start_or_continue_session(self) -> str:
        """
        开始或继续 session
        
        Returns:
            session_id (用于 MD 文件名)
        """
        now = datetime.now()
        
        # 检查是否需要新 session
        if self._should_start_new_session(now):
            self.current_session_id = self._generate_session_id(now)
            self.last_activity_time = now
            await self._create_new_session_file()
        else:
            self.last_activity_time = now
        
        return self.current_session_id
    
    def _should_start_new_session(self, now: datetime) -> bool:
        """判断是否需要新 session"""
        if not self.current_session_id:
            return True
        
        if not self.last_activity_time:
            return True
        
        time_diff = (now - self.last_activity_time).total_seconds()
        return time_diff > self.SESSION_TIMEOUT
    
    def _generate_session_id(self, timestamp: datetime) -> str:
        """生成 session ID"""
        return f"session_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    
    async def append_turn(
        self,
        turn_number: int,
        user_query: str,
        agent_response: Dict[str, Any],
        response_type: str
    ):
        """追加一个对话轮次到 MD 文件"""
        md_content = self._format_turn_markdown(
            turn_number,
            user_query,
            agent_response,
            response_type
        )
        
        # 追加到文件
        await self._append_to_session_file(md_content)
        
        # 上传到 S3
        await self._upload_to_s3()
```

### 2. Markdown 格式化器

```python
class MarkdownFormatter:
    """将 artifact 转换为 Markdown 格式"""
    
    @staticmethod
    def format_explanation(content: Dict[str, Any]) -> str:
        """格式化 explanation"""
        # 生成对应的 Markdown
        pass
    
    @staticmethod
    def format_quiz(content: Dict[str, Any]) -> str:
        """格式化 quiz"""
        pass
    
    @staticmethod
    def format_flashcard(content: Dict[str, Any]) -> str:
        """格式化 flashcard"""
        pass
```

### 3. 上下文加载优化

```python
async def load_conversation_context(
    user_id: str,
    max_sessions: int = 1
) -> str:
    """
    加载最近的对话上下文
    
    Args:
        user_id: 用户ID
        max_sessions: 加载最近几个 session（默认1个，即当前session）
    
    Returns:
        完整的 Markdown 文本
    """
    # 1. 列出该用户的所有 session MD 文件
    session_files = await list_session_files(user_id)
    
    # 2. 按时间排序，取最近的 N 个
    recent_sessions = sorted(session_files, reverse=True)[:max_sessions]
    
    # 3. 加载并拼接
    context = ""
    for session_file in recent_sessions:
        content = await load_from_s3(session_file)
        context += content + "\n\n---\n\n"
    
    return context
```

### 4. 向后兼容策略

**方案 A：完全替换**
- 删除 JSON artifacts 系统
- 只保留 MD 文件
- 简化架构

**方案 B：双轨制（推荐）**
- JSON artifacts：结构化数据，供程序使用
- MD 文件：人类可读，供 LLM 加载上下文
- 两者同步更新

**方案 C：渐进迁移**
- 新数据使用 MD
- 旧数据保留 JSON
- 逐步迁移

---

## 优势总结

### 📈 对比

| 维度 | 多个 JSON 文件 | 单个 MD 文件（Session）|
|------|----------------|----------------------|
| **文件数量** | N 个（每个 artifact 1 个） | 1 个（每个 session） |
| **可读性** | ❌ 低（JSON 格式） | ✅ 高（Markdown） |
| **上下文完整性** | ❌ 分散 | ✅ 连贯 |
| **LLM 加载** | ❌ 需要拼接 | ✅ 直接加载 |
| **人工审查** | ❌ 困难 | ✅ 容易 |
| **存储效率** | ⚖️ 中等 | ✅ 更好（减少文件数） |

### 🎯 适用场景

- ✅ **连续对话**：天然分组，上下文完整
- ✅ **长期学习**：每个 session 是一个学习单元
- ✅ **人工审查**：教师/管理员查看学习记录
- ✅ **LLM 上下文**：直接加载完整对话历史

---

## 实现优先级

### Phase 1: 核心功能（1-2天）
- ✅ `ConversationSessionManager` - Session 管理
- ✅ `MarkdownFormatter` - 格式化器
- ✅ 基础 MD 文件生成和追加

### Phase 2: 集成（1天）
- ✅ 集成到 `MemoryManager`
- ✅ 替换现有的 JSON artifact 保存逻辑
- ✅ 上下文加载优化

### Phase 3: 高级功能（1天）
- ✅ S3 上传/下载
- ✅ Session 自动切换（5分钟超时）
- ✅ Session 摘要生成

### Phase 4: 优化（可选）
- ✅ 双轨制（JSON + MD）
- ✅ 向后兼容
- ✅ 性能优化

---

## 下一步

**建议实施顺序**：
1. 先实现 Phase 1（核心功能）
2. 测试 5 分钟超时逻辑
3. 验证 Markdown 格式的可读性和 LLM 加载效果
4. 根据效果决定是否完全替换 JSON 系统

**是否开始实施？** 我可以立即开始编写代码。

