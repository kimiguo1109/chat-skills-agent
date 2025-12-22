# 📎 附件上传 API 文档

**更新日期**: 2024-11-26  
**API 地址**: http://13.52.175.51:8088

---

## 概述

支持上传文件到 GCS (`gs://kimi-dev/`)，然后在 chat/quiz/flashcard 请求中引用文件内容。

**流程**：
```
1. 上传文件 → 获取 file_uri
2. 使用 file_uri 调用 chat/createQuizs/createFlashcards
3. 外部 API 自动解析文件内容并生成结果
```

---

## API 端点

### 1. 上传文件

**POST** `/api/external/upload`

#### 请求格式 (multipart/form-data)

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | ✅ | 要上传的文件 |
| user_id | string | ❌ | 用户ID，默认 "anonymous" |

#### 支持的文件类型

- **文档**: `.txt`, `.pdf`, `.doc`, `.docx`, `.md`, `.csv`, `.json`
- **图片**: `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`
- **大小限制**: 10MB

#### 请求示例

```bash
curl -X POST http://13.52.175.51:8088/api/external/upload \
  -F "file=@ap_美国历史sample.txt" \
  -F "user_id=user_kimi"
```

#### 响应示例

```json
{
  "code": 0,
  "msg": "Upload succeeded",
  "data": {
    "file_uri": "gs://kimi-dev/user_kimi/20251126_123456_abc12345_ap_美国历史sample.txt",
    "original_name": "ap_美国历史sample.txt",
    "size": 12345,
    "content_type": "text/plain"
  }
}
```

---

### 2. 使用文件生成题目

**POST** `/api/external/createQuizs`

#### 请求格式

```json
{
  "inputList": [
    {"text": "帮我出题"},
    {"fileUri": "gs://kimi-dev/ap 美国历史sample.txt"}
  ],
  "questionCount": 5,
  "user_id": "user_kimi"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| inputList | array | ✅ | 输入列表，支持 text 和 fileUri |
| inputList[].text | string | ❌ | 文本指令 |
| inputList[].fileUri | string | ❌ | GCS 文件 URI |
| questionCount | int | ❌ | 题目数量 |
| user_id | string | ❌ | 用户ID |

#### 请求示例

```bash
curl --location 'http://13.52.175.51:8088/api/external/createQuizs' \
--header 'Content-Type: application/json' \
--data '{
    "inputList": [
        {"text": "帮我出题"},
        {"fileUri": "gs://kimi-dev/ap 美国历史sample.txt"}
    ],
    "questionCount": 3,
    "user_id": "user_kimi"
}'
```

#### 响应示例

```json
{
  "code": 0,
  "msg": "Request succeeded",
  "data": {
    "title": "伊利运河与市场革命",
    "questions": [
      {
        "question": "伊利运河连接了哪两条水体?",
        "answer_options": [
          {"text": "哈德逊河与伊利湖", "is_correct": true, "rationale": "运河连接了纽约州的哈德逊河和西部的伊利湖。"},
          {"text": "大西洋与密西西比河", "is_correct": false, "rationale": "这是运河影响范围的夸大描述。"}
        ]
      }
    ]
  }
}
```

---

### 3. 使用文件生成闪卡

**POST** `/api/external/createFlashcards`

#### 请求格式

```json
{
  "inputList": [
    {"text": "生成学习卡片"},
    {"fileUri": "gs://kimi-dev/document.txt"}
  ],
  "cardSize": 5,
  "user_id": "user_kimi"
}
```

---

### 4. 通用聊天接口（带附件）

**POST** `/api/external/chat`

#### 请求格式

```json
{
  "message": "帮我出5道题",
  "file_uri": "gs://kimi-dev/user_kimi/document.txt",
  "user_id": "user_kimi",
  "session_id": "session_123"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| message | string | ✅ | 用户消息 |
| file_uri | string | ❌ | GCS 文件 URI |
| user_id | string | ❌ | 用户ID |
| session_id | string | ❌ | 会话ID |

#### 请求示例

```bash
curl --location 'http://13.52.175.51:8088/api/external/chat' \
--header 'Content-Type: application/json' \
--data '{
    "message": "根据文件内容出5道题",
    "file_uri": "gs://kimi-dev/user_kimi/ap_history.txt",
    "user_id": "user_kimi"
}'
```

---

## 完整使用流程

### Step 1: 上传文件

```bash
# 上传文件
curl -X POST http://13.52.175.51:8088/api/external/upload \
  -F "file=@my_document.txt" \
  -F "user_id=user_kimi"

# 返回:
# {
#   "code": 0,
#   "data": {
#     "file_uri": "gs://kimi-dev/user_kimi/20251126_xxx_my_document.txt"
#   }
# }
```

### Step 2: 使用文件生成内容

```bash
# 使用返回的 file_uri 生成题目
curl --location 'http://13.52.175.51:8088/api/external/createQuizs' \
--header 'Content-Type: application/json' \
--data '{
    "inputList": [
        {"text": "根据文件内容出题"},
        {"fileUri": "gs://kimi-dev/user_kimi/20251126_xxx_my_document.txt"}
    ],
    "questionCount": 5,
    "user_id": "user_kimi"
}'
```

---

## 前端集成

前端已添加文件上传按钮，位于输入框左侧：

1. 点击 📎 按钮选择文件
2. 文件上传成功后显示绿色 ✓
3. 输入指令（如"帮我出5道题"）
4. 点击发送

**前端代码位置**: `frontend/public/demo.html` & `frontend/public/demo.js`

---

## 错误码

| code | 说明 |
|------|------|
| 0 | 成功 |
| 400 | 请求参数错误（文件类型不支持、文件过大等） |
| 500 | 服务器错误 |

---

## 注意事项

1. **GCS 配置**: 需要配置 `GOOGLE_APPLICATION_CREDENTIALS` 环境变量
2. **Mock 模式**: GCS 未配置时返回 mock URI，可用于测试
3. **文件大小**: 最大 10MB
4. **主题提取**: 外部 API 会自动从文件内容中提取主题，无需手动指定


