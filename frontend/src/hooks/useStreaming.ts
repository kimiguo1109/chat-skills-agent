/**
 * useStreaming - Handle streaming chat responses
 */

import { useState, useCallback } from 'react';
import { streamingClient } from '../api/streamingClient';
import type { StreamChunkData, StreamingState } from '../types/streaming';

export function useStreaming() {
  const [streamingStates, setStreamingStates] = useState<Map<string, StreamingState>>(new Map());

  const sendStreamingMessage = useCallback(async (
    message: string,
    onChunk?: (responseId: string, chunk: StreamChunkData) => void,
    onComplete?: (responseId: string, final: any) => void,
    onError?: (responseId: string, error: string) => void
  ): Promise<string> => {
    const responseId = `response-${Date.now()}`;
    
    // Initialize streaming state
    const initialState: StreamingState = {
      responseId,
      status: 'Starting...',
      thinking: '',
      content: '',
      final: null,
      steps: new Map(),
    };
    
    setStreamingStates(prev => new Map(prev).set(responseId, initialState));

    try {
      // Stream chat
      for await (const chunk of streamingClient.streamChat(message)) {
        // Update state
        setStreamingStates(prev => {
          const newMap = new Map(prev);
          const state = newMap.get(responseId) || initialState;
          
          // Update based on event type
          switch (chunk.event_type) {
            case 'status':
              state.status = chunk.message || 'Processing...';
              break;
            
            case 'plan_preview':
              if (chunk.steps_preview) {
                state.planPreview = {
                  topic: chunk.topic || '',
                  steps: chunk.steps_preview,
                  totalSteps: chunk.total_steps || 0,
                };
              }
              break;
            
            case 'step_start':
              if (chunk.step_order !== undefined) {
                state.currentStep = chunk.step_order;
                state.steps.set(chunk.step_order, {
                  order: chunk.step_order,
                  name: chunk.step_name || '',
                  status: 'running',
                  thinking: '',
                  startTime: Date.now(),
                });
              }
              break;
            
            case 'step_thinking':
              if (chunk.step_order !== undefined) {
                const step = state.steps.get(chunk.step_order);
                if (step) {
                  step.thinking += chunk.thinking || '';
                  state.steps.set(chunk.step_order, step);
                }
              }
              break;
            
            case 'step_complete':
              if (chunk.step_order !== undefined) {
                const step = state.steps.get(chunk.step_order);
                if (step) {
                  step.status = 'complete';
                  step.output = chunk.result;
                  step.outputType = chunk.content_type;
                  state.steps.set(chunk.step_order, step);
                }
              }
              break;
            
            case 'thinking':
              state.thinking += chunk.thinking || '';
              break;
            
            case 'content':
              state.content += chunk.content || '';
              break;
            
            case 'final':
              state.final = {
                contentType: chunk.content_type,
                content: chunk.content,
                artifactType: chunk.artifact_type,
                artifactId: chunk.artifact_id,
              };
              break;
            
            case 'error':
              state.error = chunk.error || 'Unknown error';
              break;
          }
          
          newMap.set(responseId, state);
          return newMap;
        });

        // Call chunk callback
        if (onChunk) {
          onChunk(responseId, chunk);
        }
      }

      // Stream complete
      const finalState = streamingStates.get(responseId);
      if (onComplete && finalState?.final) {
        onComplete(responseId, finalState.final);
      }

      return responseId;
    } catch (error) {
      console.error('Streaming error:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      
      setStreamingStates(prev => {
        const newMap = new Map(prev);
        const state = newMap.get(responseId) || initialState;
        state.error = errorMessage;
        newMap.set(responseId, state);
        return newMap;
      });

      if (onError) {
        onError(responseId, errorMessage);
      }

      throw error;
    }
  }, [streamingStates]);

  const getStreamingState = useCallback((responseId: string): StreamingState | undefined => {
    return streamingStates.get(responseId);
  }, [streamingStates]);

  const clearStreamingState = useCallback((responseId: string) => {
    setStreamingStates(prev => {
      const newMap = new Map(prev);
      newMap.delete(responseId);
      return newMap;
    });
  }, []);

  return {
    streamingStates,
    sendStreamingMessage,
    getStreamingState,
    clearStreamingState,
  };
}

