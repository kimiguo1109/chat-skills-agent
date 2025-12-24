# Skill Agent Demo - 交接文档

## 📋 项目概述

**一句话描述**: 这是一个基于 LLM 的智能学习助手 API 服务，为 StudyX App/Web 提供 AI 对话、概念讲解、习题生成、闪卡制作等功能。

**核心价值**: 
- 用户上传题目图片 → AI 自动识别并解答
- 用户点击快捷按钮 → AI 讲解概念、生成练习题
- 支持 30+ 语言的多语言输出

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端 (App / Web)                          │
│  - StudyX App (iOS/Android)                                      │
│  - StudyX Web (React)                                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     API 层 (FastAPI)                             │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐ │
│  │  App API         │  │  Web API         │  │  StudyX 兼容   │ │
│  │  /api/external/  │  │  /api/external/  │  │  /api/studyx/  │ │
│  │  chat            │  │  chat/web        │  │  v5/cloud/chat │ │
│  │  (同步响应)       │  │  (SSE 流式)      │  │  (SSE 流式)    │ │
│  └──────────────────┘  └──────────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      核心逻辑层                                   │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Skill        │  │ Intent       │  │ Conversation         │   │
│  │ Orchestrator │  │ Router       │  │ Manager              │   │
│  │ (技能编排)    │  │ (意图识别)    │  │ (会话管理)            │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LLM 服务层                                   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Gemini 2.5 Flash (主要 LLM)                              │   │
│  │  - 支持图片/PDF 多模态输入                                  │   │
│  │  - 支持 Thinking 模式                                      │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      存储层                                       │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ 本地文件系统  │  │ S3 云存储    │  │ StudyX API           │   │
│  │ (artifacts/) │  │ (持久化)     │  │ (用户信息/题目上下文)  │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔌 API 接口说明

### 1. App 端 API（同步响应）

#### `POST /api/external/chat`

**用途**: App 端主要聊天接口，返回完整 JSON 响应

**请求示例**:
```bash
curl -X POST "http://localhost:8088/api/external/chat" \
  -H "Content-Type: application/json" \
  -H "token: <用户登录token>" \
  -H "environment: prod" \
  -d '{
    "message": "请解释这道题",
    "user_id": "364593",
    "qid": "96rhh58",
    "session_id": "q20000003451_a7234"
  }'
```

**关键参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | 是 | 用户消息 |
| `user_id` | string | 是 | 用户 ID |
| `qid` | string | 否 | 题目 slug（用于获取题目上下文） |
| `session_id` | string | 否 | 会话 ID（格式: `q{question_id}_a{answer_id}`） |
| `action_type` | string | 否 | 快捷按钮类型: `explain_concept`, `make_simpler`, `common_mistakes` 等 |
| `file_uris` | array | 否 | GCS 文件 URI 列表 |
| `language` | string | 否 | 指定输出语言（如 `en`, `zh`, `ja`） |

**Header 参数**:
| Header | 说明 |
|--------|------|
| `token` | 用户登录 token（用于获取语言偏好和题目上下文） |
| `environment` | 环境标识: `dev`, `test`, `prod` |

**响应示例**:
```json
{
  "code": 0,
  "msg": "Success",
  "data": {
    "response": "这道题考察的是...",
    "intent": "other",
    "topic": "数学",
    "session_id": "q20000003451_a7234",
    "turn_id": 1
  }
}
```

---

### 2. Web 端 API（SSE 流式）

#### `POST /api/external/chat/web`

**用途**: Web 端聊天接口，返回 SSE 流式响应，支持发送/编辑/重新生成

**请求示例 - 发送新消息**:
```bash
curl -X POST "http://localhost:8088/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: <用户登录token>" \
  -H "environment: prod" \
  -d '{
    "message": "请解释这道题",
    "user_id": "364593",
    "question_id": "20000003451",
    "answer_id": "7234",
    "resource_id": "96rhh58",
    "action": "send"
  }'
```

**请求示例 - 编辑问题**:
```bash
curl -X POST "http://localhost:8088/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "364593",
    "question_id": "20000003451",
    "answer_id": "7234",
    "action": "edit",
    "turn_id": 1,
    "message": "修改后的问题内容",
    "version_path": "1:1"
  }'
```

