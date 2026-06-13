import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";

/** Normalizuje \( \) i \[ \] do $ / $$ (częsty format LLM). */
function normalizeMathDelimiters(text: string): string {
  return text
    .replace(/\\\[([\s\S]*?)\\\]/g, (_, eq: string) => `$$${eq.trim()}$$`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_, eq: string) => `$${eq.trim()}$`);
}

interface Props {
  content: string;
  className?: string;
}

export function MarkdownAnswer({ content, className = "" }: Props) {
  const normalized = normalizeMathDelimiters(content);

  return (
    <article className={`markdown-answer ${className}`.trim()}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-violet-400 underline-offset-2 hover:underline"
            >
              {children}
            </a>
          ),
          code: ({ className: codeClass, children, ...props }) => {
            const isBlock = codeClass?.includes("language-");
            if (isBlock) {
              return (
                <code className={codeClass} {...props}>
                  {children}
                </code>
              );
            }
            return (
              <code
                className="rounded bg-zinc-800 px-1.5 py-0.5 text-[0.9em] text-violet-200"
                {...props}
              >
                {children}
              </code>
            );
          },
        }}
      >
        {normalized}
      </ReactMarkdown>
    </article>
  );
}
