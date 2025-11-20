/**
 * Quiz Card Component - 测验题目卡片
 */

import { useState, useEffect } from 'react';
import { renderMathInContent } from '../../utils/mathRenderer';

export interface QuizQuestion {
  question: string;
  options: string[];
  correct_answer: number;
  explanation?: string;
  difficulty?: string;
}

export interface QuizContent {
  questions: QuizQuestion[];
  topic?: string;
  subject?: string;
}

interface QuizCardProps {
  content: QuizContent;
}

export function QuizCard({ content }: QuizCardProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAnswer, setSelectedAnswer] = useState<number | null>(null);
  const [showExplanation, setShowExplanation] = useState(false);
  const [answeredQuestions, setAnsweredQuestions] = useState<Set<number>>(new Set());
  const [correctCount, setCorrectCount] = useState(0);

  const currentQuestion = content.questions[currentIndex];
  const totalQuestions = content.questions.length;
  const isAnswered = answeredQuestions.has(currentIndex);

  // Render math when content changes
  useEffect(() => {
    const timer = setTimeout(() => {
      const elements = document.querySelectorAll('.quiz-math-content');
      elements.forEach(el => renderMathInContent(el as HTMLElement));
    }, 50);
    return () => clearTimeout(timer);
  }, [currentIndex]);

  const handleAnswerSelect = (optionIndex: number) => {
    if (isAnswered) return;

    setSelectedAnswer(optionIndex);
    setShowExplanation(true);
    setAnsweredQuestions(prev => new Set(prev).add(currentIndex));

    if (optionIndex === currentQuestion.correct_answer) {
      setCorrectCount(prev => prev + 1);
    }
  };

  const handleNext = () => {
    if (currentIndex < totalQuestions - 1) {
      setCurrentIndex(prev => prev + 1);
      setSelectedAnswer(null);
      setShowExplanation(false);
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex(prev => prev - 1);
      setSelectedAnswer(null);
      setShowExplanation(false);
    }
  };

  const getOptionStyle = (optionIndex: number) => {
    if (!showExplanation) {
      return 'hover:border-primary hover:bg-primary/5';
    }

    if (optionIndex === currentQuestion.correct_answer) {
      return 'border-green-500 bg-green-50 dark:bg-green-900/20';
    }

    if (optionIndex === selectedAnswer && optionIndex !== currentQuestion.correct_answer) {
      return 'border-red-500 bg-red-50 dark:bg-red-900/20';
    }

    return 'opacity-50';
  };

  const progress = ((correctCount / totalQuestions) * 100).toFixed(0);

  return (
    <div className="w-full rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-border-light dark:border-border-dark bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-2xl">quiz</span>
            <div>
              <h3 className="text-lg font-bold text-text-light-primary dark:text-text-dark-primary">
                {content.subject || '题目练习'} - {content.topic || '测验'}
              </h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {totalQuestions} 道题 · 已完成 {answeredQuestions.size} 题
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold text-primary">{progress}%</span>
          </div>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="h-2 bg-slate-200 dark:bg-slate-700">
        <div 
          className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Question */}
      <div className="p-6">
        <div className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-primary">
              题目 {currentIndex + 1} / {totalQuestions}
            </span>
            {currentQuestion.difficulty && (
              <span className={`px-2 py-1 rounded text-xs font-medium ${
                currentQuestion.difficulty === 'easy' ? 'bg-green-100 text-green-700' :
                currentQuestion.difficulty === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                'bg-red-100 text-red-700'
              }`}>
                {currentQuestion.difficulty === 'easy' ? '简单' :
                 currentQuestion.difficulty === 'medium' ? '中等' : '困难'}
              </span>
            )}
          </div>
          <p className="text-lg font-medium text-text-light-primary dark:text-text-dark-primary quiz-math-content">
            {currentQuestion.question}
          </p>
        </div>

        {/* Options */}
        <div className="space-y-3 mb-6">
          {currentQuestion.options.map((option, index) => (
            <button
              key={index}
              onClick={() => handleAnswerSelect(index)}
              disabled={isAnswered}
              className={`w-full text-left p-4 rounded-lg border-2 transition-all ${getOptionStyle(index)}`}
            >
              <div className="flex items-center gap-3">
                <span className="flex items-center justify-center w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-700 font-medium">
                  {String.fromCharCode(65 + index)}
                </span>
                <span className="flex-1 quiz-math-content">{option}</span>
                {showExplanation && index === currentQuestion.correct_answer && (
                  <span className="material-symbols-outlined text-green-500">check_circle</span>
                )}
                {showExplanation && index === selectedAnswer && index !== currentQuestion.correct_answer && (
                  <span className="material-symbols-outlined text-red-500">cancel</span>
                )}
              </div>
            </button>
          ))}
        </div>

        {/* Explanation */}
        {showExplanation && currentQuestion.explanation && (
          <div className="p-4 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
            <div className="flex items-start gap-2">
              <span className="material-symbols-outlined text-blue-500 text-xl">lightbulb</span>
              <div>
                <p className="font-medium text-blue-900 dark:text-blue-100 mb-1">解析：</p>
                <p className="text-sm text-blue-800 dark:text-blue-200 quiz-math-content">
                  {currentQuestion.explanation}
                </p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Navigation */}
      <div className="p-4 border-t border-border-light dark:border-border-dark flex items-center justify-between">
        <button
          onClick={handlePrevious}
          disabled={currentIndex === 0}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-text-light-primary dark:text-text-dark-primary hover:bg-primary/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <span className="material-symbols-outlined">arrow_back</span>
          上一题
        </button>

        <div className="flex gap-1">
          {content.questions.map((_, index) => (
            <button
              key={index}
              onClick={() => {
                setCurrentIndex(index);
                setSelectedAnswer(null);
                setShowExplanation(false);
              }}
              className={`w-8 h-8 rounded-full text-xs font-medium transition-colors ${
                index === currentIndex
                  ? 'bg-primary text-white'
                  : answeredQuestions.has(index)
                  ? 'bg-green-500 text-white'
                  : 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
              }`}
            >
              {index + 1}
            </button>
          ))}
        </div>

        <button
          onClick={handleNext}
          disabled={currentIndex === totalQuestions - 1}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          下一题
          <span className="material-symbols-outlined">arrow_forward</span>
        </button>
      </div>
    </div>
  );
}
