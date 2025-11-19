# Skill Agent - 测试指南

快速测试 Phase 3 架构和澄清机制的核心功能。

---

## 1. 快速开始（5分钟）

### 启动服务

```bash
# 终端1: 后端
cd backend
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 终端2: 前端  
cd frontend
python3 -m http.server 3000
```

访问: `http://localhost:3000/public/demo.html`

### 基础测试

```
1. 给我5道二战历史的题   → ✅ 生成5道选择题
2. 解释一下珍珠港事件     → ✅ 生成结构化解释
3. 给我10张闪卡          → ✅ 生成10张记忆卡片
```

---

## 2. Phase 3 架构测试（10分钟）

### 规则引擎测试（0 Token）

```
测试1: 给我5道二战历史的题
✅ 规则引擎命中 (0 tokens, <0.01s)
✅ Intent: quiz_request, Topic: "二战历史", Quantity: 5

测试2: 出题目
✅ 规则引擎命中 (0 tokens)
✅ Intent: quiz_request, Topic: None
✅ 触发 Clarification 卡片
```

### 多轮对话测试

```
1️⃣ 给我5道二战历史的题      → 规则引擎 (0 tokens)
2️⃣ 解释一下第一道题          → 规则引擎 (0 tokens)
3️⃣ 根据这道题再出3道类似的   → LLM fallback (~1,500 tokens)
4️⃣ 学习一下珍珠港事件        → LLM fallback (~1,500 tokens)
5️⃣ 给我10张闪卡              → 规则引擎 (0 tokens)

平均 Token/轮: ~450 (vs Phase 1: 3,132) → 节省 85.6% ✅
```

---

## 3. 澄清机制测试（15分钟）

### Onboarding 测试（首次访问）

```bash
# 清空 session
rm backend/memory_storage/session_demo-session.json

# 测试
输入: "出题目"
✅ 显示 Onboarding 卡片
✅ 5大类推荐主题（物理、数学、历史、生物、计算机）
✅ 点击任意主题 → 自动填充消息并发送
```

### Multi-Topic Clarification 测试

```
步骤1: 讲讲机器学习       → 生成内容
步骤2: 做笔记              → ✅ 触发 Clarification
       "您想对哪个主题做笔记呢？"
       [机器学习]
步骤3: 点击 [机器学习]     → 自动填充并生成笔记
```

### Topic 提取测试

```
测试1: 做牛顿第二定律的笔记
✅ Topic: "牛顿第二定律" (不是 "做牛顿第二定律的" ❌)

测试2: 给我光合作用的闪卡
✅ Topic: "光合作用" (不是 "光合作用的" ❌)

测试3: 出题目
✅ Topic: None → 触发 Clarification
```

---

## 4. 调试技巧

### 查看后端日志

```bash
# 实时查看
tail -f backend/log/token_cost_optimized.log

# 过滤 Intent Router
tail -f backend/log/token_cost_optimized.log | grep -E "Rule-based|Token Usage"
```

### 查看 Memory 文件

```bash
# Session Context
cat backend/memory_storage/session_demo-session.json | jq .current_topic
cat backend/memory_storage/session_demo-session.json | jq '.artifact_history | length'

# Intent Router 输出（Phase 3）
cat backend/memory_storage/intent_router_output.json | jq .latest
cat backend/memory_storage/intent_router_output.json | jq .stats

# 实时监控 Intent Router
watch -n 1 'cat backend/memory_storage/intent_router_output.json | jq ".latest | {method, tokens_used}"'
```

### 浏览器调试

按 `F12` 打开开发者工具，查看：
- **Console**: 查看前端日志（📤 Sending message, 📥 Response status）
- **Network**: 查看 API 请求和响应
- **Application**: 查看 localStorage

---

## 5. 常见问题

### 后端问题

**端口被占用**:
```bash
# 查找占用端口的进程
lsof -i :8000
# 杀死进程
kill -9 <PID>
```

**Gemini API 连接失败**:
```bash
# 检查 API Key
echo $GEMINI_API_KEY
# 或检查 .env 文件
cat backend/.env | grep GEMINI_API_KEY
```

**规则引擎未命中**:
```bash
# 查看 Intent Router 输出
cat backend/memory_storage/intent_router_output.json | jq '.latest.method'
# 如果是 "llm_fallback"，检查用户输入是否明确
```

### 前端问题

**页面加载失败**:
- 检查前端服务是否启动: `lsof -i :3000`
- 确认访问 `http://localhost:3000/public/demo.html` (不是 `/demo.html`)

**Clarification 按钮不工作**:
- 打开浏览器控制台检查错误
- 确认 `messageInput` 元素存在
- 检查 `selectTopic` 函数是否正确定义

### Memory 问题

**上下文丢失**:
- **原因**: 后端重启（`uvicorn --reload`）
- **解决**: 测试时不要修改代码，或使用生产模式启动

**Topic 未继承**:
```bash
# 检查 current_topic
cat backend/memory_storage/session_demo-session.json | jq .current_topic
# 如果为空，检查规则引擎的 topic 提取逻辑
```

---

## 6. 性能验证

### Token 消耗

```bash
# 查看 Intent Router 统计
cat backend/memory_storage/intent_router_output.json | jq .stats

# 期望结果:
# - rule_success_rate >= 70%
# - total_requests > 0
# - llm_fallback < 30%
```

### 响应时间

- 规则引擎命中: **<0.01s** ✅
- LLM Fallback: **~1.6s** ✅
- Skill Execution: **~5-10s** (取决于 LLM)

---

## 🎯 完整测试清单

```
快速测试（5分钟）
  ✅ 环境检查
  ✅ 启动服务
  ✅ 3个基础功能测试

Phase 3 架构（10分钟）
  ✅ 规则引擎测试（0 Token）
  ✅ 多轮对话测试（5轮）
  ✅ Token 节省验证

澄清机制（15分钟）
  ✅ Onboarding 测试
  ✅ Clarification 测试
  ✅ Topic 提取测试

调试验证（5分钟）
  ✅ 查看 Intent Router 输出
  ✅ 验证规则命中率 >= 70%
```

**总时间**: ~35分钟

---

更多详细信息请参考:
- [FEATURES.md](FEATURES.md) - 功能详解
- [README.md](README.md) - 快速开始
