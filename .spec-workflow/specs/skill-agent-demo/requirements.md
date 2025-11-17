# Requirements Document - Skill Agent Demo

## Introduction

这是一个 StudyX Skill Agent 系统的可演示 MVP（最小可行产品），用于展示从"工具箱模式"到"智能学习助手模式"的架构升级。该 demo 将实现核心的意图识别、记忆管理、技能编排和技能执行功能，通过一个统一的聊天界面为用户提供无缝的学习体验。

**核心价值：**
- 用户无需在多个工具间跳转，一个对话框完成所有学习任务
- 系统自动理解用户意图并选择合适的技能
- 记住学习进度和用户偏好，提供个性化体验
- 降低 token 成本（按需加载 Skill Prompt，而非大杂烩）

**Demo 场景：** 微积分学习助手，支持练习题生成和概念讲解两个核心技能。

## Alignment with Product Vision

根据 `General.md` PRD 文档，本 demo 实现了以下核心目标：

1. **用户体验提升**：从支离破碎的多工具跳转，升级为连续流畅的对话式学习
2. **高效意图分析**：轻量级 Intent Router 准确识别用户需求
3. **成本控制**：按需加载 Skill Prompt，避免大量无关上下文消耗 token
4. **可扩展架构**：通过 Skill Registry 实现技能的插件化管理

## Requirements

### Requirement 1: 统一聊天界面

**User Story:** 作为学生，我希望在一个对话界面中完成所有学习任务（解题、讲解、练习），而不是在多个工具间跳转，从而获得连续流畅的学习体验。

#### Acceptance Criteria

1. WHEN 用户打开应用 THEN 系统 SHALL 显示一个统一的聊天界面
2. WHEN 用户输入学习请求（如"给我几道极限练习题"）THEN 系统 SHALL 在同一界面中返回结构化结果
3. WHEN 用户在同一会话中提出不同类型的请求（练习 → 讲解）THEN 系统 SHALL 在同一对话流中响应，无需页面跳转
4. WHEN 系统返回不同类型的内容（练习题、文字讲解）THEN 界面 SHALL 根据内容类型自动选择合适的渲染组件

### Requirement 2: 智能意图识别

**User Story:** 作为学生，我希望系统能理解我的自然语言请求（如"帮我练习极限"），并自动判断我需要什么类型的帮助，而不需要我手动选择工具。

#### Acceptance Criteria

1. WHEN 用户输入自然语言请求 THEN Intent Router SHALL 解析出结构化意图（intent, topic, confidence）
2. WHEN 意图识别置信度 >= 0.6 THEN 系统 SHALL 接受该意图并继续执行
3. WHEN 意图识别置信度 < 0.6 THEN 系统 SHALL 返回澄清性问题（如"你是想要练习题还是概念讲解？"）
4. WHEN 用户输入包含明确关键词（如"练习题"、"讲解"）THEN 系统 SHALL 正确识别对应的意图标签（quiz、explain）
5. WHEN 识别失败 THEN 系统 SHALL fallback 到 explain 意图（默认讲解模式）

### Requirement 3: 学习记忆管理

**User Story:** 作为学生，我希望系统能记住我的学习进度和偏好（如我在哪些知识点薄弱、更喜欢练习题还是讲解），从而提供个性化的学习建议。

#### Acceptance Criteria

1. WHEN 用户首次使用 THEN Memory Manager SHALL 创建空的 UserLearningProfile 和 SessionContext
2. WHEN 用户完成一次练习 THEN 系统 SHALL 更新 mastery_map（知识点掌握度）
3. WHEN 用户多次使用某种学习方式（如连续做题）THEN 系统 SHALL 记录用户偏好（preferred_artifact）
4. WHEN Intent Router 需要上下文 THEN Memory Manager SHALL 提供简短的记忆摘要（≤ 100 tokens）
5. WHEN 会话结束 THEN SessionContext SHALL 被清理，UserLearningProfile SHALL 被持久化

### Requirement 4: 技能注册与发现

**User Story:** 作为系统开发者，我希望通过标准化的 Skill Registry 管理所有技能定义，从而快速添加新技能而不影响核心系统。

#### Acceptance Criteria

1. WHEN 系统启动 THEN Skill Registry SHALL 加载所有技能定义文件（JSON/YAML）
2. WHEN Orchestrator 需要查找技能 THEN Registry SHALL 根据 intent_tags 返回匹配的技能列表
3. WHEN 查询技能定义 THEN Registry SHALL 返回完整的 input_schema、output_schema、models 配置
4. WHEN 验证技能输入参数 THEN Registry SHALL 使用 JSON Schema 验证参数有效性
5. WHEN 添加新技能 THEN 只需创建新的 skill.json 文件，无需修改核心代码

