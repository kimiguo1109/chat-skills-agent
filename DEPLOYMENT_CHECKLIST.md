# 🚀 部署检查清单 - MindMap Skill

部署思维导图功能到远程服务器需要确保以下文件都已更新：

---

## 📦 后端文件 (Backend)

### 1. Skill 配置文件
```bash
backend/skills_config/mindmap_skill.yaml
```
**检查点**：
- ✅ 文件存在
- ✅ `intent_tags` 包含 `mindmap_request`, `mindmap`, `mind_map`
- ✅ `models.primary` 设置为正确的模型

### 2. Prompt 文件
```bash
backend/app/prompts/mindmap_skill.txt
```
**检查点**：
- ✅ 文件存在
- ✅ 包含完整的思维导图生成指令

### 3. Skill Orchestrator
```bash
backend/app/core/skill_orchestrator.py
```
**检查点**：
- ✅ `_wrap_output` 方法中有 mindmap 识别：
```python
elif "mindmap_id" in result or "root" in result:
    content_type = "mindmap"
```

### 4. Intent Router
```bash
backend/app/prompts/intent_router.txt
```
**检查点**：
- ✅ 支持的意图列表包含 `mindmap`
- ✅ 有 mindmap 的示例

```bash
backend/app/core/intent_router.py
```
**检查点**：
- ✅ `intent_mapping` 包含：
```python
"mindmap": "mindmap_request"
```

---

## 🎨 前端文件 (Frontend)

### 方案 A：使用 CDN（推荐用于生产环境）

修改 `frontend/public/demo.html`：

```html
<!-- Mind Elixir for Mind Map Rendering (CDN) -->
<script src="https://unpkg.com/mind-elixir@5.3.3/dist/MindElixir.iife.js"></script>
<link rel="stylesheet" href="https://unpkg.com/mind-elixir@5.3.3/dist/MindElixir.css"/>
```

**检查点**：
- ✅ 使用 `MindElixir.iife.js`（不是 min.js）
- ✅ CSS 文件名大小写正确 `MindElixir.css`
- ✅ 版本号 5.3.3

### 方案 B：使用本地文件（开发环境）

1. 安装依赖：
```bash
cd frontend
npm install mind-elixir
```

2. 创建加载器：
```bash
frontend/src/mindmap-loader.js
```

3. 修改 demo.html：
```html
<link rel="stylesheet" href="/node_modules/mind-elixir/dist/MindElixir.css">
<script type="module" src="/src/mindmap-loader.js"></script>
```

### 渲染函数

确保 `demo.html` 包含以下函数：

**检查点**：
- ✅ `renderMindMapCard(content)` - 渲染思维导图卡片
- ✅ `initializeMindMap(containerId, mindmapData)` - 初始化 Mind Elixir
- ✅ `convertToMindElixirFormat(mindmapData)` - 数据格式转换
- ✅ `convertMindMapNode(node)` - 递归节点转换

### 消息渲染

在 `addAgentMessage()` 函数中添加 mindmap 类型处理：

```javascript
else if (data.content_type === 'mindmap' && data.response_content.root) {
    contentHtml = renderMindMapCard(data.response_content);
}
```

---

## 🧪 部署后测试步骤

### 1. 验证库加载
```javascript
// 在浏览器 Console 中
typeof MindElixir
// 应该返回 "function"
```

### 2. 测试后端 API
```bash
curl -X POST http://YOUR_SERVER:8000/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test",
    "session_id": "test",
    "message": "帮我生成一个导数的思维导图"
  }'
```

**检查响应**：
- ✅ `content_type: "mindmap"`
- ✅ `response_content.root` 存在
- ✅ `response_content.mindmap_id` 存在

### 3. 端到端测试
1. 打开浏览器访问 demo.html
2. 输入："帮我生成一个导数的思维导图"
3. 验证：
   - ✅ 显示可视化思维导图（不是 JSON）
   - ✅ 有"可编辑"标识
   - ✅ 右键点击节点有菜单
   - ✅ 可以拖拽节点

---

## 🐛 常见问题排查

### 问题 1: Mind Elixir 库未加载
**症状**：Console 显示 "Mind Elixir 库未加载"  
**解决**：
1. 检查 CDN 链接是否正确
2. 检查网络能否访问 unpkg.com
3. 尝试使用备用 CDN：`https://cdn.jsdelivr.net/npm/mind-elixir@5.3.3/dist/`

### 问题 2: 返回 JSON 而不是可视化
**症状**：后端返回正确数据，但前端显示原始 JSON  
**解决**：
1. 检查 `content_type` 是否为 `"mindmap"`
2. 检查 `skill_orchestrator.py` 是否有 mindmap 识别
3. 检查前端 `addAgentMessage()` 是否处理 mindmap 类型

### 问题 3: 思维导图不可编辑
**症状**：显示思维导图但无法编辑  
**解决**：
检查 `initializeMindMap()` 配置：
```javascript
contextMenu: true,
toolBar: true,
keypress: true,
allowUndo: true,
draggable: true
```

---

## 📋 部署命令

### 后端重启
```bash
cd backend
python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端重启
```bash
cd frontend
npm run dev
# 或生产构建
npm run build
```

---

## ✅ 部署完成验证

所有以下项都应该通过：

- [ ] 后端启动无错误
- [ ] 前端启动无错误
- [ ] Mind Elixir 库加载成功（Console 无错误）
- [ ] API 测试返回正确的 mindmap 数据
- [ ] 前端显示可视化思维导图
- [ ] 思维导图可以编辑（右键菜单、拖拽）
- [ ] 快捷键工作（Tab, Enter, Delete）

---

**部署日期**：2025-11-17
**版本**：MindMap Skill v1.0

