/**
 * Artifact Renderer - 统一渲染各种类型的artifact
 */

import { QuizCard, QuizContent } from './QuizCard';
import { FlashcardCard, FlashcardContent } from './FlashcardCard';
import { MindMapCard, MindMapContent } from './MindMapCard';
import { NotesCard, NotesContent } from './NotesCard';
import { ExplainCard, ExplanationContent } from './ExplainCard';
import type { ArtifactType } from '../../utils/artifactUtils';

export interface ArtifactProps {
  type: ArtifactType;
  content: any;
}

export function ArtifactRenderer({ type, content }: ArtifactProps) {
  switch (type) {
    case 'quiz_set':
      return <QuizCard content={content as QuizContent} />;
    
    case 'flashcard_set':
      return <FlashcardCard content={content as FlashcardContent} />;
    
    case 'mindmap':
      return <MindMapCard content={content as MindMapContent} />;
    
    case 'notes':
      return <NotesCard content={content as NotesContent} />;
    
    case 'explanation':
      return <ExplainCard content={content as ExplanationContent} />;
    
    case 'learning_bundle':
      // Learning bundle contains multiple components
      return (
        <div className="space-y-6">
          {content.components && content.components.map((comp: any, index: number) => (
            <div key={index}>
              {comp.component_type === 'mindmap' && comp.content.root && (
                <MindMapCard content={comp.content} />
              )}
              {comp.component_type === 'quiz' && comp.content.questions && (
                <QuizCard content={comp.content} />
              )}
              {comp.component_type === 'flashcard' && comp.content.cards && (
                <FlashcardCard content={comp.content} />
              )}
            </div>
          ))}
        </div>
      );
    
    default:
      return (
        <div className="p-4 rounded-lg bg-slate-100 dark:bg-slate-800">
          <pre className="text-xs overflow-auto whitespace-pre-wrap">
            {JSON.stringify(content, null, 2)}
          </pre>
        </div>
      );
  }
}

// Export all artifact components
export { QuizCard, FlashcardCard, MindMapCard, NotesCard, ExplainCard };
export type { QuizContent, FlashcardContent, MindMapContent, NotesContent, ExplanationContent };

