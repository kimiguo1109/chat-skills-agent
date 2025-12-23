# Web Chat API 前端接入指南

> 更新时间: 2025-12-23

## 基础信息

- **API 地址**: `http://13.52.175.51:8088`
- **接口前缀**: `/api/external/chat/web`

---

## 1. 发送消息

### 请求
```http
POST /api/external/chat/web
Content-Type: application/json
```

```json
{
  "user_id": "364593",
  "question_id": "20000003596",
  "answer_id": "7310",
  "resource_id": "96rhhjg",
  "action": "send",
  "message": "What is the main concept?"
}
```

### SSE 响应流
```
data: {"type": "start", "action": "send", "turn_id": null}
data: {"type": "thinking", "message": "Processing your request..."}
data: {"type": "intent", "intent": "explain", "content_type": "explanation", "topic": "..."}
data: {"type": "chunk", "content": "第一段内容..."}
data: {"type": "chunk", "content": "第二段内容..."}
data: {"type": "done", "turn_id": 1, "action": "send", "full_response": "完整回答内容"}
data: [DONE]
```

### 前端处理
```javascript
// 追加新消息到聊天列表
appendMessage({
  turn: event.turn_id,
  userMessage: message,
  assistantMessage: event.full_response
});
```

---

## 2. 编辑问题 (Edit)

> **行为**: 修改问题后，**替换**原 turn 的内容（问题 + 回答）

### 请求
```json
{
  "user_id": "364593",
  "question_id": "20000003596",
  "answer_id": "7310",
  "action": "edit",
  "turn_id": 1,
  "message": "修改后的新问题"
}
```

### 关键响应字段
```json
{
  "type": "done",
  "turn_id": 1,
  "action": "edit",
  "version_updated": true,
  "original_turn_id": 1,
  "full_response": "新的回答内容"
}
```

### 前端处理
```javascript
if (event.action === "edit" && event.version_updated) {
  // 替换对应 turn 的内容（不是追加）
  updateTurn(event.turn_id, {
    userMessage: newQuestion,
    assistantMessage: event.full_response
  });
}
```

---

## 3. 重新生成 (Regenerate)

> **行为**: 保持问题不变，重新生成回答，**追加**为新 turn

### 请求
```json
{
  "user_id": "364593",
  "question_id": "20000003596",
  "answer_id": "7310",
  "action": "regenerate",
  "turn_id": 1
}
```

### 关键响应字段
```json
{
  "type": "done",
  "turn_id": 2,
  "action": "regenerate",
  "branch_created": true,
  "full_response": "重新生成的回答内容"
}
```

### 前端处理
```javascript
if (event.action === "regenerate") {
  // 追加新消息（问题复用原问题）
  appendMessage({
    turn: event.turn_id,
    userMessage: originalQuestion,  // 原问题不变
    assistantMessage: event.full_response
  });
}
```

---

## 4. 获取历史记录

### 请求
```http
GET /api/external/chat/web/history?aiQuestionId=20000003596&answerId=7310
```

### 响应
```json
{
  "code": 0,
  "data": {
    "chat_list": [
      {
        "turn": 1,
        "timestamp": "07:06:53",
        "user_message": "What is addition?",
        "assistant_message": "Addition is...",
        "has_versions": true,
        "can_edit": true,
        "can_regenerate": true,
        "feedback": null
      },
      {
        "turn": 2,
        "timestamp": "07:07:08",
        "user_message": "What is addition?",
        "assistant_message": "Let me explain again...",
        "has_versions": false,
        "can_edit": true,
        "can_regenerate": true,
        "feedback": {"type": 1}
      }
    ],
    "total": 2
  }
}
```

### 字段说明
| 字段 | 说明 |
|------|------|
| `has_versions` | 该 turn 是否有历史版本（Edit 后为 true） |
| `can_edit` | 是否可编辑 |
| `can_regenerate` | 是否可重新生成 |
| `feedback` | 反馈状态 (1=赞, -1=踩, null=无) |

---

## 5. 清除会话

### 请求
```http
POST /api/external/chat/web/clear
```

```json
{
  "user_id": "364593",
  "question_id": "20000003596",
  "answer_id": "7310"
}
```

