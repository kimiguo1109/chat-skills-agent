# Web Chat API 前端对接文档

> 更新日期: 2025-12-22  
> 服务地址: `https://chatweb.studyx.ai`  
> 内部地址: `http://35.83.184.237:28011`

---

## 🔥 接口列表

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/external/chat/web` | POST | 流式发送消息（SSE） |
| `/api/external/chat/web/clear` | POST | 清除会话 |
| `/api/external/chat/web/sessions` | GET | 获取用户会话列表 |
| `/api/external/chat/web/history` | GET | 获取单个会话聊天记录 |
| `/api/external/chat/web/versions` | GET | 获取版本历史（Edit/Regenerate） |
| `/api/external/chat/web/status` | GET | 获取会话状态 |

---

## 1️⃣ 发送消息（流式）

### 请求

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "你好，请解释量子力学",
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890",
    "action": "send"
  }'
```

### 请求字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `message` | ✅ | 用户消息（regenerate 时可空） |
| `user_id` | ✅ | 用户 ID |
| `question_id` | ✅ | 题目 ID |
| `answer_id` | ✅ | 答案 ID |
| `action` | 否 | `send`(默认) / `edit` / `regenerate` |
| `turn_id` | 条件 | edit/regenerate 时必填 |
| `file_uris` | 否 | GCS 文件数组 `["gs://..."]` |
| `files` | 否 | 前端回显 `[{"type":"image","url":"..."}]` |
| `referenced_text` | 否 | 引用的文本 |
| `action_type` | 否 | `explain_concept` / `make_simpler` / `common_mistakes` |
| `language` | 否 | `auto` / `en` / `zh` 等 |
| `qid` | 否 | 题目 slug（如 `96rhhg4`），用于获取题目上下文 |
| `resource_id` | 否 | 题目资源 ID（与 `qid` 作用相同，前端推荐用此字段） |
| `question_context` | 否 | 题目上下文文本（优先级最高） |

### 返回（SSE 事件流）

```
data: {"type": "start", "timestamp": "2025-12-18T08:00:00"}

data: {"type": "intent", "intent": "other", "content_type": "text", "topic": "量子力学"}

data: {"type": "chunk", "content": "量子力学是"}
data: {"type": "chunk", "content": "研究微观粒子"}
data: {"type": "chunk", "content": "的物理学分支..."}

data: {"type": "done", "turn_id": 5, "intent": "other", "full_response": "量子力学是研究微观粒子的物理学分支...", "elapsed_time": 2.5}
```

### SSE 事件类型

| type | 说明 | 关键字段 |
|------|------|----------|
| `start` | 开始 | `timestamp` |
| `intent` | 意图识别 | `intent`, `content_type`, `topic` |
| `chunk` | 内容块 | `content` |
| `done` | 完成 | `turn_id`, `full_response`, `elapsed_time` |
| `error` | 错误 | `message` |

### 题目上下文（qid / resource_id / question_context）

用于快捷按钮场景，让 AI 理解当前题目：

| 方式 | 字段 | 说明 |
|------|------|------|
| 方式一 | `resource_id` | **推荐** - 传题目资源 ID，后端调 `newQueryQuestionInfo` 获取内容 |
| 方式二 | `qid` | 同 `resource_id`，题目 slug（如 `96rhhg4`） |
| 方式三 | `question_context` | 直接传题目文本（优先级最高） |

**优先级：** `question_context` > `qid` / `resource_id`

**注意：**
- `qid` / `resource_id` 方式需要 Header 带有效 `token`
- 仅新会话首次请求需要传，后续追问自动继承上下文

---

## 2️⃣ Edit（编辑历史）

### 请求

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "用更简单的方式解释",
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890",
    "action": "edit",
    "turn_id": 3
  }'
```

| 字段 | 说明 |
|------|------|
| `action` | 固定 `"edit"` |
| `turn_id` | 要编辑的轮次号 |
| `message` | 新的问题 |

---

## 3️⃣ Regenerate（重新生成）

### 请求

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "",
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890",
    "action": "regenerate",
    "turn_id": 3
  }'
```

