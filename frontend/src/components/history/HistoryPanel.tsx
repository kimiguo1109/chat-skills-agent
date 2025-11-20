/**
 * History Panel Component - 学习历史记录面板
 */

import { useState, useEffect } from 'react';
import { useHistory } from '../../hooks/useHistory';
import { getArtifactIcon, getArtifactCount, formatTime } from '../../utils/artifactUtils';
import type { ArtifactItem } from '../../utils/artifactUtils';

interface HistoryPanelProps {
  isOpen: boolean;
  onClose: () => void;
  onArtifactSelect?: (item: ArtifactItem) => void;
}

export function HistoryPanel({ isOpen, onClose, onArtifactSelect }: HistoryPanelProps) {
  const { historyItems, loading, groupedHistory } = useHistory();
  const [selectedFilter, setSelectedFilter] = useState<string>('all');
  const grouped = groupedHistory();

  // Filter items
  const filteredGroups = () => {
    if (selectedFilter === 'all') {
      return grouped;
    }

    const filtered: Record<string, ArtifactItem[]> = {};
    Object.keys(grouped).forEach(key => {
      const items = grouped[key].filter(item => item.artifact_type === selectedFilter);
      if (items.length > 0) {
        filtered[key] = items;
      }
    });
    return filtered;
  };

  const filters = [
    { id: 'all', label: '全部', icon: 'apps' },
    { id: 'quiz_set', label: '题目', icon: 'quiz' },
    { id: 'flashcard_set', label: '闪卡', icon: 'style' },
    { id: 'notes', label: '笔记', icon: 'description' },
    { id: 'explanation', label: '讲解', icon: 'lightbulb' },
    { id: 'mindmap', label: '导图', icon: 'account_tree' },
  ];

  const handleItemClick = (item: ArtifactItem) => {
    if (onArtifactSelect) {
      onArtifactSelect(item);
    }
  };

  return (
    <>
      {/* Overlay */}
      <div
        className={`fixed inset-0 bg-black/50 z-[999] transition-opacity duration-300 ${
          isOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className={`fixed top-0 right-0 w-full sm:w-[400px] h-screen bg-gradient-to-br from-indigo-600 to-purple-700 z-[1000] transform transition-transform duration-300 flex flex-col shadow-2xl ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="flex-shrink-0 p-6 border-b border-white/20">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-bold text-white flex items-center gap-2">
              <span className="material-symbols-outlined text-3xl">history</span>
              学习历史
            </h2>
            <button
              onClick={onClose}
              className="w-10 h-10 rounded-lg bg-white/20 hover:bg-white/30 flex items-center justify-center text-white transition-colors"
            >
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>

          {/* Filter Tabs */}
          <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
            {filters.map(filter => (
              <button
                key={filter.id}
                onClick={() => setSelectedFilter(filter.id)}
                className={`flex-shrink-0 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                  selectedFilter === filter.id
                    ? 'bg-white text-indigo-600 shadow-lg'
                    : 'bg-white/20 text-white hover:bg-white/30'
                }`}
              >
                <span className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg">{filter.icon}</span>
                  {filter.label}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-4 border-white border-t-transparent"></div>
            </div>
          ) : Object.keys(filteredGroups()).length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-white/70">
              <span className="material-symbols-outlined text-6xl mb-4">inbox</span>
              <p className="text-lg">暂无学习记录</p>
              <p className="text-sm mt-2">开始学习后会自动保存</p>
            </div>
          ) : (
            Object.entries(filteredGroups()).map(([dateGroup, items]) => (
              <div key={dateGroup}>
                <h3 className="text-sm font-bold text-white/90 mb-3 flex items-center gap-2">
                  <span className="material-symbols-outlined text-lg">calendar_today</span>
                  {dateGroup}
                </h3>
                <div className="space-y-2">
                  {items.map(item => (
                    <button
                      key={item.artifact_id}
                      onClick={() => handleItemClick(item)}
                      className="w-full bg-white/10 hover:bg-white/20 backdrop-blur-sm rounded-lg p-4 transition-all text-left border border-white/10 hover:border-white/30 group"
                    >
                      <div className="flex items-start gap-3">
                        <span className="text-3xl flex-shrink-0 group-hover:scale-110 transition-transform">
                          {getArtifactIcon(item.artifact_type)}
                        </span>
                        <div className="flex-1 min-w-0">
                          <h4 className="font-bold text-white truncate mb-1">
                            {item.title}
                          </h4>
                          <div className="flex items-center gap-3 text-xs text-white/70">
                            <span>{formatTime(item.timestamp)}</span>
                            {getArtifactCount(item) && (
                              <span className="px-2 py-0.5 bg-white/20 rounded">
                                {getArtifactCount(item)}
                              </span>
                            )}
                          </div>
                        </div>
                        <span className="material-symbols-outlined text-white/50 group-hover:text-white transition-colors">
                          arrow_forward
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer Stats */}
        <div className="flex-shrink-0 p-4 border-t border-white/20 bg-black/20">
          <div className="grid grid-cols-3 gap-3">
            <div className="text-center">
              <div className="text-2xl font-bold text-white">{historyItems.length}</div>
              <div className="text-xs text-white/70">总计</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-white">
                {historyItems.filter(i => i.artifact_type === 'quiz_set').length}
              </div>
              <div className="text-xs text-white/70">题目</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-white">
                {historyItems.filter(i => i.artifact_type === 'flashcard_set').length}
              </div>
              <div className="text-xs text-white/70">闪卡</div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

