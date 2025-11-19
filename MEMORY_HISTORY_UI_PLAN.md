# Memory 历史记录浏览器 - demo.html 实施方案

## 📋 概述

在 `frontend/public/demo.html` 中添加 Sidebar 历史记录浏览器，允许用户查看、搜索和回溯学习历史。

---

## 🎨 UI 结构

### 页面布局

```html
<!-- demo.html 整体结构 -->
<body>
  <div class="app-container">
    <!-- 🆕 左侧 Sidebar: 历史记录 -->
    <aside id="historySidebar" class="history-sidebar">
      <!-- Sidebar 内容 -->
    </aside>
    
    <!-- 中间: Chat 区域（现有） -->
    <main class="chat-container">
      <!-- 现有 Chat 内容 -->
    </main>
    
    <!-- 右侧: 用户信息/设置（现有，可选） -->
  </div>
</body>
```

---

## 🛠️ 实施步骤

### Step 1: HTML 结构（30分钟）

```html
<!-- 在 demo.html 的 body 开始处添加 -->

<!-- 🆕 History Sidebar -->
<aside id="historySidebar" class="history-sidebar collapsed">
  <!-- Header -->
  <div class="sidebar-header">
    <h3>📚 Learning History</h3>
    <button id="toggleSidebar" class="toggle-btn">
      <svg><!-- 展开/收起图标 --></svg>
    </button>
  </div>
  
  <!-- Search & Filter -->
  <div class="sidebar-search">
    <input 
      type="text" 
      id="historySearch" 
      placeholder="🔍 Search topics..."
      class="search-input"
    />
    
    <div class="filter-buttons">
      <button class="filter-btn active" data-type="all">All</button>
      <button class="filter-btn" data-type="quiz_set">❓ Quiz</button>
      <button class="filter-btn" data-type="flashcard_set">🎴 Cards</button>
      <button class="filter-btn" data-type="notes">📝 Notes</button>
      <button class="filter-btn" data-type="explanation">💡 Explain</button>
      <button class="filter-btn" data-type="mindmap">🗺️ Map</button>
    </div>
  </div>
  
  <!-- Timeline Content -->
  <div id="historyTimeline" class="history-timeline">
    <!-- 动态加载的历史记录 -->
    
    <!-- 日期分组示例 -->
    <div class="date-group">
      <div class="date-label">📅 今天</div>
      <div class="history-items">
        <!-- 单条记录 -->
        <div class="history-item" data-artifact-id="abc123">
          <div class="item-icon">📝</div>
          <div class="item-content">
            <div class="item-title">二战历史笔记</div>
            <div class="item-meta">
              <span class="item-time">10:30 AM</span>
              <span class="item-type">Notes</span>
            </div>
          </div>
        </div>
        
        <div class="history-item" data-artifact-id="def456">
          <div class="item-icon">❓</div>
          <div class="item-content">
            <div class="item-title">光合作用题目</div>
            <div class="item-meta">
              <span class="item-time">09:15 AM</span>
              <span class="item-count">5 题</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <div class="date-group collapsed">
      <div class="date-label">📅 昨天</div>
      <div class="history-items">
        <!-- 更多记录... -->
      </div>
    </div>
    
    <!-- 加载更多 -->
    <div class="load-more">
      <button id="loadMoreHistory">Load More...</button>
    </div>
  </div>
</aside>
```

---

### Step 2: CSS 样式（1小时）