### Requirement 5: 技能智能编排

**User Story:** 作为学生，我希望系统能自动选择最合适的技能来响应我的请求，并智能地构建执行参数（如根据我的掌握度选择练习题难度）。

#### Acceptance Criteria

1. WHEN Intent Router 返回意图结果 THEN Skill Orchestrator SHALL 从 Registry 查找匹配的技能
2. WHEN 多个技能匹配同一意图 THEN Orchestrator SHALL 根据成本、用户偏好选择最优技能
3. WHEN 构建技能输入参数 THEN Orchestrator SHALL 结合 intent、memory、user_profile 生成完整的 params + context
4. WHEN 技能执行完成 THEN Orchestrator SHALL 封装结果为统一的 artifact 格式
5. WHEN 技能执行失败 THEN Orchestrator SHALL 尝试 fallback 模型或 fallback 技能
6. WHEN 结果返回前 THEN Orchestrator SHALL 调用 Memory Manager 更新学习状态

### Requirement 6: Quiz Skill（练习题生成技能）

**User Story:** 作为学生，我希望通过说"给我几道极限练习题"来获得符合我当前掌握度的练习题，从而巩固知识点。

#### Acceptance Criteria

1. WHEN QuizSkill 被调用 THEN 它 SHALL 接收参数：topic, difficulty, num_questions
2. WHEN difficulty 未指定 THEN 系统 SHALL 根据用户 mastery_map 推断难度（weak → easy, strong → hard）
3. WHEN 调用 Gemini API THEN QuizSkill SHALL 使用 gemini-2.5-flash 模型
4. WHEN LLM 返回结果 THEN QuizSkill SHALL 验证输出符合 output_schema（questions 数组结构）
5. WHEN 输出验证通过 THEN QuizSkill SHALL 返回结构化题目列表（包含 stem, options, answer, explanation）

### Requirement 7: Explain Skill（概念讲解技能）

**User Story:** 作为学生，我希望通过说"讲讲极限的定义"来获得清晰的概念讲解，从而理解理论知识。

#### Acceptance Criteria

1. WHEN ExplainSkill 被调用 THEN 它 SHALL 接收参数：topic, depth（可选）
2. WHEN depth 未指定 THEN 系统 SHALL 根据用户 mastery 推断讲解深度（weak → basic, strong → advanced）
3. WHEN 调用 Gemini API THEN ExplainSkill SHALL 使用 gemini-2.5-flash 模型
4. WHEN LLM 返回结果 THEN ExplainSkill SHALL 返回结构化讲解内容（包含 title, content, examples）

### Requirement 8: 端到端集成流程

**User Story:** 作为学生，我希望从输入问题到获得结果的整个流程无缝衔接，感受不到系统内部的复杂性。

#### Acceptance Criteria

1. WHEN 用户发送消息 THEN 前端 SHALL 调用统一的 `/agent/chat` API
2. WHEN 后端收到请求 THEN 流程 SHALL 依次执行：Intent Router → Memory Manager → Skill Orchestrator → Skill Execute → Memory Update
3. WHEN 任一步骤失败 THEN 系统 SHALL 返回友好的错误提示（如"抱歉，我没太理解你的问题，能换个方式说吗？"）
4. WHEN 流程完成 THEN 前端 SHALL 根据 artifact 类型渲染对应的 UI 组件
5. WHEN 响应时间超过 3 秒 THEN 前端 SHALL 显示加载状态

## UI/UX Requirements

**参考设计文件：** `prd_document/ui_designs/`

本 demo 采用现代化的聊天式界面设计，遵循以下 UI/UX 原则。

### Requirement 9: 主聊天界面布局

**User Story:** 作为学生，我希望界面简洁现代，能快速找到功能入口，并且在聊天时不受干扰。

#### Acceptance Criteria

1. WHEN 用户打开应用 THEN 界面 SHALL 采用三栏布局：
   - 左侧：导航侧边栏（宽度 256px）
   - 中间：聊天主区域（自适应宽度）
   - 右侧：无（为未来扩展预留）

2. WHEN 显示侧边栏 THEN 侧边栏 SHALL 包含以下元素：
   - 顶部：StudyX Logo + "Skill Agent Demo" 标识
   - 中部：课程/场景列表（如 Dashboard、Calculus Practice、Concept Explanation）
   - 底部：New Chat 按钮、Settings、Help 入口

3. WHEN 显示顶部导航栏 THEN 顶栏 SHALL 包含：
   - 左侧：当前会话标题（如 "Calculus Practice Session"）
   - 右侧：通知图标、快捷操作图标、用户头像

