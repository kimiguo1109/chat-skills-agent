/**
 * useMath - Handle KaTeX math rendering
 */

import { useEffect, useRef } from 'react';
import { renderMathInContent, initMathObserver } from '../utils/mathRenderer';

/**
 * Hook to render math in a container element
 */
export function useMath(dependencies: any[] = []) {
  const containerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (containerRef.current) {
      const timer = setTimeout(() => {
        renderMathInContent(containerRef.current);
      }, 50);
      return () => clearTimeout(timer);
    }
  }, dependencies); // eslint-disable-line react-hooks/exhaustive-deps

  return containerRef;
}

/**
 * Hook to set up automatic math rendering for dynamically added content
 */
export function useMathObserver(targetElement: HTMLElement | null) {
  useEffect(() => {
    if (!targetElement) return;

    const observer = initMathObserver(targetElement);

    return () => {
      observer?.disconnect();
    };
  }, [targetElement]);
}