```css
/* 在 demo.html 的 <style> 中添加 */

/* App Container: Flexbox 布局 */
.app-container {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* History Sidebar */
.history-sidebar {
  width: 320px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  display: flex;
  flex-direction: column;
  transition: transform 0.3s ease;
  overflow: hidden;
}

.history-sidebar.collapsed {
  transform: translateX(-320px);
}

/* Sidebar Header */
.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}

.sidebar-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.toggle-btn {
  background: transparent;
  border: none;
  color: white;
  cursor: pointer;
  padding: 8px;
}

/* Search & Filter */
.sidebar-search {
  padding: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}

.search-input {
  width: 100%;
  padding: 10px 12px;
  border: none;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.2);
  color: white;
  font-size: 14px;
}

.search-input::placeholder {
  color: rgba(255, 255, 255, 0.6);
}

.filter-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.filter-btn {
  padding: 6px 12px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  border-radius: 20px;
  background: transparent;
  color: white;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.filter-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.filter-btn.active {
  background: white;
  color: #667eea;
  border-color: white;
}

/* Timeline */
.history-timeline {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

/* Date Group */
.date-group {
  margin-bottom: 24px;
}

.date-label {
  font-size: 14px;
  font-weight: 600;
  padding: 8px 0;
  cursor: pointer;
  display: flex;
  align-items: center;
}

.date-group.collapsed .history-items {
  display: none;
}

/* History Item */
.history-item {
  display: flex;
  align-items: flex-start;
  padding: 12px;
  margin-bottom: 8px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.history-item:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: translateX(4px);
}

.item-icon {
  font-size: 24px;
  margin-right: 12px;
}

.item-content {
  flex: 1;
}

.item-title {
  font-size: 14px;
  font-weight: 500;
  margin-bottom: 4px;
}

.item-meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  opacity: 0.8;
}

/* Load More */
.load-more {
  text-align: center;
  padding: 16px 0;
}

.load-more button {
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: white;
  padding: 8px 24px;
  border-radius: 20px;
  cursor: pointer;
}

/* Chat Container 调整 */
.chat-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  /* 现有样式保持不变 */
}

/* 响应式: 小屏幕 */
@media (max-width: 768px) {
  .history-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    height: 100vh;
    z-index: 1000;
  }
}
```

---

### Step 3: JavaScript 功能（2-3小时）

