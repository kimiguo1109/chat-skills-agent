/**
 * ExplainCard - 概念讲解卡片（严格按照原始设计）
 */

export interface ExplainSection {
  title: string
  content: string
  examples?: Array<{
    example_text: string
    explanation: string
  }>
  formula_or_diagram_description?: string | null
}

export interface RelatedConcept {
  concept_name: string
  brief_explanation: string
}

export interface ExplanationContent {
  concept: string
  subject: string
  summary: string
  sections: ExplainSection[]
  related_concepts?: RelatedConcept[]
  difficulty_level?: string
}

interface ExplainCardProps {
  content: ExplanationContent
}

export function ExplainCard({ content }: ExplainCardProps) {
  return (
    <div className="w-full max-w-4xl rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm">
      {/* Title Header */}
      <div className="p-6 sm:p-8">
        <h1 className="text-2xl sm:text-3xl font-bold text-text-light-primary dark:text-text-dark-primary tracking-tight">
          {content.concept}
        </h1>
        {content.summary && (
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-2">
            {content.summary}
          </p>
        )}
      </div>

      {/* Content Area */}
      <div className="px-6 sm:px-8 pb-6 text-base text-text-light-primary dark:text-text-dark-primary space-y-4">
        {content.sections.map((section, sectionIdx) => (
          <div key={sectionIdx} className="space-y-4">
            <p dangerouslySetInnerHTML={{ __html: section.content.replace(/<code>/g, '<code class="bg-primary/10 text-primary p-1 rounded-md text-sm">') }} />
            
            {/* Formula */}
            {section.formula_or_diagram_description && (
              <div className="my-4 p-4 bg-background-light dark:bg-background-dark rounded-lg text-center font-mono text-lg">
                <span className="font-bold">{section.formula_or_diagram_description}</span>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Divider Line */}
      <hr className="border-border-light dark:border-border-dark" />

      {/* Examples Section */}
      {content.sections.some(s => s.examples && s.examples.length > 0) && (
        <div className="p-6 sm:p-8">
          <h2 className="text-xl sm:text-2xl font-semibold text-text-light-primary dark:text-text-dark-primary mb-5">
            Examples
          </h2>
          <div className="space-y-6">
            {content.sections.map((section, sectionIdx) =>
              section.examples?.map((example, exampleIdx) => (
                <div key={`${sectionIdx}-${exampleIdx}`} className="flex flex-col gap-3">
                  <h3 className="font-semibold text-text-light-primary dark:text-text-dark-primary">
                    <span className="bg-primary text-white rounded-full h-6 w-6 inline-flex items-center justify-center text-sm mr-2">
                      {exampleIdx + 1}
                    </span>
                    <span dangerouslySetInnerHTML={{ __html: example.example_text.replace(/<code>/g, '<code class="bg-primary/10 text-primary p-1 rounded-md text-sm">') }} />
                  </h3>
                  <ul className="list-none space-y-2 pl-8 text-text-light-secondary dark:text-text-dark-secondary border-l-2 border-primary/50 ml-3">
                    {example.explanation.split('\n').map((step, stepIdx) => (
                      step.trim() && (
                        <li key={stepIdx} dangerouslySetInnerHTML={{ __html: step.replace(/<code>/g, '<code class="bg-primary/10 text-primary p-1 rounded-md text-sm">') }} />
                      )
                    ))}
                  </ul>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