**请求示例 - 重新生成回答**:
```bash
curl -X POST "http://localhost:8088/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "364593",
    "question_id": "20000003451",
    "answer_id": "7234",
    "action": "regenerate",
    "turn_id": 1
  }'
```

**关键参数**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | send/edit 必填 | 用户消息 |
| `user_id` | string | 是 | 用户 ID |
| `question_id` | string | 是 | 题目 ID（数字格式，用于 session_id） |
| `answer_id` | string | 是 | 答案 ID |
| `resource_id` | string | 否 | 题目 slug（如 `96rhh58`，用于获取题目上下文） |
| `action` | string | 是 | 操作类型: `send`, `edit`, `regenerate` |
| `turn_id` | int | edit/regenerate 必填 | 要操作的 turn ID |
| `version_path` | string | 否 | 版本路径，格式: `turn_id:version_id`，如 `1:2` |
| `action_type` | string | 否 | 快捷按钮类型 |

**SSE 响应格式**:
```
data: {"type": "start", "action": "send", "turn_id": null, "timestamp": "..."}
data: {"type": "thinking", "message": "Processing your request..."}
data: {"type": "intent", "intent": "other", "content_type": "text", "topic": ""}
data: {"type": "chunk", "content": "这道题"}
data: {"type": "chunk", "content": "考察的是"}
data: {"type": "done", "turn_id": 1, "intent": "other", "full_response": "这道题考察的是...", "action": "send"}
data: [DONE]
```

**Edit/Regenerate 响应额外字段**:
- `action: "edit"` 时: `version_updated: true`, `original_turn_id: 1`
- `action: "regenerate"` 时: `branch_created: true`

---

#### `POST /api/external/chat/web/clear`

**用途**: 清除会话历史

**请求示例**:
```bash
curl -X POST "http://localhost:8088/api/external/chat/web/clear" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "364593",
    "question_id": "20000003451",
    "answer_id": "7234"
  }'
```

---

#### `POST /api/external/chat/web/feedback`

**用途**: 提交点赞/踩反馈

**请求示例**:
```bash
curl -X POST "http://localhost:8088/api/external/chat/web/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "364593",
    "question_id": "20000003451",
    "answer_id": "7234",
    "turn_id": 1,
    "version_id": 2,
    "feedback_type": "like"
  }'
```

**参数说明**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `turn_id` | int | 对话轮次 |
| `version_id` | int | 版本 ID（每个版本独立 feedback） |
| `feedback_type` | string/int | `"like"`, `"dislike"`, `"cancel"` 或 `1`, `2`, `0` |

---

### 3. StudyX 兼容 API

#### `POST /api/studyx/v5/cloud/chat/newHomeChatQuestionV2`

**用途**: 兼容 StudyX 原生 App 的聊天接口

**请求示例**:
```bash
curl -X POST "http://localhost:8088/api/studyx/v5/cloud/chat/newHomeChatQuestionV2" \
  -H "Content-Type: application/json" \
  -H "token: <用户登录token>" \
  -H "environment: prod" \
  -d '{
    "promptInput": "请解释这道题",
    "aiId": 21,
    "aiQuestionId": "20000003451",
    "aiAnswerId": "7234",
    "resourceId": "96rhh58",
    "chatType": 2
  }'
```

**关键参数**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `promptInput` | string | 用户消息 |
| `aiQuestionId` | string | 题目 ID（数字格式） |
| `aiAnswerId` | string | 答案 ID |
| `resourceId` | string | 题目 slug（用于获取题目上下文）⚠️ 重要 |
| `actionType` | string | 快捷按钮类型 |
| `fileUris` | array | 文件 URI 列表 |

**SSE 响应格式（StudyX 原生格式）**:
```
data: {"code":0,"msg":"Request succeeded","data":{"contents":[{"content":"这道题","role":"assistant"}],"msgId":"20000003451","sessionId":"xxx"}}
```

#### `GET /api/studyx/v5/cloud/chat/getHomeworkChatListV2`

**用途**: 获取聊天历史（StudyX 格式）

**请求示例**:
```bash
curl "http://localhost:8088/api/studyx/v5/cloud/chat/getHomeworkChatListV2?aiQuestionId=20000003451&answerId=7234" \
  -H "token: <用户登录token>"
```