```javascript
// 在 demo.html 的 <script> 标签中添加

// ============= 历史记录管理 =============

// 全局状态
let historyData = {
  artifacts: [],
  filteredArtifacts: [],
  currentFilter: 'all',
  searchTerm: '',
  page: 1,
  hasMore: true
};

// 初始化历史记录
async function initHistory() {
  const sidebar = document.getElementById('historySidebar');
  const toggleBtn = document.getElementById('toggleSidebar');
  
  // 展开/收起 Sidebar
  toggleBtn.addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
  });
  
  // 搜索
  document.getElementById('historySearch').addEventListener('input', (e) => {
    historyData.searchTerm = e.target.value.toLowerCase();
    filterAndRenderHistory();
  });
  
  // 筛选按钮
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      historyData.currentFilter = e.target.dataset.type;
      filterAndRenderHistory();
    });
  });
  
  // 加载更多
  document.getElementById('loadMoreHistory').addEventListener('click', loadMoreHistory);
  
  // 初始加载
  await loadHistory();
}

// 加载历史记录（API 调用）
async function loadHistory() {
  try {
    const response = await fetch(
      `${API_BASE}/api/sessions/${SESSION_ID}/artifacts?page=${historyData.page}&limit=50`
    );
    const data = await response.json();
    
    historyData.artifacts = [...historyData.artifacts, ...data.artifacts];
    historyData.hasMore = data.artifacts.length === 50;
    
    filterAndRenderHistory();
  } catch (error) {
    console.error('Failed to load history:', error);
  }
}

// 加载更多
async function loadMoreHistory() {
  historyData.page += 1;
  await loadHistory();
}

// 筛选和渲染
function filterAndRenderHistory() {
  let filtered = historyData.artifacts;
  
  // 按类型筛选
  if (historyData.currentFilter !== 'all') {
    filtered = filtered.filter(item => item.artifact_type === historyData.currentFilter);
  }
  
  // 按搜索词筛选
  if (historyData.searchTerm) {
    filtered = filtered.filter(item => 
      item.topic.toLowerCase().includes(historyData.searchTerm) ||
      item.summary.toLowerCase().includes(historyData.searchTerm)
    );
  }
  
  historyData.filteredArtifacts = filtered;
  renderHistory();
}

// 渲染历史记录
function renderHistory() {
  const timeline = document.getElementById('historyTimeline');
  
  // 按日期分组
  const grouped = groupByDate(historyData.filteredArtifacts);
  
  // 生成 HTML
  let html = '';
  for (const [label, items] of Object.entries(grouped)) {
    html += `
      <div class="date-group">
        <div class="date-label">${label}</div>
        <div class="history-items">
          ${items.map(item => renderHistoryItem(item)).join('')}
        </div>
      </div>
    `;
  }
  
  // 加载更多按钮
  if (historyData.hasMore) {
    html += `
      <div class="load-more">
        <button id="loadMoreHistory">Load More...</button>
      </div>
    `;
  }
  
  timeline.innerHTML = html;
  
  // 重新绑定事件
  bindHistoryItemEvents();
}

// 渲染单条历史记录
function renderHistoryItem(item) {
  const icon = getArtifactIcon(item.artifact_type);
  const time = formatTime(item.timestamp);
  const count = getArtifactCount(item);
  
  return `
    <div class="history-item" data-artifact-id="${item.id}" onclick="viewArtifact('${item.id}')">
      <div class="item-icon">${icon}</div>
      <div class="item-content">
        <div class="item-title">${item.topic}</div>
        <div class="item-meta">
          <span class="item-time">${time}</span>
          ${count ? `<span class="item-count">${count}</span>` : ''}
        </div>
      </div>
    </div>
  `;
}

// 查看历史记录（回溯）
async function viewArtifact(artifactId) {
  try {
    // 1. 获取完整内容
    const response = await fetch(`${API_BASE}/api/artifacts/${artifactId}`);
    const artifact = await response.json();
    
    // 2. 在 Chat 中显示回溯标签
    const timestamp = formatDateTime(artifact.timestamp);
    addSystemMessage(`[回溯] ${timestamp}`);
    
    // 3. 根据类型渲染内容
    const messageData = {
      content_type: artifact.artifact_type,
      response_content: artifact.content
    };
    addAgentMessage(messageData);
    
    // 4. 显示提示
    addSystemMessage('💡 你可以基于此内容继续对话，例如："再出3道类似的题"');
    
    // 5. 设置上下文（用于后续对话）
    window.currentArtifactContext = artifact;
    
  } catch (error) {
    console.error('Failed to view artifact:', error);
    addSystemMessage('❌ 无法加载历史记录');
  }
}

// ============= 辅助函数 =============

// 按日期分组
function groupByDate(artifacts) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today - 86400000);
  const thisWeek = new Date(today - 7 * 86400000);
  
  const groups = {
    '📅 今天': [],
    '📅 昨天': [],
    '📅 本周': [],
    '📅 更早': []
  };
  
  artifacts.forEach(item => {
    const date = new Date(item.timestamp);
    if (date >= today) {
      groups['📅 今天'].push(item);
    } else if (date >= yesterday) {
      groups['📅 昨天'].push(item);
    } else if (date >= thisWeek) {
      groups['📅 本周'].push(item);
    } else {
      groups['📅 更早'].push(item);
    }
  });
  
  // 移除空分组
  Object.keys(groups).forEach(key => {
    if (groups[key].length === 0) {
      delete groups[key];
    }
  });
  
  return groups;
}

// 获取 artifact 图标
function getArtifactIcon(type) {
  const icons = {
    'quiz_set': '❓',
    'flashcard_set': '🎴',
    'notes': '📝',
    'explanation': '💡',
    'mindmap': '🗺️',
    'learning_bundle': '📦'
  };
  return icons[type] || '📄';
}

// 获取 artifact 数量
function getArtifactCount(item) {
  if (item.artifact_type === 'quiz_set') {
    return `${item.content.questions?.length || 0} 题`;
  } else if (item.artifact_type === 'flashcard_set') {
    return `${item.content.flashcards?.length || 0} 卡`;
  }
  return null;
}

// 格式化时间
function formatTime(timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function formatDateTime(timestamp) {
  const date = new Date(timestamp);
  return date.toLocaleString('zh-CN');
}

// 添加系统消息
function addSystemMessage(text) {
  const chatContainer = document.getElementById('chatMessages');
  const messageDiv = document.createElement('div');
  messageDiv.className = 'message system-message';
  messageDiv.innerHTML = `<div class="message-content">${text}</div>`;
  chatContainer.appendChild(messageDiv);
  chatContainer.scrollTop = chatContainer.scrollHeight;
}

// ============= 初始化 =============

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
  initHistory();
});
```

