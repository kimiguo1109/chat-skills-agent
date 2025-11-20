# 🚀 Demo 快速启动指南

## 启动方式

### 1. 启动 React 版本（推荐）

```bash
npm run dev:demo
```

这将自动打开浏览器，访问 `http://localhost:3100/demo-react.html`

### 2. 启动开发服务器，手动访问

```bash
npm run dev
```

然后访问：
- React 版本：`http://localhost:3100/demo-react.html` ✨ **推荐**
- 原始版本：`http://localhost:3100/demo.html` （保留作为参考）

## 版本对比

| 功能 | demo.html（原版） | demo-react.html（新版） |
|------|-------------------|------------------------|
| 代码行数 | 3005行 | 模块化 < 200行/文件 |
| 类型安全 | ❌ | ✅ TypeScript |
| 可维护性 | 低 | 高 |
| 可扩展性 | 低 | 高 |
| 功能完整性 | ✅ | ✅ 完全一致 |

## 功能清单

✅ 流式聊天响应
✅ Thinking 过程显示
✅ 学习计划步骤追踪
✅ Artifact 渲染（Quiz、Flashcard、MindMap、Notes、Explanation）
✅ 学习历史面板
✅ LaTeX 数学公式渲染
✅ 暗黑模式支持

## 更多信息

查看 [REFACTOR_GUIDE.md](./REFACTOR_GUIDE.md) 了解详细的重构说明。

