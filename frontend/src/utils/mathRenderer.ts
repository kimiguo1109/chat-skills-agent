/**
 * LaTeX Math Rendering Utilities using KaTeX
 */

// KaTeX type declarations
declare global {
  interface Window {
    renderMathInElement?: (element: HTMLElement, options: any) => void;
    katex?: any;
  }
}

/**
 * Render math expressions in an HTML element
 */
export function renderMathInContent(element: HTMLElement | null): void {
  if (!element || typeof window.renderMathInElement === 'undefined') {
    return;
  }

  try {
    window.renderMathInElement(element, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\[', right: '\\]', display: true },
        { left: '\\(', right: '\\)', display: false }
      ],
      throwOnError: false
    });
  } catch (e) {
    console.warn('LaTeX rendering error:', e);
  }
}

/**
 * Initialize KaTeX auto-rendering observer
 */
export function initMathObserver(targetElement: HTMLElement): MutationObserver | null {
  if (typeof window.renderMathInElement === 'undefined') {
    return null;
  }

  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType === 1) { // Element node
          const element = node as HTMLElement;
          
          // Render thinking content
          if (element.classList && element.classList.contains('thinking-content')) {
            renderMathInContent(element);
          }
          
          // Render all new content
          const mathElements = element.querySelectorAll && 
            element.querySelectorAll('.thinking-content, .prose, .math-content');
          
          if (mathElements) {
            mathElements.forEach(el => renderMathInContent(el as HTMLElement));
          }
        }
      });
    });
  });

  observer.observe(targetElement, {
    childList: true,
    subtree: true
  });

  return observer;
}

