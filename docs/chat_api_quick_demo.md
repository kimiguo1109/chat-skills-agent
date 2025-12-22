# Chat API Quick Demo

> 快速演示所有功能

---

## 🔗 API 端点

| 端点 | 用途 |
|------|------|
| `POST /api/chat/send` | 纯 Chat + 上下文管理 |
| `POST /api/external/chat` | Skill 框架 + 技能调用 |

---

## 📋 功能演示

### 1. 纯文本对话

```bash
# 基础对话
curl -s http://13.52.175.51:8088/api/chat/send \
  -H "Content-Type: application/json" \
  -d '{"message":"你好，我想学习物理","user_id":"demo","session_id":"demo_001"}'

# 上下文追问
curl -s http://13.52.175.51:8088/api/chat/send \
  -H "Content-Type: application/json" \
  -d '{"message":"能举个例子吗","user_id":"demo","session_id":"demo_001"}'
```

### 2. 图片识别

```bash
# 图片内容描述
curl -s http://13.52.175.51:8088/api/chat/send \
  -H "Content-Type: application/json" \
  -d '{
    "message":"这张图片是什么",
    "user_id":"demo",
    "session_id":"demo_001",
    "file_uris":["gs://kimi-dev/images.jpeg"]
  }'
```

### 3. 文档理解

```bash
# 单文档分析
curl -s http://13.52.175.51:8088/api/chat/send \
  -H "Content-Type: application/json" \
  -d '{
    "message":"这个文件讲了什么",
    "user_id":"demo",
    "session_id":"demo_001",
    "file_uris":["gs://kimi-dev/ap 美国历史sample.txt"]
  }'

# 多文档比较
curl -s http://13.52.175.51:8088/api/chat/send \
  -H "Content-Type: application/json" \
  -d '{
    "message":"比较这两个文件",
    "user_id":"demo",
    "session_id":"demo_001",
    "file_uris":["gs://kimi-dev/ap 美国历史sample.txt","gs://kimi-dev/ap 美国历史sample 2.txt"]
  }'
```

### 4. 技能调用 (Skill Framework)

```bash
# Quiz 出题
curl -s http://13.52.175.51:8088/api/external/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"给我3道光合作用的题","user_id":"demo","session_id":"demo_skill"}'

# 闪卡生成
curl -s http://13.52.175.51:8088/api/external/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"生成2张化学键的闪卡","user_id":"demo","session_id":"demo_skill"}'

# 继续出题 (上下文继承)
curl -s http://13.52.175.51:8088/api/external/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"再来2道题","user_id":"demo","session_id":"demo_skill"}'
```

### 5. 智能检索 (早期对话回溯)

```bash
# 时间引用 - "回到最开始"
curl -s http://13.52.175.51:8088/api/chat/send \
  -H "Content-Type: application/json" \
  -d '{"message":"回到最开始讲的内容","user_id":"demo","session_id":"demo_001"}'

# 索引引用 - "第一个问题"
curl -s http://13.52.175.51:8088/api/chat/send \
  -H "Content-Type: application/json" \
  -d '{"message":"第一个问题讲的是什么","user_id":"demo","session_id":"demo_001"}'
```

### 6. 文件 + 技能

```bash
# 文档出题
curl -s http://13.52.175.51:8088/api/external/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message":"根据文件出3道题",
    "user_id":"demo",
    "session_id":"demo_skill",
    "file_uris":["gs://kimi-dev/ap 美国历史sample.txt"]
  }'
```

---

## 📊 响应格式

### Pure Chat (`/api/chat/send`)

```json
{
  "code": 0,
  "data": {
    "text": "回复内容...",
    "session_id": "demo_001",
    "token_usage": {
      "llm_generation": {"input": 500, "output": 150, "total": 650},
      "total": {"total": 650}
    },
    "context_stats": {
      "session_turns": 5,
      "loaded_turns": 5,
      "retrieved_turns": 0
    }
  }
}
```

### Skill Framework (`/api/external/chat`)

```json
{
  "code": 0,
  "data": {
    "content_type": "quiz_set",
    "intent": "quiz_request",
    "topic": "Photosynthesis",
    "content": { "questions": [...] },
    "token_usage": { "total_internal_tokens": 1500 }
  }
}
```

---

## 🔧 统计 API

```bash
# Token 统计
curl -s http://13.52.175.51:8088/api/external/token-stats/today
```

