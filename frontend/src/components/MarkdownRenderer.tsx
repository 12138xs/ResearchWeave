import { type ReactNode } from 'react';

function renderInlineMarkdown(text: string) {
  const nodes: ReactNode[] = [];
  const pattern = /!\[([^\]]*)\]\(([^)]+)\)|\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    if (match[1] !== undefined) {
      nodes.push(<img key={`${match.index}-img`} alt={match[1]} src={match[2]} />);
    } else if (match[3] !== undefined) {
      nodes.push(
        <a key={`${match.index}-link`} href={match[4]} target="_blank" rel="noreferrer">
          {match[3]}
        </a>
      );
    } else if (match[5] !== undefined) {
      nodes.push(<code key={`${match.index}-code`}>{match[5]}</code>);
    } else if (match[6] !== undefined) {
      nodes.push(<strong key={`${match.index}-strong`}>{match[6]}</strong>);
    }
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes.length > 0 ? nodes : text;
}

export function MarkdownRenderer({ markdown, emptyText = '这篇文档还没有正文。' }: { markdown?: string; emptyText?: string }) {
  const source = markdown?.trim();
  if (!source) return <div className="markdown-renderer markdown-empty">{emptyText}</div>;
  const lines = source.split(/\r?\n/);
  const blocks = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line.trim()) continue;

    if (line.startsWith('```')) {
      const language = line.slice(3).trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }
      blocks.push(
        <pre key={`code-${index}`}>
          {language && <span>{language}</span>}
          <code>{codeLines.join('\n')}</code>
        </pre>
      );
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = renderInlineMarkdown(heading[2]);
      if (level === 1) blocks.push(<h2 key={`h-${index}`}>{content}</h2>);
      else if (level === 2) blocks.push(<h3 key={`h-${index}`}>{content}</h3>);
      else blocks.push(<h4 key={`h-${index}`}>{content}</h4>);
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^[-*]\s+/, ''));
        index += 1;
      }
      index -= 1;
      blocks.push(
        <ul key={`ul-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`${item}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
          ))}
        </ul>
      );
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\d+\.\s+/, ''));
        index += 1;
      }
      index -= 1;
      blocks.push(
        <ol key={`ol-${index}`}>
          {items.map((item, itemIndex) => (
            <li key={`${item}-${itemIndex}`}>{renderInlineMarkdown(item)}</li>
          ))}
        </ol>
      );
      continue;
    }

    if (line.startsWith('>')) {
      blocks.push(<blockquote key={`quote-${index}`}>{renderInlineMarkdown(line.replace(/^>\s?/, ''))}</blockquote>);
      continue;
    }

    const paragraph = [line];
    while (index + 1 < lines.length && lines[index + 1].trim() && !/^(#{1,3})\s+|^[-*]\s+|^\d+\.\s+|^>|^```/.test(lines[index + 1])) {
      index += 1;
      paragraph.push(lines[index]);
    }
    blocks.push(<p key={`p-${index}`}>{renderInlineMarkdown(paragraph.join(' '))}</p>);
  }
  return <div className="markdown-renderer">{blocks}</div>;
}


