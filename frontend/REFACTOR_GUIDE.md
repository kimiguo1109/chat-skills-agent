# Demo.html 重构指南

## 📖 重构说明

原来的 `demo.html` 文件有 **3000+ 行代码**，不利于维护和扩展。现在已经将其模块化重构到 React 框架中。

## 🎯 重构目标

✅ **保留所有功能** - 不影响任何现有功能
✅ **模块化架构** - 代码拆分为独立组件
✅ **类型安全** - 使用 TypeScript
✅ **易于扩展** - 清晰的代码结构
✅ **保留测试入口** - `demo.html` 和 `demo-react.html` 共存

## 📁 新的代码架构

```
src/
├── api/
│   ├── config.ts              # API配置
│   └── streamingClient.ts     # 流式API客户端
├── components/
│   ├── artifacts/             # Artifact渲染组件
│   │   ├── QuizCard.tsx       # 测验题目
│   │   ├── FlashcardCard.tsx  # 闪卡集合
│   │   ├── MindMapCard.tsx    # 思维导图
│   │   ├── NotesCard.tsx      # 学习笔记
│   │   ├── ExplainCard.tsx    # 概念讲解
│   │   └── ArtifactRenderer.tsx  # 统一渲染器
│   ├── chat/
│   │   └── StreamingMessage.tsx  # 流式消息组件
│   └── history/
│       └── HistoryPanel.tsx   # 学习历史面板
├── hooks/
│   ├── useStreaming.ts        # 流式响应hook
│   ├── useHistory.ts          # 历史记录hook
│   └── useMath.ts             # 数学公式渲染hook
├── utils/
│   ├── mathRenderer.ts        # LaTeX渲染工具
│   └── artifactUtils.ts       # Artifact工具函数
├── types/
│   └── streaming.ts           # 类型定义
├── DemoApp.tsx                # 主应用组件
└── demo-main.tsx              # demo.html入口
```

## 🚀 使用方法

### 方式1: 使用原始 demo.html（保留）

```bash
# 启动开发服务器
npm run dev

# 访问原始版本
http://localhost:3100/demo.html
```

原始的 `demo.html` **完全保留**，所有功能不变。

### 方式2: 使用 React 版本（推荐）

```bash
# 启动开发服务器
npm run dev

# 访问 React 版本
http://localhost:3100/demo-react.html
```

React 版本提供了完全相同的功能，但代码更易维护。

### 方式3: 集成到主应用

在你的应用中直接导入：

```tsx
import { DemoApp } from './src/DemoApp';

function App() {
  return <DemoApp />;
}
```

## 🔧 核心功能模块

### 1. Artifact 渲染组件

每种 artifact 类型都有独立的组件：

- **QuizCard** - 测验题目，支持答题、解析显示
- **FlashcardCard** - 闪卡，支持翻转动画、掌握标记
- **MindMapCard** - 思维导图，基于 Mind Elixir，支持编辑
- **NotesCard** - 学习笔记，支持分层结构
- **ExplainCard** - 概念讲解，支持示例和公式

### 2. 流式响应处理

```tsx
import { useStreaming } from './hooks/useStreaming';

const { sendStreamingMessage } = useStreaming();

await sendStreamingMessage(
  message,
  onChunk,    // 每个chunk的回调
  onComplete, // 完成时的回调
  onError     // 错误处理
);
```

### 3. 学习历史管理

```tsx
import { useHistory } from './hooks/useHistory';

const { historyItems, loadHistory, addToHistory } = useHistory();
```

### 4. 数学公式渲染

```tsx
import { renderMathInContent } from './utils/mathRenderer';

// 手动渲染
renderMathInContent(element);

// 或使用 hook
import { useMath } from './hooks/useMath';
const containerRef = useMath([dependencies]);
```

## 📊 重构效果对比

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| 单文件行数 | 3005行 | < 200行/文件 |
| 代码组织 | 单一HTML | 模块化组件 |
| 类型安全 | ❌ | ✅ TypeScript |
| 可复用性 | ❌ | ✅ 高度模块化 |
| 可测试性 | ❌ | ✅ 单元测试友好 |
| 维护难度 | 高 | 低 |

## 🎨 自定义和扩展

### 添加新的 Artifact 类型

1. 创建新组件：`src/components/artifacts/NewArtifact.tsx`
2. 在 `ArtifactRenderer.tsx` 中注册
3. 添加类型定义到 `utils/artifactUtils.ts`

### 自定义样式

所有组件使用 Tailwind CSS，可以直接修改类名或在 `tailwind.config.js` 中自定义。

### API 配置

修改 `src/api/config.ts`：

```ts
export const API_CONFIG = {
  BASE_URL: 'http://your-api-url',
  USER_ID: 'your-user-id',
  // ...
};
```

## 🐛 调试技巧

### 查看流式响应状态

```tsx
const { streamingStates } = useStreaming();
console.log(streamingStates);
```

### 查看历史记录

```tsx
const { historyItems } = useHistory();
console.log(historyItems);
```

## 📝 迁移清单

如果你要从 `demo.html` 迁移到 React 版本：

- [x] ✅ API 配置（`src/api/config.ts`）
- [x] ✅ 流式响应处理（`src/api/streamingClient.ts`）
- [x] ✅ Artifact 渲染（`src/components/artifacts/`）
- [x] ✅ 学习历史面板（`src/components/history/`）
- [x] ✅ 数学公式渲染（`src/utils/mathRenderer.ts`）
- [x] ✅ 主界面布局（`src/DemoApp.tsx`）

## 🚧 注意事项

1. **Mind Elixir** 需要在 HTML 中引入（已在 `demo-react.html` 中配置）
2. **KaTeX** 需要在 HTML 中引入（已配置）
3. **Material Icons** 需要在 HTML 中引入（已配置）
4. 确保后端 API 运行在 `http://localhost:8000`

## 💡 最佳实践

1. **使用 TypeScript** - 所有新代码都应该有类型定义
2. **组件解耦** - 每个组件只负责一个功能
3. **hooks 复用** - 业务逻辑封装在 hooks 中
4. **样式一致** - 使用统一的 Tailwind 类名

## 📞 问题反馈

如果遇到问题，请检查：

1. 是否安装了所有依赖：`npm install`
2. 后端是否运行：`http://localhost:8000/api/agent/chat-stream`
3. 浏览器控制台是否有错误
4. Node.js 版本是否符合要求（推荐 18+）

## 🎉 总结

重构后的代码：
- ✨ **更清晰** - 每个文件职责单一
- 🚀 **更快速** - 开发效率提升
- 🛡️ **更安全** - TypeScript 类型检查
- 🔧 **更灵活** - 易于扩展和维护

原始 `demo.html` 完全保留，可以随时切换测试！

