import { getFileUrl } from "../api";

interface Props {
  text: string;
  className?: string;
}

export default function MarkdownText({ text, className = "" }: Props) {
  const lines = text.split("\n");
  const elements: JSX.Element[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.startsWith("```")) {
      const lang = line.slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      elements.push(
        <pre key={elements.length} className="my-2 p-3 bg-gray-100 dark:bg-gray-900 rounded-lg overflow-x-auto text-xs font-mono">
          {lang && <div className="text-[10px] text-gray-400 mb-1">{lang}</div>}
          <code>{codeLines.join("\n")}</code>
        </pre>
      );
      continue;
    }

    // Headers
    if (line.startsWith("### ")) {
      elements.push(<h3 key={elements.length} className="text-sm font-semibold mt-3 mb-1">{renderInline(line.slice(4))}</h3>);
      i++; continue;
    }
    if (line.startsWith("## ")) {
      elements.push(<h2 key={elements.length} className="text-base font-semibold mt-3 mb-1">{renderInline(line.slice(3))}</h2>);
      i++; continue;
    }
    if (line.startsWith("# ")) {
      elements.push(<h1 key={elements.length} className="text-lg font-bold mt-3 mb-1">{renderInline(line.slice(2))}</h1>);
      i++; continue;
    }

    // Unordered list
    if (line.match(/^[\-\*]\s/)) {
      const listItems: JSX.Element[] = [];
      while (i < lines.length && lines[i].match(/^[\-\*]\s/)) {
        listItems.push(<li key={listItems.length}>{renderInline(lines[i].replace(/^[\-\*]\s/, ""))}</li>);
        i++;
      }
      elements.push(<ul key={elements.length} className="my-1 pl-4 list-disc space-y-0.5">{listItems}</ul>);
      continue;
    }

    // Ordered list
    if (line.match(/^\d+\.\s/)) {
      const listItems: JSX.Element[] = [];
      while (i < lines.length && lines[i].match(/^\d+\.\s/)) {
        listItems.push(<li key={listItems.length}>{renderInline(lines[i].replace(/^\d+\.\s/, ""))}</li>);
        i++;
      }
      elements.push(<ol key={elements.length} className="my-1 pl-4 list-decimal space-y-0.5">{listItems}</ol>);
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      elements.push(<div key={elements.length} className="h-2" />);
      i++; continue;
    }

    // Regular paragraph
    elements.push(<p key={elements.length} className="my-0.5">{renderInline(line)}</p>);
    i++;
  }

  return <div className={`text-sm ${className}`}>{elements}</div>;
}

/** Render inline markdown: bold, italic, code, images, links */
function renderInline(text: string): (string | JSX.Element)[] {
  // Split by markdown patterns: ![alt](url), **bold**, *italic*, `code`, [text](url)
  const parts = text.split(/(!\[[^\]]*\]\([^)]+\)|\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/);

  return parts.map((part, i) => {
    // Image
    const imgMatch = part.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    if (imgMatch) {
      const [, alt, url] = imgMatch;
      const src = url.startsWith("/") ? getFileUrl(url) : url;
      return <img key={i} src={src} alt={alt} className="my-2 rounded-lg max-h-64 object-contain inline-block" />;
    }

    // Link
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      const [, linkText, href] = linkMatch;
      return <a key={i} href={href} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">{linkText}</a>;
    }

    // Bold
    const boldMatch = part.match(/^\*\*(.+)\*\*$/);
    if (boldMatch) {
      return <strong key={i}>{boldMatch[1]}</strong>;
    }

    // Italic
    const italicMatch = part.match(/^\*(.+)\*$/);
    if (italicMatch) {
      return <em key={i}>{italicMatch[1]}</em>;
    }

    // Inline code
    const codeMatch = part.match(/^`(.+)`$/);
    if (codeMatch) {
      return <code key={i} className="px-1 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-xs font-mono">{codeMatch[1]}</code>;
    }

    return part;
  });
}