---

### 4. 历史记录 API

#### `GET /api/external/chat/history`

**用途**: App 端获取聊天历史

```bash
curl "http://localhost:8088/api/external/chat/history?session_id=q20000003451_a7234&user_id=364593"
```

#### `GET /api/external/chat/web/history`

**用途**: Web 端获取聊天历史（支持版本管理）

**请求示例**:
```bash
# 默认获取最新版本
curl "http://localhost:8088/api/external/chat/web/history?aiQuestionId=20000003451&answerId=7234"

# 指定版本路径（获取 Turn 1 的 v1 版本对话）
curl "http://localhost:8088/api/external/chat/web/history?aiQuestionId=20000003451&answerId=7234&version_path=1:1"
```

**参数说明**:
| 参数 | 类型 | 说明 |
|------|------|------|
| `aiQuestionId` | string | 题目 ID |
| `answerId` | string | 答案 ID |
| `version_path` | string | 版本路径，格式: `turn_id:version_id`，如 `1:2` |

**响应结构**:
```json
{
  "code": 0,
  "msg": "Success",
  "data": {
    "question_id": "20000003451",
    "answer_id": "7234",
    "session_id": "q20000003451_a7234",
    "user_id": "364593",
    
    "chat_list": [
      {
        "turn": 1,
        "version_id": 2,
        "total_versions": 2,
        "timestamp": "2025-12-24T01:42:52",
        "user_message": "1+1+1",
        "assistant_message": "...",
        "feedback": null,
        "can_edit": true,
        "can_regenerate": true,
        "has_versions": true,
        "is_original": false,
        "action": "regenerate"
      }
    ],
    "total": 1,
    
    "all_versions": [
      {
        "turn": 1,
        "version_id": 1,
        "total_versions": 2,
        "user_message": "1+1+1",
        "assistant_message": "原始回答...",
        "is_original": true,
        "action": "original"
      },
      {
        "turn": 1,
        "version_id": 2,
        "total_versions": 2,
        "user_message": "1+1+1",
        "assistant_message": "重新生成的回答...",
        "is_original": false,
        "action": "regenerate"
      }
    ],
    "all_versions_total": 2,
    
    "turn_versions": {
      "1": {
        "total_versions": 2,
        "versions": [
          {"version_id": 1, "is_original": true, "action": "original", "user_message": "...", "assistant_message": "..."},
          {"version_id": 2, "is_original": false, "action": "regenerate", "user_message": "...", "assistant_message": "..."}
        ]
      }
    },
    
    "current_version_path": "default",
    "has_versions": true
  }
}
```

**字段说明**:
| 字段 | 说明 |
|------|------|
| `chat_list` | 当前版本路径的对话（每个 turn 显示选中的版本） |
| `all_versions` | 所有版本列表（供版本切换使用） |
| `turn_versions` | 每个 turn 的版本详情（按 turn 分组） |
| `has_versions` | 是否有多版本（用于显示版本切换器） |
| `action` | 版本来源: `original`, `edit`, `regenerate` |

---

## 🔄 核心流程

### 流程 1: 用户发送消息

```
用户消息 → 获取语言偏好 → 获取题目上下文 → 意图识别 → 技能执行 → 返回响应
          (StudyX API)    (StudyX API)    (Skill       (Gemini
                                          Registry)    LLM)
```

### 流程 2: 语言偏好获取

```python
# 1. 从 Header 获取 token 和 environment
token = request.headers.get("token")
environment = request.headers.get("environment", "test")  # dev/test/prod

# 2. 调用 StudyX API 获取用户语言设置
GET https://{env_host}/api/studyx/v5/cloud/ai/getLangByUserId
Headers: { "token": "<token>" }

# 3. 返回语言代码
# 成功: "en", "zh", "ja", "ko" 等
# 失败（用户没设置）: 默认返回 "en"
```

### 流程 3: 题目上下文获取

```python
# 1. 需要 slug 格式的 resource_id（如 96rhh58）
# ⚠️ 不是数字格式的 question_id（如 20000003451）

# 2. 调用 StudyX API 获取题目详情
GET https://{env_host}/api/studyx/v5/cloud/ai/newQueryQuestionInfo
Params: { "id": "96rhh58", "type": "3", "routeType": "1" }
Headers: { "token": "<token>" }

# 3. 返回题目上下文
# Question: <题目内容>
# Answer: <答案内容>
```