4. WHEN 显示聊天区域 THEN 聊天区 SHALL 支持：
   - 垂直滚动查看历史消息
   - Agent 消息左对齐（带头像、浅色背景）
   - 用户消息右对齐（带头像、蓝色背景）
   - 加载状态显示（三个跳动的圆点动画）

5. WHEN 显示输入区域 THEN 输入框 SHALL 固定在底部，包含：
   - 文本输入框（placeholder: "Ask a calculus question or type your answer..."）
   - 发送按钮（蓝色圆形，Material Icons "send" 图标）

**设计规范：**
- **字体**：Space Grotesk（主界面）、Lexend（卡片组件）
- **配色**：
  - Primary: `#137fec`（品牌蓝）
  - Background Light: `#f6f7f8`
  - Surface Light: `#ffffff`
  - Text Primary: `#0d141b`
  - Border: `#e7edf3`
- **圆角**：默认 `0.25rem`，卡片 `0.75rem`
- **间距**：使用 Tailwind 标准间距（4px 基准）

### Requirement 10: QuizCard 组件设计

**User Story:** 作为学生，我希望练习题展示清晰，能看到进度条、选项反馈和详细解析，从而更好地学习。

#### Acceptance Criteria

1. WHEN 渲染 QuizCard THEN 卡片 SHALL 包含以下区域：
   - 顶部：主题标签（如"微积分练习"）+ 进度条 + 进度文字（Question 1 of 5）
   - 中部：题目标题（大字号加粗）
   - 选项区：单选按钮 + 选项文字
   - 底部：提交按钮（或"再来一组练习"按钮）

2. WHEN 题目未提交 THEN 选项 SHALL 显示为：
   - 未选中：灰色边框，鼠标悬停变浅蓝背景
   - 已选中：蓝色边框 + 浅蓝背景
   - 可点击切换选择

3. WHEN 用户提交答案 THEN 界面 SHALL 更新为：
   - 正确答案：绿色边框 + 绿色背景 + 绿色对勾图标
   - 错误答案（用户选择）：红色边框 + 红色背景 + 红色叉号图标
   - 其他选项：灰色边框 + 60% 透明度，禁止点击
   - 底部显示 Explanation 区域（浅灰背景，包含详细解析）

4. WHEN 显示进度条 THEN 进度条 SHALL：
   - 背景：浅灰色 `#e5e7eb`
   - 进度：蓝色渐变填充，根据 `currentQuestion / totalQuestions` 计算宽度
   - 高度：8px，圆角

5. WHEN 渲染 Explanation THEN 解析区 SHALL：
   - 标题："Explanation" 加粗
   - 内容：分段文字说明，支持数学公式展示
   - 背景：浅灰 `bg-slate-50`

**组件参考：** `prd_document/ui_designs/quizcard_(练习题)_组件/`

### Requirement 11: ExplainCard 组件设计

**User Story:** 作为学生，我希望概念讲解结构清晰、易读，包含公式和例子，从而快速理解知识点。

#### Acceptance Criteria

1. WHEN 渲染 ExplainCard THEN 卡片 SHALL 包含以下结构：
   - 标题区：概念名称（如 "The Chain Rule"），大标题加粗
   - 内容区：
     - 概念定义段落
     - 公式展示区域（居中、等宽字体、浅色背景）
     - 解释性文字
   - 例子区：
     - "Examples" 标题
     - 多个编号例子（序号圆形蓝色背景）

2. WHEN 显示公式 THEN 公式区域 SHALL：
   - 背景：浅灰 `bg-background-light`
   - 文字：等宽字体（font-mono）、加粗
   - 居中对齐
   - 上下间距 16px

3. WHEN 显示代码片段 THEN 代码 SHALL：
   - 浅蓝背景 `bg-primary/10`
   - 蓝色文字 `text-primary`
   - 内边距 4px
   - 圆角 4px

4. WHEN 显示例子列表 THEN 每个例子 SHALL：
   - 序号：蓝色圆形背景 + 白色数字（直径 24px）
   - 标题：加粗，描述例子目标
   - 步骤列表：左侧蓝色竖线，每步文字左对齐

5. WHEN 例子包含步骤 THEN 步骤列表 SHALL：
   - 左侧：2px 蓝色半透明竖线
   - 缩进：32px
   - 行间距：8px
   - 文字颜色：次要文字色 `text-secondary`

**组件参考：** `prd_document/ui_designs/explaincard_(概念讲解)_组件/`

### Requirement 12: 响应式设计与暗黑模式

