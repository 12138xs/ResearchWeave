import { type ReactNode } from 'react';
import { MathFormula } from './MathFormula';

const LIGHT_SECTION_HEADING_RE = new RegExp(
  String.raw`^\s*(研究背景|方法原理|主要结果|\u{942e}\u{65c2}\u{2512}\u{9473}\u{5c7e}\u{6ad9}|\u{93c2}\u{89c4}\u{7876}\u{9358}\u{71ba}\u{608a}|\u{6d93}\u{660f}\u{e6e6}\u{7f01}\u{64b4}\u{7049})\s*\n+`,
  'u',
);

function stripRedundantLightHeading(text: string) {
  return text.replace(LIGHT_SECTION_HEADING_RE, '').trim();
}

export function BasicRichTextBlock({ text, fallback }: { text: string; fallback: string }) {
  const normalized = stripRedundantLightHeading(text || fallback);
  const blocks = normalized
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);
  if (blocks.length === 0) return <p>{fallback}</p>;
  return (
    <div className="rich-text-block">
      {blocks.map((block, index) => {
        const lines = block.split(/\n/).map((line) => line.trim()).filter(Boolean);
        const isList = lines.length > 1 && lines.every((line) => /^([-*]|\d+[.)]|[（(]?\d+[）)])\s+/.test(line));
        const isFormulaBlock = /^\$\$[\s\S]+\$\$$/.test(block);
        const fencedBlock = /^```([A-Za-z0-9_-]*)\n([\s\S]*?)```$/.exec(block);
        const heading = /^(#{2,4})\s+(.+)$/.exec(block);
        if (isFormulaBlock) {
          return <div className="math-block" key={index}>{block.replace(/^\$\$|\$\$$/g, '').trim()}</div>;
        }
        if (fencedBlock) {
          const language = fencedBlock[1] || 'text';
          return (
            <pre className={language === 'mermaid' ? 'diagram-block' : 'code-block'} key={index}>
              <code>{fencedBlock[2].trim()}</code>
            </pre>
          );
        }
        if (heading) {
          return <h4 key={index}>{renderInlineMath(heading[2])}</h4>;
        }
        if (isList) {
          return (
            <ul key={index}>
              {lines.map((line, itemIndex) => (
                <li key={itemIndex}>{renderInlineMath(line.replace(/^([-*]|\d+[.)]|[（(]?\d+[）)])\s+/, ''))}</li>
              ))}
            </ul>
          );
        }
        return <p key={index}>{renderInlineMath(block)}</p>;
      })}
    </div>
  );
}

function renderInlineMath(text: string): ReactNode[] {
  return renderEnhancedInlineMath(text);
}

type RichTextListBlock = {
  kind: 'list';
  ordered: boolean;
  items: string[];
};

type RichTextBlockItem =
  | { kind: 'heading'; level: 2 | 3 | 4; content: string }
  | { kind: 'paragraph'; content: string }
  | RichTextListBlock
  | { kind: 'code'; language: string; content: string }
  | { kind: 'math'; content: string }
  | { kind: 'table'; headers: string[]; rows: string[][] };

type QualityScore = {
  title: string;
  score: number | null;
  note: string;
  needsReview: boolean;
};