| 字段 | 说明 |
|------|------|
| `action` | 固定 `"regenerate"` |
| `turn_id` | 要重新生成的轮次号 |
| `message` | 可以为空 |

---

## 4️⃣ 引用文本 + 快捷按钮

### 引用文本

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "这一步我不太明白",
    "referenced_text": "8x - 31 = -29，移项得 8x = 2",
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890",
    "action": "send"
  }'
```

### 快捷按钮

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "",
    "action_type": "explain_concept",
    "resource_id": "96rhhg4",
    "user_id": "367102",
    "question_id": "20000003474",
    "answer_id": "7244",
    "action": "send"
  }'
```

| action_type | 说明 |
|-------------|------|
| `explain_concept` | 解释这个概念 |
| `make_simpler` | 用更简单的方式解释 |
| `common_mistakes` | 列举常见错误 |

**重要：** 使用快捷按钮时，需传 `resource_id` 让 AI 获取题目上下文

---

## 5️⃣ 文件上传

### GCS URI 自动转换

后端会自动将 GCS URI 转换为 HTTPS URL 下载：
```
gs://studyx_test/temp/xxx.jpg → https://files.istudyx.com/temp/xxx.jpg
```

### 单图片

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "这张图片是什么",
    "file_uris": ["gs://studyx_test/temp/8c77f68a/xxx.jpg"],
    "files": [{"type": "image", "url": "https://files.istudyx.com/temp/8c77f68a/xxx.jpg"}],
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890",
    "action": "send"
  }'
```

### 单文档

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "这个文档讲了什么",
    "file_uris": ["gs://studyx_test/temp/notes.txt"],
    "files": [{"type": "document", "name": "学习笔记.txt"}],
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890",
    "action": "send"
  }'
```

### 多文件

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "比较这两个文档",
    "file_uris": ["gs://studyx_test/temp/doc1.txt", "gs://studyx_test/temp/doc2.txt"],
    "files": [
      {"type": "document", "name": "文档1.txt"},
      {"type": "document", "name": "文档2.txt"}
    ],
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890",
    "action": "send"
  }'
```

### 纯文件上传（无文字消息）

```bash
curl -N -X POST "https://chatweb.studyx.ai/api/external/chat/web" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "",
    "file_uris": ["gs://studyx_test/temp/photo.jpg"],
    "files": [{"type": "image", "url": "https://files.istudyx.com/temp/photo.jpg"}],
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890",
    "action": "send"
  }'
```

**注意：** `message` 为空时，后端会根据用户语言自动生成默认提示（如"请分析这张图片"）

---

## 6️⃣ 获取会话列表

### 请求

```bash
curl "https://chatweb.studyx.ai/api/external/chat/web/sessions?user_id=367102&page=1&limit=20"
```

### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `user_id` | ✅ | 用户 ID |
| `page` | 否 | 页码（默认 1） |
| `limit` | 否 | 每页数量（默认 20，最大 50） |

### 返回

```json
{
  "code": 0,
  "msg": "Success",
  "data": {
    "user_id": "367102",
    "sessions": [
      {
        "session_id": "q20000003084_a7041",
        "question_id": "20000003084",
        "answer_id": "7041",
        "turn_count": 2,
        "created_at": "2025-12-18T01:40:18",
        "updated_at": "2025-12-18T01:40:18",
        "first_timestamp": "01:40:12"
      }
    ],
    "total": 10,
    "page": 1,
    "limit": 20,
    "has_more": false
  }
}
```

---

## 7️⃣ 获取聊天历史

### 请求

```bash
curl "https://chatweb.studyx.ai/api/external/chat/web/history?aiQuestionId=20000003084&answerId=7041"
```

### 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `aiQuestionId` | ✅ | 题目 ID |
| `answerId` | ✅ | 答案 ID |

### 返回

```json
{
  "code": 0,
  "msg": "Success",
  "data": {
    "question_id": "20000003084",
    "answer_id": "7041",
    "session_id": "q20000003084_a7041",
    "user_id": "367102",
    "chat_list": [
      {
        "turn": 1,
        "timestamp": "01:40:12",
        "user_message": "Please explain this concept",
        "assistant_message": "Hello! The concept involves...",
        "referenced_text": null,
        "files": null,
        "feedback": null
      }
    ],
    "total": 2
  }
}
```

---

## 8️⃣ 清除会话

### 请求

```bash
curl -X POST "https://chatweb.studyx.ai/api/external/chat/web/clear" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890"
  }'
