/**
 * API Configuration
 */

export const API_CONFIG = {
  BASE_URL: 'http://localhost:8000',
  USER_ID: 'demo-user',
  SESSION_ID: 'demo-session',
  USE_STREAMING: true,
  ENDPOINTS: {
    CHAT: '/api/agent/chat',
    CHAT_STREAM: '/api/agent/chat-stream',
    HISTORY: '/api/agent/history',
    HISTORY_ARTIFACT: '/api/agent/history/artifact',
  }
} as const;

export type ApiConfig = typeof API_CONFIG;

