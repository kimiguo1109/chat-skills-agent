/**
 * useHistory - Handle learning history
 */

import { useState, useEffect, useCallback } from 'react';
import { streamingClient } from '../api/streamingClient';
import type { ArtifactItem } from '../utils/artifactUtils';
import { groupHistoryByDate } from '../utils/artifactUtils';

export function useHistory() {
  const [historyItems, setHistoryItems] = useState<ArtifactItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Load history from backend
   */
  const loadHistory = useCallback(async (limit: number = 50) => {
    setLoading(true);
    setError(null);

    try {
      const response = await streamingClient.getHistory(limit);
      
      if (response.history && Array.isArray(response.history)) {
        setHistoryItems(response.history);
      } else {
        setHistoryItems([]);
      }
    } catch (err) {
      console.error('Failed to load history:', err);
      setError(err instanceof Error ? err.message : 'Failed to load history');
      setHistoryItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Get artifact by ID
   */
  const getArtifact = useCallback(async (artifactId: string) => {
    try {
      const response = await streamingClient.getArtifact(artifactId);
      return response;
    } catch (err) {
      console.error('Failed to get artifact:', err);
      throw err;
    }
  }, []);

  /**
   * Add new artifact to history
   */
  const addToHistory = useCallback((item: ArtifactItem) => {
    setHistoryItems(prev => [item, ...prev]);
  }, []);

  /**
   * Get grouped history
   */
  const groupedHistory = useCallback(() => {
    return groupHistoryByDate(historyItems);
  }, [historyItems]);

  /**
   * Clear history
   */
  const clearHistory = useCallback(() => {
    setHistoryItems([]);
  }, []);

  // Load history on mount
  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  return {
    historyItems,
    loading,
    error,
    loadHistory,
    getArtifact,
    addToHistory,
    groupedHistory,
    clearHistory,
  };
}

