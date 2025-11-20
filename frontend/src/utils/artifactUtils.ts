/**
 * Artifact Utilities
 */

export type ArtifactType = 
  | 'quiz_set' 
  | 'flashcard_set' 
  | 'notes' 
  | 'explanation' 
  | 'mindmap' 
  | 'learning_bundle'
  | 'learning_plan';

export interface ArtifactItem {
  artifact_id: string;
  artifact_type: ArtifactType;
  title: string;
  content: any;
  timestamp: number;
  session_id?: string;
  message_id?: string;
}

/**
 * Get icon for artifact type
 */
export function getArtifactIcon(type: ArtifactType): string {
  const icons: Record<ArtifactType, string> = {
    'quiz_set': '❓',
    'flashcard_set': '🎴',
    'notes': '📝',
    'explanation': '💡',
    'mindmap': '🗺️',
    'learning_bundle': '📦',
    'learning_plan': '📋'
  };
  return icons[type] || '📄';
}

/**
 * Get artifact count text
 */
export function getArtifactCount(item: ArtifactItem): string | null {
  if (item.artifact_type === 'quiz_set' && item.content.questions) {
    return `${item.content.questions.length} 题`;
  } else if (item.artifact_type === 'flashcard_set' && item.content.cards) {
    return `${item.content.cards.length} 卡`;
  }
  return null;
}

/**
 * Format timestamp to time string
 */
export function formatTime(timestamp: number): string {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

/**
 * Format timestamp to datetime string
 */
export function formatDateTime(timestamp: number): string {
  const date = new Date(timestamp);
  return date.toLocaleString('zh-CN');
}

/**
 * Escape HTML
 */
export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Detect content type from text
 */
export function detectContentType(content: string): string {
  if (content.includes('```mindmap') || content.includes('# Root')) {
    return 'mindmap';
  } else if (content.includes('```') || content.includes('def ') || content.includes('function ')) {
    return 'code';
  }
  return 'text';
}

/**
 * Group history items by date
 */
export function groupHistoryByDate(items: ArtifactItem[]): Record<string, ArtifactItem[]> {
  const groups: Record<string, ArtifactItem[]> = {
    '今天': [],
    '昨天': [],
    '本周': [],
    '更早': []
  };

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const thisWeek = new Date(today);
  thisWeek.setDate(thisWeek.getDate() - 7);

  items.forEach(item => {
    const itemDate = new Date(item.timestamp);
    if (itemDate >= today) {
      groups['今天'].push(item);
    } else if (itemDate >= yesterday) {
      groups['昨天'].push(item);
    } else if (itemDate >= thisWeek) {
      groups['本周'].push(item);
    } else {
      groups['更早'].push(item);
    }
  });

  // Remove empty groups
  Object.keys(groups).forEach(key => {
    if (groups[key].length === 0) {
      delete groups[key];
    }
  });

  return groups;
}

