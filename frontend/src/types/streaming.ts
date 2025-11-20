/**
 * Streaming Response Types
 */

export interface StreamChunkData {
  event_type: 'status' | 'plan_preview' | 'step_start' | 'step_thinking' | 'step_complete' | 'thinking' | 'content' | 'final' | 'error';
  message?: string;
  topic?: string;
  steps_preview?: StepPreview[];
  total_steps?: number;
  step_order?: number;
  step_name?: string;
  thinking?: string;
  content?: string;
  content_type?: string;
  result?: any;
  artifact_type?: string;
  artifact_id?: string;
  error?: string;
}

export interface StepPreview {
  step_order: number;
  step_name: string;
  description: string;
}

export interface StreamingState {
  responseId: string;
  status: string;
  thinking: string;
  content: string;
  final: any;
  planPreview?: {
    topic: string;
    steps: StepPreview[];
    totalSteps: number;
  };
  currentStep?: number;
  steps: Map<number, StepState>;
  error?: string;
}

export interface StepState {
  order: number;
  name: string;
  status: 'pending' | 'running' | 'complete' | 'error';
  thinking: string;
  thinkingSummary?: string;
  output?: any;
  outputType?: string;
  startTime?: number;
  elapsed?: number;
}