---

## 🔧 后端 API

### 新增端点（backend/app/api/history.py）

```python
from fastapi import APIRouter, Query
from typing import Optional, List, Dict
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/api/sessions/{session_id}/artifacts")
async def get_artifacts(
    session_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    artifact_type: Optional[str] = None
):
    """
    获取会话的历史 artifacts
    
    参数:
    - page: 页码（从1开始）
    - limit: 每页数量
    - search: 搜索关键词（按 topic/summary 搜索）
    - artifact_type: 筛选类型
    
    返回:
    - artifacts: List[ArtifactRecord]
    - total: int
    - has_more: bool
    """
    session_context = await memory_manager.get_session_context(session_id)
    artifacts = session_context.artifact_history or []
    
    # 筛选
    if search:
        artifacts = [
            a for a in artifacts 
            if search.lower() in a.topic.lower() or search.lower() in a.summary.lower()
        ]
    
    if artifact_type:
        artifacts = [a for a in artifacts if a.artifact_type == artifact_type]
    
    # 排序（最新的在前）
    artifacts.sort(key=lambda x: x.timestamp, reverse=True)
    
    # 分页
    total = len(artifacts)
    start = (page - 1) * limit
    end = start + limit
    paginated = artifacts[start:end]
    
    return {
        "artifacts": [a.dict() for a in paginated],
        "total": total,
        "has_more": end < total
    }


@router.get("/api/artifacts/{artifact_id}")
async def get_artifact_detail(artifact_id: str):
    """
    获取单个 artifact 的完整内容
    用于回溯显示
    """
    # 从所有 sessions 中查找该 artifact
    artifact = await memory_manager.find_artifact_by_id(artifact_id)
    
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    
    return artifact.dict()
```

### 在 MemoryManager 中添加查找方法

```python
# backend/app/core/memory_manager.py

class MemoryManager:
    # ... 现有方法 ...
    
    async def find_artifact_by_id(self, artifact_id: str) -> Optional[ArtifactRecord]:
        """
        从所有 sessions 中查找指定 ID 的 artifact
        """
        for session_context in self._session_contexts.values():
            for artifact in session_context.artifact_history:
                if artifact.id == artifact_id:
                    return artifact
        return None
```

---

## 📊 实施优先级

| 步骤 | 内容 | 时间 | 优先级 |
|------|------|------|--------|
| Step 1 | HTML 结构 | 30min | 🔴 高 |
| Step 2 | CSS 样式 | 1h | 🔴 高 |
| Step 3 | JavaScript 基础功能 | 1-2h | 🔴 高 |
| Step 4 | 后端 API | 1h | 🔴 高 |
| Step 5 | 搜索筛选 | 30min | 🟡 中 |
| Step 6 | 性能优化（懒加载） | 30min | 🟢 低 |

**总时间**: 4-5 小时
**预期完成**: V2.2 版本

---

## 🎯 测试场景

### 1. 基础展示
- [ ] Sidebar 正常展开/收起
- [ ] 历史记录按日期分组显示
- [ ] 显示正确的图标、主题、时间、数量

### 2. 搜索筛选
- [ ] 搜索框输入关键词，实时筛选
- [ ] 类型筛选按钮正常切换
- [ ] 筛选结果正确

### 3. 回溯显示
- [ ] 点击历史记录，Chat 中显示完整内容
- [ ] 显示回溯时间标签
- [ ] 不同类型内容正确渲染

### 4. 继续对话
- [ ] 基于回溯内容提问，系统正确识别上下文
- [ ] "再出3道类似的题" 基于当前 artifact 生成

### 5. 性能
- [ ] 大量历史记录（100+）加载流畅
- [ ] 滚动流畅，无卡顿
- [ ] 懒加载正常工作

---

## ✅ 完成标准

- ✅ UI 完整实现，样式美观
- ✅ 历史记录正确加载和显示
- ✅ 搜索筛选功能正常
- ✅ 回溯显示正确
- ✅ 可以基于历史内容继续对话
- ✅ 性能优化到位（100+ 记录无卡顿）
- ✅ 响应式设计，移动端适配