export function RichTextBlock({ text, fallback }: { text: string; fallback: string }) {
  const normalized = stripRedundantLightHeading(text || fallback);
  const blocks = parseRichTextBlocks(normalized);
  if (blocks.length === 0) return <p>{fallback}</p>;
  return (
    <div className="rich-text-block rich-text-block-enhanced">
      {blocks.map((block, index) => {
        if (block.kind === 'heading') {
          if (block.level === 2) return <h2 key={index}>{renderEnhancedInlineMath(block.content)}</h2>;
          if (block.level === 3) return <h3 key={index}>{renderEnhancedInlineMath(block.content)}</h3>;
          return <h4 key={index}>{renderEnhancedInlineMath(block.content)}</h4>;
        }
        if (block.kind === 'math') {
          return <MathFormula tex={block.content} display key={index} />;
        }
        if (block.kind === 'code') {
          const language = block.language || 'text';
          return (
            <pre className={isDiagramLanguage(language) ? 'diagram-block' : 'code-block'} key={index}>
              {language !== 'text' && <span>{language}</span>}
              <code>{block.content}</code>
            </pre>
          );
        }
        if (block.kind === 'list') {
          const ListTag = block.ordered ? 'ol' : 'ul';
          return (
            <ListTag key={index}>
              {block.items.map((item, itemIndex) => (
                <li key={`${item}-${itemIndex}`}>{renderInlineRichContent(item)}</li>
              ))}
            </ListTag>
          );
        }
        if (block.kind === 'table') {
          return (
            <div className="markdown-table-wrap" key={index}>
              <table className="markdown-table">
                <thead>
                  <tr>
                    {block.headers.map((header, headerIndex) => (
                      <th key={`${header}-${headerIndex}`}>{renderInlineRichContent(header)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {block.headers.map((_, cellIndex) => (
                        <td key={cellIndex}>{renderInlineRichContent(row[cellIndex] ?? '')}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return <p key={index}>{renderInlineRichContent(block.content)}</p>;
      })}
    </div>
  );
}

function parseRichTextBlocks(text: string): RichTextBlockItem[] {
  const source = text.trim();
  if (!source) return [];
  const lines = source.split(/\r?\n/);
  const blocks: RichTextBlockItem[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trim();
    if (!line) continue;

    if (isMarkdownTableStart(lines, index)) {
      const tableLines = [lines[index], lines[index + 1]];
      index += 2;
      while (index < lines.length && isMarkdownTableRow(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      index -= 1;
      blocks.push(parseMarkdownTable(tableLines));
      continue;
    }

    if (looksLikeBareMathBlock(line)) {
      const mathLines = [rawLine.trim()];
      while (index + 1 < lines.length && lines[index + 1].trim() && looksLikeBareMathContinuation(lines[index + 1].trim())) {
        index += 1;
        mathLines.push(lines[index].trim());
      }
      blocks.push({ kind: 'math', content: mathLines.join('\n').trim() });
      continue;
    }

    if (line.startsWith('```')) {
      const language = line.slice(3).trim().toLowerCase();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }
      blocks.push({ kind: 'code', language: language || 'text', content: codeLines.join('\n').trimEnd() });
      continue;
    }

    if (line === '$$' || line.startsWith('$$')) {
      const mathLines: string[] = [];
      const firstLine = line.replace(/^\$\$\s?/, '');
      if (firstLine && !firstLine.endsWith('$$')) mathLines.push(firstLine);
      if (firstLine.endsWith('$$')) {
        mathLines.push(firstLine.replace(/\s?\$\$$/, ''));
      } else {
        index += 1;
        while (index < lines.length && !lines[index].trim().endsWith('$$')) {
          mathLines.push(lines[index].trimEnd());
          index += 1;
        }
        if (index < lines.length) mathLines.push(lines[index].trim().replace(/\s?\$\$$/, ''));
      }
      blocks.push({ kind: 'math', content: mathLines.join('\n').trim() });
      continue;
    }

    if (line.startsWith('\\[')) {
      const mathLines = [line.replace(/^\\\[\s?/, '')];
      while (index + 1 < lines.length && !lines[index].trim().endsWith('\\]')) {
        index += 1;
        mathLines.push(lines[index].trimEnd());
      }
      blocks.push({ kind: 'math', content: mathLines.join('\n').replace(/\s?\\\]$/, '').trim() });
      continue;
    }

    const heading = /^(#{2,4})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length as 2 | 3 | 4, content: heading[2].trim() });
      continue;
    }

    const unordered = /^[-*+]\s+(.+)$/.exec(line);
    const ordered = /^(\d+[.)]|[（(]?\d+[）)])\s+(.+)$/.exec(line);
    if (unordered || ordered) {
      const listBlock: RichTextListBlock = { kind: 'list', ordered: Boolean(ordered), items: [] };
      while (index < lines.length) {
        const current = lines[index].trim();
        const currentUnordered = /^[-*+]\s+(.+)$/.exec(current);
        const currentOrdered = /^(\d+[.)]|[（(]?\d+[）)])\s+(.+)$/.exec(current);
        if (listBlock.ordered && currentOrdered) listBlock.items.push(currentOrdered[2].trim());
        else if (!listBlock.ordered && currentUnordered) listBlock.items.push(currentUnordered[1].trim());
        else break;
        index += 1;
      }
      index -= 1;
      blocks.push(listBlock);
      continue;
    }

    const paragraph = [rawLine.trim()];
    while (index + 1 < lines.length && lines[index + 1].trim() && !isRichTextBlockStart(lines[index + 1])) {
      index += 1;
      paragraph.push(lines[index].trim());
    }
    blocks.push({ kind: 'paragraph', content: paragraph.join('\n') });
  }
  return blocks;
}

function isRichTextBlockStart(line: string) {
  const trimmed = line.trim();
  if (isMarkdownTableRow(trimmed)) return true;
  return /^#{2,4}\s+/.test(trimmed)
    || /^[-*+]\s+/.test(trimmed)
    || /^(\d+[.)]|[（(]?\d+[）)])\s+/.test(trimmed)
    || looksLikeBareMathBlock(trimmed)
    || trimmed.startsWith('```')
    || trimmed.startsWith('$$')
    || trimmed.startsWith('\\[');
}

function isDiagramLanguage(language: string) {
  return ['diagram', 'mermaid', 'flowchart', 'dot', 'graphviz', 'pseudocode', 'algorithm'].includes(language.toLowerCase());
}

function isMarkdownTableStart(lines: string[], index: number) {
  return index + 1 < lines.length && isMarkdownTableRow(lines[index]) && isMarkdownTableSeparator(lines[index + 1]);
}

function isMarkdownTableRow(line: string) {
  const trimmed = line.trim();
  return trimmed.includes('|') && /^\|?.+\|.+\|?$/.test(trimmed);
}

function isMarkdownTableSeparator(line: string) {
  const cells = splitMarkdownTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function splitMarkdownTableRow(line: string) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
}

function parseMarkdownTable(lines: string[]): RichTextBlockItem {
  const headers = splitMarkdownTableRow(lines[0]);
  const rows = lines.slice(2).filter(isMarkdownTableRow).map(splitMarkdownTableRow);
  return { kind: 'table', headers, rows };
}

function renderInlineRichContent(text: string): ReactNode[] {
  return text.split(/\n/).flatMap((line, index) => {
    const rendered = renderEnhancedInlineMath(line);
    return index === 0 ? rendered : [<br key={`br-${index}`} />, ...rendered];
  });
}

function renderEnhancedInlineMath(text: string): ReactNode[] {
  const normalized = normalizeMathDelimiters(text);
  return normalized.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*|\$[^$\n]+\$|\\\([^)]*\\\))/g).filter(Boolean).map((part, index) => {
    if (/^`[^`\n]+`$/.test(part)) {
      return <code className="inline-code" key={index}>{part.slice(1, -1)}</code>;
    }
    if (/^\*\*[^*\n]+\*\*$/.test(part)) {
      return <strong key={index}>{renderEnhancedInlineMath(part.slice(2, -2))}</strong>;
    }
    if (/^\$[^$\n]+\$$/.test(part)) {
      return <MathFormula tex={part.slice(1, -1)} key={index} />;
    }
    if (/^\\\([^)]*\\\)$/.test(part)) {
      return <MathFormula tex={part.slice(2, -2)} key={index} />;
    }
    return part;
  });
}

function normalizeMathDelimiters(markdown: string) {
  const protectedPattern = /```[\s\S]*?```|`[^`\n]+`|\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\[[\s\S]*?\\\]|\\\([^)]*\\\)/g;
  const pieces: string[] = [];
  let cursor = 0;
  for (const match of markdown.matchAll(protectedPattern)) {
    pieces.push(wrapBareMathInPlainText(markdown.slice(cursor, match.index)));
    pieces.push(match[0]);
    cursor = (match.index ?? 0) + match[0].length;
  }
  pieces.push(wrapBareMathInPlainText(markdown.slice(cursor)));
  return pieces.join('');
}

function wrapBareMathInPlainText(text: string) {
  const formulaPattern = new RegExp(
    [
      String.raw`\\frac\{[^{}\n]+\}\{[^{}\n]+\}`,
      String.raw`\\mathcal\{[^{}\n]+\}(?:[_^]\{?[A-Za-z0-9_\\]+\}?)?`,
      String.raw`\\(?:partial|nabla)(?:[_^]\{?[A-Za-z0-9_\\]+\}?)*(?:\s*[+\-=]\s*(?:\\(?:partial|nabla)(?:[_^]\{?[A-Za-z0-9_\\]+\}?)*|[A-Za-z](?:_[A-Za-z0-9\\{}]+|\^\{?[A-Za-z0-9+\\{}]+\}?)))*`,
      String.raw`\\(?:sum|int)(?:[_^]\{?[A-Za-z0-9_=+\-\\]+\}?)*(?:\s*[A-Za-z0-9_{}^\\=+\-*/().]+)?`,
      String.raw`\b[A-Za-z](?:_[A-Za-z0-9\\{}]+|\^\{?[A-Za-z0-9+\\{}]+\}?)(?:\([^)，。；;：:\n]*\))?(?:\s*=\s*[\[({]?[A-Za-z0-9_{}^\\+\-*/.,\s/]+[\])}]?)?`,
    ].join('|'),
    'g',
  );
  return text.replace(formulaPattern, (formula) => {
    const trimmed = trimTrailingMathPunctuation(formula);
    if (!trimmed) return formula;
    return `$${trimmed}$${formula.slice(trimmed.length)}`;
  });
}

function trimTrailingMathPunctuation(value: string) {
  return value.replace(/[，。；;：:、,.!?！？]+$/u, '').trimEnd();
}

function looksLikeBareMathBlock(line: string) {
  const trimmed = line.trim();
  if (/^(?:\\\[|\$\$)/.test(trimmed)) return false;
  if (/^\\(?:mathcal|frac|sum|int|partial|nabla|Delta|Bigl|left)\b/.test(trimmed) && /[=\\_{}^]/.test(trimmed)) return true;
  return /^[A-Za-z][A-Za-z0-9_{}^\\]*\s*=/.test(trimmed) && /[\\_{}^]/.test(trimmed);
}

function looksLikeBareMathContinuation(line: string) {
  return looksLikeBareMathBlock(line) || (/^[+\-=]/.test(line) && /[\\_{}^]/.test(line));
}

