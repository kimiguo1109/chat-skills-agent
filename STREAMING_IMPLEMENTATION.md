# 流式思考过程实现方案

## 🎯 目标

实现流式展示AI思考过程，用户无需等待，可以实时看到：
1. **思考步骤**：AI的推理过程（逐步展示）
2. **生成内容**：最终结果（逐步展示）
3. **状态更新**：当前正在做什么

## 📊 架构设计

### 后端架构

```
┌─────────────────────────────────────────┐
│      /api/agent/chat-stream             │
│          (Server-Sent Events)           │
└────────────────┬────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────┐
│      SkillOrchestrator.execute_stream   │
│     (流式编排，逐步yield结果)           │
└────────────────┬────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────┐
│      GeminiClient.generate_stream       │
│     (Gemini API 流式调用)               │
└────────────────┬────────────────────────┘
                 │
                 ↓
┌─────────────────────────────────────────┐
│        前端 EventSource                  │
│    (实时接收并渲染)                      │
└─────────────────────────────────────────┘
```

### 数据流

```
Step 1: 状态更新
→ {"type": "status", "message": "正在分析您的请求..."}

Step 2: 意图识别完成
→ {"type": "status", "message": "开始生成题目..."}

Step 3: 思考过程（逐步）
→ {"type": "thinking", "text": "用户请求关于光合作用的题目..."}
→ {"type": "thinking", "text": "需要考虑难度和题型..."}
→ {"type": "thinking", "text": "准备生成5道选择题..."}

Step 4: 内容生成（逐步）
→ {"type": "content", "text": "{\n  \"quiz_set_id\": ..."}
→ {"type": "content", "text": "  \"questions\": [\n    {"}
→ {"type": "content", "text": "      \"question_text\": \"什么是光合作用？\""}
...

Step 5: 完成
→ {"type": "done", "thinking": "完整思考", "content": "完整内容"}
```

## ✅ 已实现部分

### 1. GeminiClient.generate_stream()

```python
async def generate_stream(
    self,
    prompt: str,
    model: str = "gemini-2.5-flash",
    thinking_budget: int = 1024
):
    """流式生成，逐步yield思考和内容"""
    stream = await self.async_client.models.generate_content_stream(
        model=model,
        contents=prompt,
        config=config
    )
    
    async for chunk in stream:
        # 提取思考部分
        if hasattr(part, 'thought'):
            yield {
                "type": "thinking",
                "text": thought_text
            }
        # 提取内容部分
        elif hasattr(part, 'text'):
            yield {
                "type": "content",
                "text": content_text
            }
    
    yield {"type": "done"}
```

### 2. API Endpoint: /api/agent/chat-stream

```python
@router.post("/chat-stream")
async def agent_chat_stream(request: ChatRequest):
    """Server-Sent Events endpoint"""
    
    async def event_generator():
        # Step 1: 意图识别
        yield "data: {...}\n\n"
        
        # Step 2: 流式执行
        async for chunk in orchestrator.execute_stream(...):
            yield f"data: {json.dumps(chunk)}\n\n"
        
        yield "data: {\"type\": \"done\"}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

## 🚧 待实现部分

### 1. SkillOrchestrator.execute_stream()

需要重构现有的 `execute()` 方法，使其支持流式输出：

```python
async def execute_stream(
    self,
    intent_result: IntentResult,
    user_id: str,
    session_id: str
):
    """流式执行技能"""
    
    # 1. 选择技能
    skill = self._select_skill(intent_result.intent)
    yield {"type": "status", "message": f"使用 {skill.display_name}"}
    
    # 2. 构建上下文
    context = await self._build_context(skill, user_id, session_id)
    
    # 3. 构建输入参数
    params = self._build_input_params(skill, intent_result, context)
    
    # 4. 加载 prompt
    prompt = self._load_prompt(skill, params)
    
    # 5. �� 流式调用 LLM
    async for chunk in self.gemini_client.generate_stream(
        prompt=prompt,
        model=skill.models.get("primary", "gemini-2.5-flash"),
        thinking_budget=skill.thinking_budget
    ):
        # 直接转发 LLM 的流式输出
        yield chunk
    
    # 6. 解析最终结果并更新 memory
    # ... (在 done 时处理)
```

### 2. 前端 EventSource

```javascript
// 创建 EventSource 连接
const eventSource = new EventSource('/api/agent/chat-stream', {
    method: 'POST',
    body: JSON.stringify({
        user_id: 'demo-user',
        session_id: 'demo-session',
        message: '给我5道光合作用的题'
    })
});

// 监听消息
eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === 'status') {
        // 更新状态提示
        updateStatus(data.message);
    } 
    else if (data.type === 'thinking') {
        // 逐步添加思考内容
        appendThinking(data.text);
    } 
    else if (data.type === 'content') {
        // 逐步添加生成内容
        appendContent(data.text);
    } 
    else if (data.type === 'done') {
        // 完成，关闭连接
        eventSource.close();
        renderFinal(data.content);
    }
};

// 错误处理
eventSource.onerror = (error) => {
    console.error('Stream error:', error);
    eventSource.close();
};
```

### 3. 前端UI实时渲染

```javascript
function appendThinking(text) {
    const thinkingDiv = document.getElementById('thinking-process');
    
    // 如果还没有思考面板，创建它
    if (!thinkingDiv) {
        createThinkingPanel();
    }
    
    // 追加文本（使用打字机效果）
    const textNode = document.createTextNode(text);
    thinkingDiv.querySelector('.content').appendChild(textNode);
    
    // 自动滚动
    thinkingDiv.scrollTop = thinkingDiv.scrollHeight;
}

