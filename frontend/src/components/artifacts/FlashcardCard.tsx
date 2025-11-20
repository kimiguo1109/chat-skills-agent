/**
 * Flashcard Card Component - 闪卡集合组件
 */

import { useState, useEffect } from 'react';
import { renderMathInContent } from '../../utils/mathRenderer';

export interface Flashcard {
  term: string;
  definition: string;
  example?: string;
}

export interface FlashcardContent {
  cards: Flashcard[];
  topic?: string;
  subject?: string;
}

interface FlashcardCardProps {
  content: FlashcardContent;
}

export function FlashcardCard({ content }: FlashcardCardProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);
  const [masteredCards, setMasteredCards] = useState<Set<number>>(new Set());

  const currentCard = content.cards[currentIndex];
  const totalCards = content.cards.length;
  const isMastered = masteredCards.has(currentIndex);

  // Render math when card changes
  useEffect(() => {
    const timer = setTimeout(() => {
      const elements = document.querySelectorAll('.flashcard-math-content');
      elements.forEach(el => renderMathInContent(el as HTMLElement));
    }, 50);
    return () => clearTimeout(timer);
  }, [currentIndex, isFlipped]);

  const handleFlip = () => {
    setIsFlipped(!isFlipped);
  };

  const handleNext = () => {
    if (currentIndex < totalCards - 1) {
      setCurrentIndex(prev => prev + 1);
      setIsFlipped(false);
    }
  };

  const handlePrevious = () => {
    if (currentIndex > 0) {
      setCurrentIndex(prev => prev - 1);
      setIsFlipped(false);
    }
  };

  const handleMastered = () => {
    setMasteredCards(prev => {
      const newSet = new Set(prev);
      if (newSet.has(currentIndex)) {
        newSet.delete(currentIndex);
      } else {
        newSet.add(currentIndex);
      }
      return newSet;
    });
  };

  const progress = ((masteredCards.size / totalCards) * 100).toFixed(0);

  return (
    <div className="w-full rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-border-light dark:border-border-dark bg-gradient-to-r from-purple-50 to-pink-50 dark:from-purple-900/20 dark:to-pink-900/20">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="material-symbols-outlined text-primary text-2xl">style</span>
            <div>
              <h3 className="text-lg font-bold text-text-light-primary dark:text-text-dark-primary">
                {content.subject || '闪卡'} - {content.topic || '记忆卡片'}
              </h3>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                {totalCards} 张卡片 · 已掌握 {masteredCards.size} 张
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
          className="h-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Card Container */}
      <div className="p-8 min-h-[400px] flex items-center justify-center">
        <div 
          className="relative w-full max-w-2xl h-80 perspective-1000"
          onClick={handleFlip}
        >
          <div 
            className={`absolute inset-0 transition-transform duration-500 transform-style-3d cursor-pointer ${
              isFlipped ? 'rotate-y-180' : ''
            }`}
            style={{ 
              transformStyle: 'preserve-3d',
              transform: isFlipped ? 'rotateY(180deg)' : 'rotateY(0deg)'
            }}
          >
            {/* Front Side */}
            <div 
              className="absolute inset-0 rounded-2xl shadow-2xl p-8 flex flex-col items-center justify-center backface-hidden bg-gradient-to-br from-blue-500 to-indigo-600 text-white"
              style={{ backfaceVisibility: 'hidden' }}
            >
              <span className="material-symbols-outlined text-6xl mb-6 opacity-50">book</span>
              <p className="text-2xl font-bold text-center flashcard-math-content">
                {currentCard.term}
              </p>
              <p className="text-sm mt-6 opacity-75">点击翻转卡片</p>
            </div>

            {/* Back Side */}
            <div 
              className="absolute inset-0 rounded-2xl shadow-2xl p-8 flex flex-col justify-center backface-hidden bg-gradient-to-br from-purple-500 to-pink-600 text-white"
              style={{ 
                backfaceVisibility: 'hidden',
                transform: 'rotateY(180deg)'
              }}
            >
              <div className="space-y-4">
                <div>
                  <p className="text-sm font-medium opacity-75 mb-2">定义：</p>
                  <p className="text-lg leading-relaxed flashcard-math-content">
                    {currentCard.definition}
                  </p>
                </div>
                {currentCard.example && (
                  <div className="pt-4 border-t border-white/20">
                    <p className="text-sm font-medium opacity-75 mb-2">示例：</p>
                    <p className="text-base leading-relaxed flashcard-math-content">
                      {currentCard.example}
                    </p>
                  </div>
                )}
              </div>
              <p className="text-sm mt-6 opacity-75 text-center">点击再次翻转</p>
            </div>
          </div>
        </div>
      </div>

      {/* Card Indicator */}
      <div className="px-8 pb-4">
        <div className="flex items-center justify-center gap-2">
          {content.cards.map((_, index) => (
            <button
              key={index}
              onClick={(e) => {
                e.stopPropagation();
                setCurrentIndex(index);
                setIsFlipped(false);
              }}
              className={`h-2 rounded-full transition-all ${
                index === currentIndex
                  ? 'w-8 bg-primary'
                  : masteredCards.has(index)
                  ? 'w-2 bg-green-500'
                  : 'w-2 bg-slate-300 dark:bg-slate-600'
              }`}
            />
          ))}
        </div>
      </div>

      {/* Controls */}
      <div className="p-4 border-t border-border-light dark:border-border-dark">
        <div className="flex items-center justify-between mb-4">
          <button
            onClick={handlePrevious}
            disabled={currentIndex === 0}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-text-light-primary dark:text-text-dark-primary hover:bg-primary/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <span className="material-symbols-outlined">arrow_back</span>
            上一张
          </button>

          <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
            {currentIndex + 1} / {totalCards}
          </span>

          <button
            onClick={handleNext}
            disabled={currentIndex === totalCards - 1}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            下一张
            <span className="material-symbols-outlined">arrow_forward</span>
          </button>
        </div>

        <button
          onClick={handleMastered}
          className={`w-full py-3 rounded-lg text-sm font-bold transition-colors ${
            isMastered
              ? 'bg-green-500 text-white hover:bg-green-600'
              : 'bg-slate-100 dark:bg-slate-700 text-text-light-primary dark:text-text-dark-primary hover:bg-slate-200 dark:hover:bg-slate-600'
          }`}
        >
          {isMastered ? (
            <span className="flex items-center justify-center gap-2">
              <span className="material-symbols-outlined">check_circle</span>
              已掌握
            </span>
          ) : (
            <span>标记为已掌握</span>
          )}
        </button>
      </div>
    </div>
  );
}