**User Story:** 作为学生，我希望界面在不同设备上都能良好显示，并支持暗黑模式，从而在任何环境下舒适使用。

#### Acceptance Criteria

1. WHEN 在移动设备（< 768px）THEN 界面 SHALL：
   - 隐藏侧边栏（点击菜单图标展开）
   - 聊天区域占满屏幕宽度
   - 顶部导航栏高度不变
   - 卡片组件调整内边距为 16px（桌面为 32px）

2. WHEN 在平板设备（768px - 1024px）THEN 侧边栏 SHALL：
   - 宽度缩小至 200px
   - 导航项文字保持可读

3. WHEN 在桌面设备（> 1024px）THEN 界面 SHALL：
   - 侧边栏固定宽度 256px
   - 聊天区域最大宽度 1200px，居中显示
   - 卡片组件最大宽度 800px

4. WHEN 用户切换到暗黑模式 THEN 配色 SHALL 更新为：
   - Background Dark: `#101922`
   - Surface Dark: `#1a2632`
   - Text Dark Primary: `#f6f7f8`
   - Border Dark: `#2a3b4d`
   - 所有组件自动适配暗黑配色

5. WHEN 检测系统主题偏好 THEN 应用 SHALL 自动应用对应主题

**实现方式：**
- 使用 Tailwind CSS `dark:` 前缀定义暗黑模式样式
- 使用 CSS 变量存储主题颜色
- 使用 `prefers-color-scheme` 媒体查询检测系统偏好

### Requirement 13: 加载状态与错误提示

**User Story:** 作为学生，我希望在等待响应时看到明确的加载状态，遇到错误时看到友好的提示，从而了解系统当前状态。

#### Acceptance Criteria

1. WHEN Agent 正在思考 THEN 界面 SHALL 显示：
   - Agent 头像 + "StudyX Agent" 标签
   - 三个跳动圆点动画（bounce 动画，延迟 0.1s/0.2s/0.3s）
   - 浅色消息气泡背景

2. WHEN API 调用失败 THEN 界面 SHALL 显示：
   - Agent 消息气泡，内容为友好错误提示
   - 例如："抱歉，我遇到了一些问题。请稍后再试或换个问题。"
   - 可选：重试按钮

3. WHEN 输入框为空 THEN 发送按钮 SHALL 禁用（灰色、不可点击）

4. WHEN 用户输入内容 THEN 发送按钮 SHALL 启用（蓝色、hover 效果）

5. WHEN 提交练习题答案 THEN 提交按钮 SHALL：
   - 显示加载状态（按钮文字变为"提交中..."）
   - 禁用防止重复点击
   - 收到响应后恢复正常状态

**动画规范：**
- 跳动动画：translateY(-4px)，持续时间 1s，无限循环
- 按钮 hover：背景色 90% 透明度，过渡时间 200ms
- 选项点击：背景色过渡 150ms

### Requirement 14: 用户认证与Session持久化

**User Story:** 作为学生，我希望系统能记住我的身份，每次重新登录后自动加载我的学习偏好、历史聊天记录和知识掌握度，从而获得连续的个性化学习体验。

#### Acceptance Criteria

1. WHEN 用户首次访问应用 THEN 系统 SHALL 显示登录/注册界面
2. WHEN 用户注册新账户 THEN 系统 SHALL：
   - 验证用户名唯一性（用户名长度 3-20 字符）
   - 验证密码强度（至少 6 字符）
   - 创建用户记录并生成 JWT token
   - 自动登录并跳转到聊天界面
3. WHEN 用户登录 THEN 系统 SHALL：
   - 验证用户名和密码
   - 生成 JWT token（有效期 7 天）
   - 返回 token 和用户基本信息
   - 前端存储 token 到 localStorage
4. WHEN 已登录用户刷新页面 THEN 系统 SHALL：
   - 从 localStorage 读取 token
   - 验证 token 有效性
   - 自动加载用户的 UserLearningProfile 和历史聊天记录
5. WHEN 用户发送消息 THEN 系统 SHALL：
   - 从 token 中提取 user_id
   - 关联消息到该用户的 session
   - 持久化聊天记录到存储
6. WHEN 用户退出登录 THEN 系统 SHALL：
   - 清除前端 localStorage 中的 token
   - 清除当前会话状态
   - 返回登录界面
7. WHEN Memory Manager 需要用户数据 THEN 系统 SHALL：
   - 从持久化存储加载 UserLearningProfile
   - 加载最近 N 条历史消息作为 SessionContext
   - 分析历史记录生成用户偏好摘要