### 响应
```json
{
  "code": 0,
  "msg": "Session cleared successfully"
}
```

---

## 6. 反馈 (点赞/踩)

### 提交反馈
```http
POST /api/external/chat/web/feedback
```

```json
{
  "user_id": "364593",
  "question_id": "20000003596",
  "answer_id": "7310",
  "turn_number": 1,
  "feedback_type": 1
}
```

| feedback_type | 含义 |
|---------------|------|
| `1` | 赞 👍 |
| `-1` | 踩 👎 |
| `0` | 取消反馈 |

### 获取反馈
```http
GET /api/external/chat/web/feedback?user_id=364593&question_id=20000003596&answer_id=7310
```

---

## 7. 快捷操作 (Quick Actions)

发送消息时，可通过 `action_type` 触发快捷操作：

```json
{
  "action": "send",
  "action_type": "explain_concept",
  "message": "",
  "resource_id": "96rhhjg"
}
```

| action_type | 说明 |
|-------------|------|
| `explain_concept` | 解释概念 |
| `make_simpler` | 简化解释 |
| `common_mistakes` | 常见错误 |

---

## 8. Edit vs Regenerate 对比

| 操作 | 请求字段 | 行为 | turn_id 返回 |
|------|---------|------|-------------|
| **Edit** | `action:"edit"` + `message:"新问题"` | 替换原 turn | 原 turn_id |
| **Regenerate** | `action:"regenerate"` | 追加新 turn | 新 turn_id |

---

## 9. 版本追踪 (version_path)

当用户切换到某个版本后继续提问时，需要传递 `version_path` 字段，让后端知道当前上下文：

### 请求示例
```json
{
  "user_id": "364593",
  "question_id": "20000003596",
  "answer_id": "7310",
  "action": "send",
  "message": "Can you explain more?",
  "version_path": "1:1"  // 表示在 Turn 1 的 version 1 下继续提问
}
```

### version_path 格式
| 格式 | 含义 |
|------|------|
| `"1:1"` | Turn 1 的 version 1（原始版本） |
| `"1:2"` | Turn 1 的 version 2（Edit/Regenerate 后的版本） |
| 不传或 `null` | 使用当前活动分支（最新版本） |

### History 返回的版本信息
```json
{
  "data": {
    "chat_list": [...],
    "version_info": {
      "1": {
        "has_versions": true,
        "versions": [
          {"version_id": 1, "turn_in_list": 1, "answer_preview": "1+1=2", "children_turns": []},
          {"version_id": 2, "turn_in_list": 2, "answer_preview": "1+1+1=3", "children_turns": [3]}
        ]
      }
    },
    "current_version_path": "default"
  }
}
```

### 前端处理流程
1. 用户点击切换到 version 1
2. 前端调用 `history?version_path=1:1` 获取 v1 的对话
3. 用户在 v1 下发送新消息
4. 前端发送: `{"action": "send", "message": "...", "version_path": "1:1"}`
5. 后端在 v1 分支下追加新 turn

---

## 10. 完整请求字段参考

```typescript
interface WebChatRequest {
  // 必填
  user_id: string;
  question_id: string;
  answer_id: string;
  
  // 操作类型
  action: "send" | "edit" | "regenerate";
  
  // Edit/Regenerate 时必填
  turn_id?: number;
  
  // Send/Edit 时的消息内容
  message?: string;
  
  // 🆕 版本追踪
  version_path?: string;     // 格式: "turn_id:version_id"，如 "1:2"
  
  // 可选
  resource_id?: string;      // 题目 slug
  action_type?: string;      // 快捷操作
  referenced_text?: string;  // 引用文本
  language?: string;         // 语言
}
```

---

## 11. SSE 事件类型

| type | 说明 | 关键字段 |
|------|------|---------|
| `start` | 开始处理 | `action`, `turn_id` |
| `thinking` | 思考中 | `message` |
| `intent` | 意图识别结果 | `intent`, `topic` |
| `chunk` | 内容片段（流式） | `content` |
| `done` | 完成 | `turn_id`, `full_response`, `action` |
| `error` | 错误 | `message` |

---

## 有问题？

联系后端开发确认。

