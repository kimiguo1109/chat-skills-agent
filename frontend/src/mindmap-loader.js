/**
 * Mind Elixir 加载器
 * 用于在 demo.html 中加载本地安装的 Mind Elixir 库
 */

import MindElixir from 'mind-elixir';

// 将 MindElixir 挂载到 window 对象，供 demo.html 使用
window.MindElixir = MindElixir;

console.log('✅ Mind Elixir 已从本地加载');