### 流程 4: 意图识别

```python
# Skill Registry (0-token 匹配)
# 基于关键词快速识别用户意图

意图类型:
- "other" → 普通对话（直接用 LLM 回答）
- "explain_request" → 概念讲解
- "quiz_request" → 生成练习题
- "flashcard_request" → 生成闪卡
- "notes_request" → 生成笔记
- "mindmap_request" → 生成思维导图
```

### 流程 5: 版本管理（Edit/Regenerate）

```
用户操作          后端处理                    存储结构
─────────────────────────────────────────────────────────
Send 新消息  →   追加新 turn            →   Turn N v1 (original)
                                            
Edit 问题    →   替换 turn 内容         →   Turn N v1 (original) 保存到 versions.json
                保存旧版本                   Turn N v2 (edit) 替换到 MD 文件
                                            
Regenerate   →   替换 turn 回答         →   Turn N v1 (original) 保存到 versions.json
                保存旧版本                   Turn N v2 (regenerate) 替换到 MD 文件
```

**前端版本切换**:
1. 调用 `history` API 获取 `turn_versions`
2. 渲染版本切换器（如 `1/2` `2/2`）
3. 用户切换版本时，用 `version_path` 参数重新请求 `history`
4. 继续对话时，传递 `version_path` 给 `chat/web` 接口

**版本数据结构示例**:
```
Turn 1: 原始问题 "1+1"
  ├── v1 (original): "1+1 = 2"
  └── v2 (regenerate): "Let me explain: 1+1 = 2 because..."

Turn 2: 继续提问 "1+1+1"  
  ├── v1 (original): "1+1+1 = 3"
  └── v2 (edit): 问题改为 "1+1+1+2"，回答 "= 5"
```

---

## 📁 关键文件说明

```
backend/app/
├── api/
│   ├── external.py          # App 端 API（同步响应）
│   ├── external_web.py      # Web 端 API（SSE 流式）+ StudyX 兼容接口
│   └── feedback.py          # 反馈 API
├── core/
│   ├── skill_orchestrator.py    # 技能编排（调用各种 Skill）
│   ├── skill_registry.py        # 意图识别（关键词匹配）
│   ├── semantic_skill_matcher.py # 语义意图识别（embedding）
│   └── conversation_session_manager.py  # 会话管理
├── services/
│   └── gemini.py            # Gemini LLM 服务
└── prompts/                 # LLM Prompt 模板

backend/artifacts/           # 会话历史存储（按用户 ID 分目录）
└── {user_id}/
    └── q{question_id}_a{answer_id}.md
```

---

## ⚠️ 重要注意事项

### 1. qid vs question_id vs resource_id

| 字段 | 格式 | 用途 | 示例 |
|------|------|------|------|
| `question_id` | 数字 | 构建 session_id | `20000003451` |
| `resource_id` / `qid` | slug | 获取题目上下文 | `96rhh58` |

**前端需要同时传递两种 ID！**

### 2. 环境配置

| 环境 | API 域名 |
|------|----------|
| dev | `https://test.istudyx.com` |
| test | `https://test.istudyx.com` |
| prod | `https://mapp.studyxapp.com` |

### 3. Token 要求

- 获取语言偏好：需要 `token` Header
- 获取题目上下文：需要 `token` Header
- 如果没有 token，语言默认 `en`，题目上下文为空

### 4. 截断问题

如果 LLM 响应被截断：
- 检查 `max_tokens` 设置（当前 8192）
- 检查 `thinking_budget`（设为 0 可禁用思考模式，节省 tokens）

---

## 🚀 启动服务

```bash
# 一键启动
cd /root/usr/skill_agent_demo
./start_services.sh

# 查看日志
tail -f logs/backend.log

# 停止服务
./stop_services.sh
```

---

## 🧪 测试脚本

```bash
# App API 测试
./test_chat.sh

# Web API 测试
./test_chat_web.sh
```

---

## 📞 联系方式

如有问题，请联系项目负责人。

