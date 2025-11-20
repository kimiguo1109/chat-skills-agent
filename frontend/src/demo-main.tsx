/**
 * Demo Entry Point - demo.html的React入口
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import { DemoApp } from './DemoApp';
import './index.css';

// 等待DOM加载完成
document.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('demo-root');
  
  if (root) {
    ReactDOM.createRoot(root).render(
      <React.StrictMode>
        <DemoApp />
      </React.StrictMode>
    );
    
    console.log('🚀 React Demo App mounted successfully!');
  } else {
    console.error('❌ Could not find #demo-root element');
  }
});

