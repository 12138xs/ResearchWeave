import katex from 'katex';
import 'katex/dist/katex.min.css';

export function MathFormula({ tex, display = false }: { tex: string; display?: boolean }) {
  const cleaned = normalizeTexForKatex(tex);
  try {
    const html = katex.renderToString(cleaned, {
      displayMode: display,
      throwOnError: false,
      strict: 'ignore',
      trust: false,
    });
    const Tag = display ? 'div' : 'span';
    return <Tag className={display ? 'math-block math-rendered' : 'math-inline math-rendered'} dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    const Tag = display ? 'div' : 'span';
    return <Tag className={display ? 'math-block math-fallback' : 'math-inline math-fallback'}>{cleaned}</Tag>;
  }
}

function normalizeTexForKatex(value: string) {
  return value
    .replace(/\\text\{([^{}]*)\}/g, '\\mathrm{$1}')
    .replace(/\s+/g, ' ')
    .trim();
}


