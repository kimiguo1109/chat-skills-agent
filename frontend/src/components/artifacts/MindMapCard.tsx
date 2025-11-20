/**
 * MindMap Card Component - 思维导图组件
 */

import { useEffect, useRef } from 'react';

// MindElixir type declarations
declare global {
  interface Window {
    MindElixir?: any;
  }
}

export interface MindMapNode {
  id: string;
  text: string;
  color?: string;
  children?: MindMapNode[];
}

export interface MindMapContent {
  root: {
    name?: string;
    text?: string;
    id: string;
    children: MindMapNode[];
    color?: string;
  };
  subject?: string;
  topic?: string;
  structure_summary?: string;
}

interface MindMapCardProps {
  content: MindMapContent;
}

export function MindMapCard({ content }: MindMapCardProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mindInstanceRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Check if MindElixir is loaded
    if (typeof window.MindElixir === 'undefined') {
      console.error('Mind Elixir library not loaded');
      if (containerRef.current) {
        containerRef.current.innerHTML = '<p class="p-4 text-red-500">思维导图库加载失败，请刷新页面重试</p>';
      }
      return;
    }

    try {
      // Convert data format
      const mindElixirData = convertToMindElixirFormat(content);

      // Initialize Mind Elixir
      const mind = new window.MindElixir({
        el: containerRef.current,
        direction: window.MindElixir.SIDE,
        draggable: true,
        contextMenu: true,
        toolBar: true,
        keypress: true,
        locale: 'zh_CN',
        allowUndo: true,
        overflowHidden: false,
        primaryLinkStyle: 2,
        primaryNodeVerticalGap: 15,
        primaryNodeHorizontalGap: 65,
        contextMenuOption: {
          focus: true,
          link: true,
          extend: [
            {
              name: '添加子节点',
              onclick: () => mind.addChild(),
            },
            {
              name: '添加兄弟节点',
              onclick: () => mind.insertSibling(),
            },
            {
              name: '编辑节点',
              onclick: () => mind.beginEdit(),
            },
            {
              name: '删除节点',
              onclick: () => mind.removeNode(),
            },
          ],
        },
      });

      // Load data
      mind.init(mindElixirData);

      // Store instance
      mindInstanceRef.current = mind;

      // Listen to events
      if (mind.bus && typeof mind.bus.addListener === 'function') {
        mind.bus.addListener('operation', (operation: any) => {
          console.log('思维导图操作:', operation.name);
        });

        mind.bus.addListener('nodeSelect', (node: any) => {
          console.log('选中节点:', node.nodeData.topic);
        });
      }

      console.log('✅ 思维导图渲染成功');
    } catch (error) {
      console.error('思维导图渲染失败:', error);
      if (containerRef.current) {
        containerRef.current.innerHTML = `<p class="p-4 text-red-500">思维导图渲染失败: ${error}</p>`;
      }
    }

    // Cleanup
    return () => {
      if (mindInstanceRef.current) {
        // MindElixir doesn't have a destroy method, but we can clear the reference
        mindInstanceRef.current = null;
      }
    };
  }, [content]);

  return (
    <div className="w-full rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-border-light dark:border-border-dark">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-2xl">account_tree</span>
            <div>
              <h3 className="text-lg font-bold text-text-light-primary dark:text-text-dark-primary">
                {content.subject || '思维导图'} - {content.topic || ''}
              </h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {content.structure_summary || ''}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-sm text-slate-500">edit</span>
            <span className="text-xs text-slate-500">可编辑</span>
          </div>
        </div>
      </div>

      {/* MindMap Container */}
      <div 
        ref={containerRef} 
        className="w-full bg-white dark:bg-slate-900" 
        style={{ height: '600px' }}
      />

      {/* Footer */}
      <div className="p-3 border-t border-border-light dark:border-border-dark bg-slate-50 dark:bg-slate-800">
        <p className="text-xs text-slate-600 dark:text-slate-400">
          💡 提示：右键点击节点可以添加、编辑、删除节点。支持拖拽移动节点位置。按 Tab 添加子节点，Enter 添加兄弟节点。
        </p>
      </div>
    </div>
  );
}

/**
 * Convert backend data to MindElixir format
 */
function convertToMindElixirFormat(mindmapData: MindMapContent) {
  const rootText = mindmapData.root.name || mindmapData.root.text || 'Root';
  
  return {
    nodeData: {
      id: mindmapData.root.id,
      topic: rootText,
      children: mindmapData.root.children.map(convertMindMapNode),
      style: {
        fontSize: '18px',
        color: mindmapData.root.color || '#10b981',
        fillColor: '#fff',
        borderColor: mindmapData.root.color || '#10b981',
        borderWidth: 2,
      },
    },
  };
}

/**
 * Recursively convert nodes
 */
function convertMindMapNode(node: MindMapNode): any {
  return {
    id: node.id,
    topic: node.text,
    children: node.children?.map(convertMindMapNode) || [],
    style: {
      fontSize: '14px',
      color: node.color || '#333',
      fillColor: '#fff',
      borderColor: node.color || '#ccc',
      borderWidth: 1,
    },
  };
}

