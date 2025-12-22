# App Chat API 前端对接文档

> 更新日期: 2025-12-18  
> 服务地址: `http://13.52.175.51:8088`

---

## 🔥 接口列表

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/external/chat` | POST | 发送消息 |
| `/api/external/chat/history` | GET | 获取聊天历史 |
| `/api/chat/feedback` | POST | 提交反馈 |

---

## 1️⃣ 发送消息

### 请求

```bash
curl -X POST "http://13.52.175.51:8088/api/external/chat" \
  -H "Content-Type: application/json" \
  -H "token: 用户登录token" \
  -d '{
    "message": "你好，请解释量子力学",
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890"
  }'
```

### 请求字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `message` | ✅ | 用户消息（有文件时可空） |
| `user_id` | ✅ | 用户 ID |
| `question_id` | ✅ | 题目 ID |
| `answer_id` | ✅ | 答案 ID |
| `file_uris` | 否 | GCS 文件数组 `["gs://..."]` |
| `files` | 否 | 前端回显 `[{"type":"image","url":"..."}]` |
| `referenced_text` | 否 | 引用的文本 |
| `action_type` | 否 | `explain_concept` / `make_simpler` / `common_mistakes` |
| `language` | 否 | `auto` / `en` / `zh` 等 |

### 返回

```json
{
  "code": 0,
  "msg": "Request succeeded",
  "data": {
    "session_id": "qQ12345_aA67890",
    "content_type": "text",
    "intent": "other",
    "topic": "量子力学",
    "content": {
      "text": "量子力学是研究微观粒子..."
    },
    "token_usage": {
      "total_internal_tokens": 500
    },
    "context_stats": {
      "session_turns": 5,
      "loaded_turns": 5
    }
  }
}
```

---

## 2️⃣ 引用文本 + 快捷按钮

### 引用文本

```bash
curl -X POST "http://13.52.175.51:8088/api/external/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "这一步我不太明白",
    "referenced_text": "8x - 31 = -29，移项得 8x = 2",
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890"
  }'
```

### 快捷按钮

```bash
curl -X POST "http://13.52.175.51:8088/api/external/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "",
    "action_type": "explain_concept",
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890"
  }'
```

| action_type | 说明 |
|-------------|------|
| `explain_concept` | 解释这个概念 |
| `make_simpler` | 用更简单的方式解释 |
| `common_mistakes` | 列举常见错误 |

---

## 3️⃣ 文件上传

### 单图片

```bash
curl -X POST "http://13.52.175.51:8088/api/external/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "这张图片是什么",
    "file_uris": ["gs://kimi-dev/images.jpeg"],
    "files": [{"type": "image", "url": "https://cdn.studyx.com/images.jpeg"}],
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890"
  }'
```

### 单文档

```bash
curl -X POST "http://13.52.175.51:8088/api/external/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "这个文档讲了什么",
    "file_uris": ["gs://kimi-dev/notes.txt"],
    "files": [{"type": "document", "name": "学习笔记.txt"}],
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890"
  }'
```

### 多文件

```bash
curl -X POST "http://13.52.175.51:8088/api/external/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "比较这两个文档",
    "file_uris": ["gs://kimi-dev/doc1.txt", "gs://kimi-dev/doc2.txt"],
    "files": [
      {"type": "document", "name": "文档1.txt"},
      {"type": "document", "name": "文档2.txt"}
    ],
    "user_id": "367102",
    "question_id": "Q12345",
    "answer_id": "A67890"
  }'
```

---

## 4️⃣ 获取聊天历史

### 请求

```bash
curl "http://13.52.175.51:8088/api/external/chat/history?aiQuestionId=Q12345&answerId=A67890"
```

### 返回

```json
{
  "code": 0,
  "data": {
    "question_id": "Q12345",
    "answer_id": "A67890",
    "session_id": "qQ12345_aA67890",
    "total": 5,
    "chat_list": [
      {
        "turn": 1,
        "timestamp": "08:00:00",
        "user_message": "这一步怎么理解",
        "assistant_message": "这个步骤是...",
        "referenced_text": "8x - 31 = -29",
        "files": [{"type": "image", "url": "..."}],
        "feedback": {"type": "like", "timestamp": "..."}
      }
    ]
  }
}
```

---

## 5️⃣ 提交反馈

### 请求

```bash
curl -X POST "http://13.52.175.51:8088/api/chat/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "367102",
    "session_id": "qQ12345_aA67890",
    "turn_number": 1,
    "feedback_type": "like"
  }'
```

### 反馈类型

| feedback_type | 说明 |
|---------------|------|
| `like` | 👍 点赞 |
| `dislike` | 👎 踩 |
| `report` | 报告问题 |

### 报告问题

```bash
curl -X POST "http://13.52.175.51:8088/api/chat/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "367102",
    "session_id": "qQ12345_aA67890",
    "turn_number": 1,
    "feedback_type": "report",
    "report_reason": "calculation_error",
    "report_detail": "第二步计算有错误"
  }'
```

| report_reason | 说明 |
|---------------|------|
| `calculation_error` | 计算错误 |
| `steps_confusing` | 步骤混乱 |
| `wrong_answer` | 答案错误 |
| `other` | 其他 |

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
| 单图片上传 | ✅ |
| 单文档上传 | ✅ |
| 多文件上传 | ✅ |
| 聊天历史 | ✅ |
| 反馈 API | ✅ |
| 多语言 | ✅ |

**通过率: 100%** (68/68)