```

### 返回

```json
{
  "code": 0,
  "msg": "Session cleared successfully",
  "data": {
    "session_id": "qQ12345_aA67890",
    "previous_turns": 15,
    "archived": true,
    "new_session_ready": true
  }
}
```

---

## 9️⃣ 获取版本历史

### 请求

```bash
curl "https://chatweb.studyx.ai/api/external/chat/web/versions?user_id=367102&question_id=Q12345&answer_id=A67890"
```

### 返回

```json
{
  "code": 0,
  "data": {
    "session_id": "qQ12345_aA67890",
    "total_versions": 2,
    "versions": [
      {
        "version_id": 1,
        "action": "edit",
        "turn_id": 3,
        "timestamp": "2025-12-18T08:00:00"
      }
    ]
  }
}
```

---

## 🔟 获取会话状态

### 请求

```bash
curl "https://chatweb.studyx.ai/api/external/chat/web/status?user_id=367102&question_id=Q12345&answer_id=A67890"
```

### 返回

```json
{
  "code": 0,
  "data": {
    "session_id": "qQ12345_aA67890",
    "turn_count": 10,
    "version_count": 2,
    "is_processing": false,
    "exists": true
  }
}
```

---

## 📱 files 数组格式

```json
{
  "files": [
    {"type": "image", "url": "https://cdn.studyx.com/img.jpg"},
    {"type": "document", "name": "笔记.pdf"}
  ]
}
```

| 字段 | 说明 |
|------|------|
| `type` | `image` 或 `document` |
| `url` | 图片用，HTTP URL |
| `name` | 文档用，文件名 |

---

## 🌐 多语言

| language | 说明 |
|----------|------|
| `auto` | 自动检测（默认） |
| `en` | English |
| `zh` | 简体中文 |
| `zh-TW` | 繁體中文 |
| `ja` | 日本語 |
| `ko` | 한국어 |
| `fr` | Français |
| `es` | Español |

不传 `language` 时，自动从 StudyX 用户设置获取。

---

## 📱 与 App 端区别

| 功能 | App 端 `/api/external/chat` | Web 端 `/api/external/chat/web` |
|------|---------------------------|-------------------------------|
| 输出格式 | JSON | SSE 流式 |
| Edit/Regenerate | ❌ | ✅ |
| Clear Session | ❌ | ✅ |
| 版本历史 | ❌ | ✅ |

---

## 🧪 测试结果

| 测试项 | 状态 |
|--------|------|
| 普通对话 | ✅ |
| Quiz 生成 | ✅ |
| Flashcard 生成 | ✅ |
| Explain 讲解 | ✅ |
| Plan Skill | ✅ |
| 上下文追问 | ✅ |
| 引用文本 | ✅ |
| 快捷按钮 | ✅ |
| 快捷按钮 + resource_id | ✅ |
| 单图片上传 | ✅ |
| 单文档上传 | ✅ |
| 多文件上传 | ✅ |
| 纯文件上传（无文字） | ✅ |
| GCS URI → HTTPS 转换 | ✅ |
| Edit 功能 | ✅ |
| Regenerate | ✅ |
| 会话列表 | ✅ |
| 聊天历史 | ✅ |
| 清除会话 | ✅ |
| 版本历史 | ✅ |
| 多语言支持 | ✅ |

**通过率: 100%** (21/21)
