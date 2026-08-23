import React from "react";

interface Props {
  content: string;
}

export default function MarkdownView({ content }: Props) {
  if (!content) return null;

  // Split content into blocks by double line-breaks, while preserving fenced code blocks intact
  const blocks = parseBlocks(content);

  return (
    <div className="space-y-2.5 text-sm text-gray-200 leading-relaxed break-words font-sans">
      {blocks.map((block, i) => (
        <React.Fragment key={i}>{renderBlock(block)}</React.Fragment>
      ))}
    </div>
  );
}

type BlockType =
  | { type: "heading"; level: number; text: string }
  | { type: "code"; lang: string; code: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "blockquote"; text: string }
  | { type: "paragraph"; lines: string[] };

function parseBlocks(raw: string): BlockType[] {
  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  const blocks: BlockType[] = [];

  let currentLines: string[] = [];
  let inCodeBlock = false;
  let codeLang = "";
  let codeLines: string[] = [];
  let listItems: string[] = [];
  let isOrderedList = false;

  function flushParagraph() {
    if (currentLines.length > 0) {
      blocks.push({ type: "paragraph", lines: [...currentLines] });
      currentLines = [];
    }
  }

  function flushList() {
    if (listItems.length > 0) {
      blocks.push({
        type: "list",
        ordered: isOrderedList,
        items: [...listItems],
      });
      listItems = [];
      isOrderedList = false;
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Fenced Code Block Handling
    if (line.trim().startsWith("```")) {
      if (inCodeBlock) {
        // End code block
        blocks.push({ type: "code", lang: codeLang, code: codeLines.join("\n") });
        inCodeBlock = false;
        codeLang = "";
        codeLines = [];
      } else {
        // Start code block
        flushParagraph();
        flushList();
        inCodeBlock = true;
        codeLang = line.trim().slice(3).trim();
        codeLines = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    const trimmed = line.trim();

    // Empty line separates blocks
    if (trimmed === "") {
      flushParagraph();
      flushList();
      continue;
    }

    // Headings
    if (trimmed.startsWith("### ")) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: 3, text: trimmed.slice(4) });
      continue;
    }
    if (trimmed.startsWith("## ")) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: 2, text: trimmed.slice(3) });
      continue;
    }
    if (trimmed.startsWith("# ")) {
      flushParagraph();
      flushList();
      blocks.push({ type: "heading", level: 1, text: trimmed.slice(2) });
      continue;
    }

    // Blockquotes
    if (trimmed.startsWith("> ")) {
      flushParagraph();
      flushList();
      blocks.push({ type: "blockquote", text: trimmed.slice(2) });
      continue;
    }

    // Unordered List Items: "- " or "* "
    if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph();
      if (listItems.length > 0 && isOrderedList) {
        flushList();
      }
      isOrderedList = false;
      listItems.push(trimmed.replace(/^[-*]\s+/, ""));
      continue;
    }

    // Ordered List Items: "1. ", "2. ", etc.
    const orderedMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
    if (orderedMatch) {
      flushParagraph();
      if (listItems.length > 0 && !isOrderedList) {
        flushList();
      }
      isOrderedList = true;
      listItems.push(orderedMatch[2]);
      continue;
    }

    // If currently in a list item and line is indented, attach to last list item
    if (listItems.length > 0 && (line.startsWith("  ") || line.startsWith("\t"))) {
      listItems[listItems.length - 1] += " " + trimmed;
      continue;
    }

    // Regular paragraph line
    flushList();
    currentLines.push(line);
  }

  if (inCodeBlock) {
    blocks.push({ type: "code", lang: codeLang, code: codeLines.join("\n") });
  }
  flushParagraph();
  flushList();

  return blocks;
}

function renderBlock(block: BlockType): React.ReactNode {
  switch (block.type) {
    case "heading": {
      if (block.level === 1) {
        return (
          <h1 className="text-base font-bold text-gray-100 mt-3 mb-1.5 pb-1 border-b border-gray-800 flex items-center gap-2">
            {renderInlineMarkdown(block.text)}
          </h1>
        );
      }
      if (block.level === 2) {
        return (
          <h2 className="text-sm font-bold text-pilot-accent mt-2.5 mb-1 flex items-center gap-1.5">
            {renderInlineMarkdown(block.text)}
          </h2>
        );
      }
      return (
        <h3 className="text-xs font-semibold text-gray-200 uppercase tracking-wide mt-2 mb-1 text-gray-300">
          {renderInlineMarkdown(block.text)}
        </h3>
      );
    }

    case "code":
      return (
        <div className="my-2 rounded-lg bg-gray-950/90 border border-gray-800 p-3 overflow-x-auto shadow-inner">
          {block.lang && (
            <div className="text-[10px] font-mono text-gray-500 uppercase mb-1">
              {block.lang}
            </div>
          )}
          <pre className="font-mono text-xs text-emerald-400 leading-relaxed select-text whitespace-pre">
            {block.code}
          </pre>
        </div>
      );

    case "list":
      if (block.ordered) {
        return (
          <ol className="space-y-1 my-1.5 pl-1">
            {block.items.map((item, idx) => (
              <li key={idx} className="flex items-start gap-2 text-xs sm:text-sm text-gray-200">
                <span className="font-mono text-xs font-bold text-pilot-accent shrink-0 mt-0.5">
                  {idx + 1}.
                </span>
                <div className="flex-1 leading-relaxed">{renderInlineMarkdown(item)}</div>
              </li>
            ))}
          </ol>
        );
      }
      return (
        <ul className="space-y-1 my-1.5 pl-1">
          {block.items.map((item, idx) => (
            <li key={idx} className="flex items-start gap-2 text-xs sm:text-sm text-gray-200">
              <span className="text-pilot-accent shrink-0 mt-1 text-[8px] leading-none select-none">
                ●
              </span>
              <div className="flex-1 leading-relaxed">{renderInlineMarkdown(item)}</div>
            </li>
          ))}
        </ul>
      );

    case "blockquote":
      return (
        <blockquote className="border-l-2 border-pilot-accent pl-3 py-1 my-1.5 text-xs text-gray-400 bg-gray-900/40 rounded-r">
          {renderInlineMarkdown(block.text)}
        </blockquote>
      );

    case "paragraph":
      return (
        <div className="leading-relaxed">
          {block.lines.map((line, idx) => (
            <React.Fragment key={idx}>
              {renderInlineMarkdown(line)}
              {idx < block.lines.length - 1 && <br />}
            </React.Fragment>
          ))}
        </div>
      );
  }
}

/**
 * Parses inline formatting: **bold**, *italic*, `code`, and plain text.
 */
function renderInlineMarkdown(text: string): React.ReactNode {
  if (!text) return null;

  // Regex tokens matching `code`, **bold**, *italic*, [link](url)
  const tokenRegex = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g;
  const parts = text.split(tokenRegex);

  return parts.map((part, index) => {
    if (!part) return null;

    // Inline code
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      return (
        <code
          key={index}
          className="font-mono text-[11px] sm:text-xs px-1.5 py-0.5 rounded bg-gray-900 text-amber-300 border border-gray-800 mx-0.5"
        >
          {part.slice(1, -1)}
        </code>
      );
    }

    // Bold
    if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
      return (
        <strong key={index} className="font-semibold text-gray-100">
          {part.slice(2, -2)}
        </strong>
      );
    }

    // Italic
    if (part.startsWith("*") && part.endsWith("*") && part.length >= 2) {
      return (
        <em key={index} className="italic text-gray-300">
          {part.slice(1, -1)}
        </em>
      );
    }

    return <span key={index}>{part}</span>;
  });
}