function appendContent(text) {
    const contentDiv = document.getElementById('response-content');
    
    // 追加内容
    contentDiv.textContent += text;
    
    // 如果是JSON，实时尝试解析并美化显示
    try {
        const json = JSON.parse(contentDiv.textContent);
        renderPretty(json);
    } catch {
        // 还未完成，继续累积
    }
}
```

## 📋 实现步骤（按优先级）

### Phase 1: 基础流式生成 ✅

- [x] GeminiClient.generate_stream()
- [x] API endpoint /api/agent/chat-stream
- [ ] 简单前端 demo（测试流式连接）

### Phase 2: 完整流式编排 🚧

- [ ] SkillOrchestrator.execute_stream()
- [ ] 处理 prompt loading
- [ ] 处理 JSON parsing（流式JSON可能不完整）
- [ ] Memory 更新（在完成时）

### Phase 3: 前端体验优化 ⏳

- [ ] 思考过程实时展示
- [ ] 内容逐步渲染
- [ ] 打字机效果
- [ ] 加载动画
- [ ] 错误处理

### Phase 4: 高级功能 ⏳

- [ ] 暂停/继续生成
- [ ] 取消生成
- [ ] 多轮对话流式
- [ ] 并发请求管理

## 🧪 测试方案

### 1. 后端测试

```bash
# 测试流式API
curl -N -X POST http://localhost:8000/api/agent/chat-stream \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test",
    "session_id": "test",
    "message": "给我5道光合作用的题"
  }'

# 应该看到实时输出:
data: {"type": "status", "message": "正在分析您的请求..."}

data: {"type": "thinking", "text": "用户请求..."}

data: {"type": "content", "text": "{..."}

data: {"type": "done"}
```

### 2. 前端测试

```javascript
// 在浏览器控制台测试
const eventSource = new EventSource(
    'http://localhost:8000/api/agent/chat-stream?' +
    'user_id=test&session_id=test&message=test'
);

eventSource.onmessage = (e) => console.log(e.data);
```

## ⚠️ 注意事项

### 1. JSON 流式解析

流式生成的JSON可能不完整，需要处理：

```python
# 方案A: 累积完整后再解析
accumulated = ""
async for chunk in stream:
    if chunk["type"] == "content":
        accumulated += chunk["text"]

# 完成时解析
final_json = json.loads(accumulated)
```

```python
# 方案B: 使用增量JSON解析器
import ijson

parser = ijson.items(content_stream, '')
```

### 2. 错误处理

```python
try:
    async for chunk in generate_stream(...):
        yield chunk
except Exception as e:
    yield {
        "type": "error",
        "message": str(e)
    }
```

### 3. 超时处理

```python
import asyncio

try:
    async with asyncio.timeout(30):  # 30秒超时
        async for chunk in stream:
            yield chunk
except asyncio.TimeoutError:
    yield {"type": "error", "message": "请求超时"}
```

## 📊 性能对比

### 传统模式（等待完整响应）

```
用户发送请求 → [等待15秒] → 显示完整结果
```

**用户体验**: ⭐⭐ (感觉很慢，不知道在干什么)

### 流式模式（实时展示）

```
用户发送请求 
  → [0.5s] 显示"正在分析..."
  → [1s] 显示"开始生成题目..."
  → [2s] 显示思考过程 (逐步)
  → [5s-15s] 显示生成内容 (逐步)
  → [15s] 完成
```

**用户体验**: ⭐⭐⭐⭐⭐ (有反馈，知道进度，不焦虑)

## 🎯 最终效果

### 用户界面

```
┌────────────────────────────────────────┐
│  StudyX Agent                          │
├────────────────────────────────────────┤
│                                        │
│  User: 给我5道光合作用的题             │
│                                        │
│  Agent:                                │
│  ┌──────────────────────────────────┐ │
│  │ 🧠 思考过程                      │ │
│  │ ▼ 展开查看                       │ │
│  └──────────────────────────────────┘ │
│                                        │
│  [▓▓▓▓▓▓▓░░░] 正在生成题目...       │
│                                        │
│  ┌──────────────────────────────────┐ │
│  │ 题目 1:                          │ │
│  │ 光合作用的主要产物是？            │ │
│  │ A. 氧气                          │ │
│  │ B. 二氧化碳                       │ │
│  │ ...                   [生成中]   │ │
│  └──────────────────────────────────┘ │
│                                        │
└────────────────────────────────────────┘
```

## 🚀 快速开始（MVP）

### 1. 测试流式 Gemini API

```python
# test_streaming.py
import asyncio
from app.services.gemini import GeminiClient

async def test():
    client = GeminiClient()
    
    async for chunk in client.generate_stream(
        prompt="给我5道光合作用的选择题",
        thinking_budget=1024
    ):
        print(f"[{chunk['type']}] {chunk.get('text', '')[:50]}")

asyncio.run(test())
```

### 2. 测试流式 API

```bash
# 启动后端
cd backend
python -m uvicorn app.main:app --reload

# 测试（另一个终端）
curl -N -X POST http://localhost:8000/api/agent/chat-stream \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test","session_id":"test","message":"test"}'
```

### 3. 前端集成

```html
<!-- demo.html -->
<script>
function sendStreamMessage(message) {
    const url = '/api/agent/chat-stream';
    const eventSource = new EventSource(url + '?message=' + encodeURIComponent(message));
    
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('Received:', data);
        
        // TODO: 渲染到UI
    };
}
</script>
```

---

**Status**: 🚧 Phase 1 基础设施已完成，Phase 2-4 待实现
**Next**: 实现 SkillOrchestrator.execute_stream()
