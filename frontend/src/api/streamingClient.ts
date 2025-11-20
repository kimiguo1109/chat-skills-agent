/**
 * Streaming API Client
 */

import { API_CONFIG } from './config';
import type { StreamChunkData } from '../types/streaming';

export class StreamingClient {
  private baseUrl: string;
  private userId: string;
  private sessionId: string;

  constructor(baseUrl?: string, userId?: string, sessionId?: string) {
    this.baseUrl = baseUrl || API_CONFIG.BASE_URL;
    this.userId = userId || API_CONFIG.USER_ID;
    this.sessionId = sessionId || API_CONFIG.SESSION_ID;
  }

  /**
   * Send a streaming chat message
   */
  async *streamChat(message: string): AsyncGenerator<StreamChunkData> {
    const response = await fetch(`${this.baseUrl}${API_CONFIG.ENDPOINTS.CHAT_STREAM}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: this.userId,
        session_id: this.sessionId,
        message: message,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();

      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split by double newline (SSE format)
      const events = buffer.split('\n\n');
      buffer = events.pop() || ''; // Keep last incomplete event in buffer

      for (const event of events) {
        if (event.startsWith('data: ')) {
          try {
            const data = JSON.parse(event.substring(6));
            yield data as StreamChunkData;
          } catch (e) {
            console.error('Failed to parse SSE data:', e);
          }
        }
      }
    }
  }

  /**
   * Send a traditional (non-streaming) chat message
   */
  async sendChat(message: string): Promise<any> {
    const response = await fetch(`${this.baseUrl}${API_CONFIG.ENDPOINTS.CHAT}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: this.userId,
        session_id: this.sessionId,
        message: message,
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return await response.json();
  }

  /**
   * Get chat history
   */
  async getHistory(limit: number = 50): Promise<any> {
    const response = await fetch(
      `${this.baseUrl}${API_CONFIG.ENDPOINTS.HISTORY}?user_id=${this.userId}&session_id=${this.sessionId}&limit=${limit}`
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return await response.json();
  }

  /**
   * Get artifact by ID
   */
  async getArtifact(artifactId: string): Promise<any> {
    const response = await fetch(
      `${this.baseUrl}${API_CONFIG.ENDPOINTS.HISTORY_ARTIFACT}/${artifactId}?user_id=${this.userId}`
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    return await response.json();
  }
}

// Singleton instance
export const streamingClient = new StreamingClient();

