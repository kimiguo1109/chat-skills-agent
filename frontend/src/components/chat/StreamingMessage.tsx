/**
 * Streaming Message Component - 流式响应消息组件
 * 支持 thinking 过程、plan steps等
 */

import { useEffect, useState } from 'react';
import { renderMathInContent } from '../../utils/mathRenderer';
import { ArtifactRenderer } from '../artifacts/ArtifactRenderer';
import type { StreamingState } from '../../types/streaming';

interface StreamingMessageProps {
  state: StreamingState;
}

export function StreamingMessage({ state }: StreamingMessageProps) {
  const [showFullThinking, setShowFullThinking] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      const elements = document.querySelectorAll('.streaming-math-content');
      elements.forEach(el => renderMathInContent(el as HTMLElement));
    }, 50);
    return () => clearTimeout(timer);
  }, [state]);

  return (
    <div className="flex items-start gap-3 w-full">
      {/* Avatar */}
      <div 
        className="bg-center bg-no-repeat aspect-square bg-cover rounded-full size-10 shrink-0" 
        style={{ backgroundImage: 'url("https://lh3.googleusercontent.com/aida-public/AB6AXuCxe92kEf7gMHjbEHfZQu3F-p4XUO0nyA37zYAuOz7CiVXM_3hgmQ9gTI6zw7siePySKKolumdfXax7FjZ1tuLAnsb5rDYnZjw4LaKpR0MpYWUilv2DSX2VlCD416jAvXmMW3d3TA0MfMgLOkvyyvAqiNcFnqdLIk1LOdKh1Axylm3hUbhf-JtzopMhBhZ5WxEDvTgpGF0E65VLCr805vqY4iosbw4L8Qmm-sViAPSF8dXyszl2XldUnwHCnAakeX7o04PO1S6iwT_m")' }} 
      />

      {/* Content */}
      <div className="flex flex-1 flex-col gap-1 items-start w-full">
        <p className="text-text-light-secondary dark:text-text-dark-secondary text-sm font-medium">
          StudyX Agent
        </p>

        <div className="w-full space-y-4">
          {/* Status */}
          {state.status && (
            <div className="flex items-center gap-2 text-sm text-primary">
              <div className="animate-spin rounded-full h-4 w-4 border-2 border-primary border-t-transparent"></div>
              <span>{state.status}</span>
            </div>
          )}

          {/* Plan Preview */}
          {state.planPreview && (
            <div className="rounded-lg border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark p-4">
              <h4 className="font-bold text-text-light-primary dark:text-text-dark-primary mb-2">
                📋 {state.planPreview.topic}
              </h4>
              <p className="text-sm text-text-light-secondary dark:text-text-dark-secondary mb-3">
                共 {state.planPreview.totalSteps} 个步骤
              </p>
              <div className="space-y-2">
                {state.planPreview.steps.map(step => (
                  <div 
                    key={step.step_order}
                    className="flex items-start gap-2 text-sm"
                  >
                    <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary flex items-center justify-center text-xs font-bold">
                      {step.step_order}
                    </span>
                    <div>
                      <p className="font-medium text-text-light-primary dark:text-text-dark-primary">
                        {step.step_name}
                      </p>
                      <p className="text-xs text-text-light-secondary dark:text-text-dark-secondary">
                        {step.description}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Steps Progress */}
          {state.steps.size > 0 && (
            <div className="space-y-3">
              {Array.from(state.steps.values()).map(step => (
                <div 
                  key={step.order}
                  className="rounded-lg border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark p-4"
                >
                  <div className="flex items-center gap-3 mb-2">
                    <span className={`material-symbols-outlined text-xl ${
                      step.status === 'complete' ? 'text-green-500' :
                      step.status === 'running' ? 'text-primary animate-pulse' :
                      'text-slate-400'
                    }`}>
                      {step.status === 'complete' ? 'check_circle' :
                       step.status === 'running' ? 'pending' :
                       'radio_button_unchecked'}
                    </span>
                    <h5 className="font-bold text-text-light-primary dark:text-text-dark-primary">
                      {step.name}
                    </h5>
                  </div>

                  {step.thinking && step.status === 'running' && (
                    <div className="mt-2 p-3 bg-blue-50 dark:bg-blue-900/20 rounded text-sm text-text-light-primary dark:text-text-dark-primary streaming-math-content">
                      <p className="text-xs text-blue-600 dark:text-blue-400 mb-1">💭 思考中...</p>
                      <p className="whitespace-pre-wrap">{step.thinking}</p>
                    </div>
                  )}

                  {step.output && step.status === 'complete' && (
                    <div className="mt-3">
                      <ArtifactRenderer type={step.outputType as any} content={step.output} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Thinking Process */}
          {state.thinking && !state.planPreview && (
            <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg border border-yellow-200 dark:border-yellow-800">
              <button
                onClick={() => setShowFullThinking(!showFullThinking)}
                className="flex items-center gap-2 text-sm font-medium text-yellow-800 dark:text-yellow-200 mb-2"
              >
                <span className="material-symbols-outlined text-lg">psychology</span>
                <span>AI 思考过程</span>
                <span className="material-symbols-outlined text-sm">
                  {showFullThinking ? 'expand_less' : 'expand_more'}
                </span>
              </button>
              {showFullThinking && (
                <div className="text-sm text-yellow-700 dark:text-yellow-300 whitespace-pre-wrap streaming-math-content">
                  {state.thinking}
                </div>
              )}
            </div>
          )}

          {/* Content */}
          {state.content && (
            <div className="rounded-xl rounded-bl-none px-4 py-3 bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark text-text-light-primary dark:text-text-dark-primary whitespace-pre-wrap streaming-math-content">
              {state.content}
            </div>
          )}

          {/* Final Result */}
          {state.final && (
            <div className="w-full">
              <ArtifactRenderer 
                type={state.final.artifactType as any} 
                content={state.final.content} 
              />
            </div>
          )}

          {/* Error */}
          {state.error && (
            <div className="p-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300">
              <div className="flex items-center gap-2 mb-2">
                <span className="material-symbols-outlined">error</span>
                <span className="font-medium">发生错误</span>
              </div>
              <p className="text-sm">{state.error}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

