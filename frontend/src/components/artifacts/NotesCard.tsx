/**
 * Notes Card Component - 学习笔记组件
 */

import { useEffect } from 'react';
import { renderMathInContent } from '../../utils/mathRenderer';

export interface NotesSection {
  title: string;
  content: string;
  subsections?: NotesSection[];
}

export interface NotesContent {
  structured_notes: NotesSection[];
  topic?: string;
  subject?: string;
  summary?: string;
}

interface NotesCardProps {
  content: NotesContent;
}

export function NotesCard({ content }: NotesCardProps) {
  useEffect(() => {
    const timer = setTimeout(() => {
      const elements = document.querySelectorAll('.notes-math-content');
      elements.forEach(el => renderMathInContent(el as HTMLElement));
    }, 50);
    return () => clearTimeout(timer);
  }, [content]);

  const renderSection = (section: NotesSection, level: number = 0) => {
    const headingSize = level === 0 ? 'text-xl' : level === 1 ? 'text-lg' : 'text-base';
    const marginLeft = level > 0 ? `ml-${level * 4}` : '';

    return (
      <div key={section.title} className={`mb-6 ${marginLeft}`}>
        <h4 className={`${headingSize} font-bold text-text-light-primary dark:text-text-dark-primary mb-3 flex items-center gap-2`}>
          <span className="material-symbols-outlined text-primary">
            {level === 0 ? 'folder' : 'subdirectory_arrow_right'}
          </span>
          {section.title}
        </h4>
        <div className="prose prose-slate dark:prose-invert max-w-none notes-math-content">
          <p className="text-text-light-primary dark:text-text-dark-primary leading-relaxed whitespace-pre-wrap">
            {section.content}
          </p>
        </div>
        {section.subsections && section.subsections.length > 0 && (
          <div className="mt-4 space-y-4">
            {section.subsections.map(subsection => renderSection(subsection, level + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="w-full rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-border-light dark:border-border-dark bg-gradient-to-r from-green-50 to-teal-50 dark:from-green-900/20 dark:to-teal-900/20">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary text-2xl">description</span>
          <div>
            <h3 className="text-lg font-bold text-text-light-primary dark:text-text-dark-primary">
              {content.subject || '学习笔记'} - {content.topic || '笔记'}
            </h3>
            {content.summary && (
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                {content.summary}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="p-6">
        {content.structured_notes.map(section => renderSection(section))}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-border-light dark:border-border-dark bg-slate-50 dark:bg-slate-800 flex items-center justify-between">
        <p className="text-xs text-slate-600 dark:text-slate-400">
          📝 共 {content.structured_notes.length} 个章节
        </p>
        <button className="flex items-center gap-1 px-3 py-1 rounded text-xs font-medium text-primary hover:bg-primary/10 transition-colors">
          <span className="material-symbols-outlined text-sm">download</span>
          导出笔记
        </button>
      </div>
    </div>
  );
}

