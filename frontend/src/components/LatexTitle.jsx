import { useMemo } from "react";
import katex from "katex";

/**
 * Renders a text string with inline LaTeX ($...$) converted to rendered math.
 * Falls back to raw text if KaTeX fails on a segment.
 */
export function LatexTitle({ text, className = "" }) {
  const html = useMemo(() => {
    if (!text || !text.includes("$")) return null;
    // Split on $...$ (non-greedy), preserving delimiters
    const parts = text.split(/(\$[^$]+\$)/g);
    return parts.map((part) => {
      if (part.startsWith("$") && part.endsWith("$")) {
        const latex = part.slice(1, -1);
        try {
          return katex.renderToString(latex, { throwOnError: false, displayMode: false });
        } catch {
          return part;
        }
      }
      // Escape HTML in text parts
      return part.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }).join("");
  }, [text]);

  if (!html) return <span className={className}>{text}</span>;
  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