8. WHEN 用户完成一次交互 THEN 系统 SHALL：
   - 更新 UserLearningProfile（mastery_map, preferred_artifact）
   - 持久化更新到存储
   - 保存聊天记录（user message + agent response）

**存储方案：**
- **Backend**: 使用 SQLite（轻量级，无需额外服务）
- **数据表**:
  - `users` 表：user_id, username, password_hash, created_at
  - `learning_profiles` 表：user_id, mastery_map (JSON), preferred_artifact, last_active
  - `chat_history` 表：id, user_id, session_id, role, content, artifact (JSON), timestamp

**认证方式：**
- 使用 JWT (JSON Web Token) 无状态认证
- Token payload: {user_id, username, exp}
- 前端每次请求在 Authorization header 中携带 token

## Non-Functional Requirements

### Code Architecture and Modularity

- **单一职责原则**：每个模块（Intent Router、Memory Manager、Skill Orchestrator、Skills）独立实现，职责明确
- **模块化设计**：
  - 后端：每个核心模块独立的 Python 文件/包
  - 前端：UI 组件按功能拆分（ChatInterface、MessageRenderer、QuizCard、ExplainCard）
- **依赖管理**：模块间通过明确的 API 接口通信，避免循环依赖
- **清晰接口**：所有 Skill 实现统一的 `execute(params, context)` 签名

### Performance

- **Intent Router 响应时间**：≤ 500ms（使用轻量级 Gemini Flash 模型）
- **Skill 执行时间**：QuizSkill ≤ 3s，ExplainSkill ≤ 2s
- **端到端响应时间**：用户发送消息到前端渲染结果 ≤ 5s
- **Token 优化**：Intent Router prompt ≤ 200 tokens，单个 Skill prompt ≤ 500 tokens

### Security

- **API Key 保护**：Gemini API Key 存储在后端环境变量中，不暴露给前端
- **输入验证**：所有用户输入经过 Pydantic 模型验证，防止注入攻击
- **错误处理**：敏感错误信息（如 API Key 错误）不直接返回前端

### Reliability

- **Fallback 机制**：
  - Intent Router：置信度低时返回澄清问题
  - Skill 执行：主模型失败时尝试 fallback 模型
  - 网络错误：显示重试选项
- **错误日志**：所有模块异常记录到日志文件，便于调试
- **优雅降级**：当 Memory 服务不可用时，使用空上下文继续执行

### Usability

- **对话式交互**：用户只需自然语言输入，无需学习复杂操作
- **即时反馈**：加载状态、进度提示清晰可见
- **响应式设计**：界面适配桌面和移动端
- **错误提示友好**：避免技术术语，用学生能理解的语言解释问题

### Scalability & Extensibility

- **技能可扩展**：添加新 Skill 只需：
  1. 创建 `skills/{skill_id}/skill.json` 配置
  2. 实现 `skills/{skill_id}/handler.py`
  3. Registry 自动加载
- **意图可扩展**：Intent Router 支持动态添加新 intent 标签
- **存储可替换**：当前使用内存存储，接口设计支持无缝切换到 Redis/MongoDB

## Out of Scope（MVP 不包含）

以下功能在 demo 阶段不实现，但架构支持后续扩展：

- ❌ 多技能 Pipeline（BundleSkill）
- ~~❌ 用户认证系统~~ ✅ **已纳入 Requirement 14**
- ~~❌ 持久化存储（Redis/MongoDB）~~ ✅ **已纳入 Requirement 14（使用 SQLite）**
- ❌ 实时 WebSocket 更新
- ❌ 语音输入/输出
- ❌ 多语言支持
- ❌ Homework Skill、FlashcardSkill 等其他技能
- ❌ 完整的用户画像分析（简化版 mastery_map）
- ❌ 成本监控和预算控制
- ❌ 密码重置/找回功能
- ❌ OAuth 第三方登录（Google/GitHub）
- ❌ 用户头像上传

## Success Metrics

Demo 成功的标准：

1. ✅ 用户能在一个界面完成"练习题 → 讲解 → 再练习"的完整学习流程
2. ✅ Intent Router 对明确意图的识别准确率 > 85%
3. ✅ 端到端响应时间 < 5 秒
4. ✅ 系统能记住用户在会话中的主题切换
5. ✅ 代码结构清晰，新增一个 Skill 只需 < 50 行代码
6. ✅ 演示视频能展示核心价值：从工具箱到智能助手的体验提升
7. 🆕 用户能注册/登录，退出后重新登录时自动加载历史偏好和聊天记录
8. 🆕 系统能根据用户历史行为（如连续3次使用闪卡）持久化偏好，影响后续意图识别
9. 🆕 多用户场景：不同用户的数据完全隔离，互不影响

