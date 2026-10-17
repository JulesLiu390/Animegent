import { memo, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkCjkFriendly from "remark-cjk-friendly";
import remarkGfm from "remark-gfm";
import { useLightbox } from "../hooks";
import { isVideoPath, resolveMediaUrl } from "../lib/media";

interface Props {
  text: string;
  /** 当前项目：模型回复里的相对路径（output/panels/x.png）按这个项目解析 */
  project?: string | null;
  /** 点击指向项目文件的链接：返回 true 表示已处理（例如在预览面板打开） */
  onOpenLink?: (url: string) => boolean;
  streaming?: boolean;
  className?: string;
}

// cjk-friendly：让「**画面：**街上…」这种中文常见写法也能正确加粗（CommonMark 默认规则在全角标点后不能闭合）
const remarkPlugins = [remarkGfm, remarkCjkFriendly];

function MarkdownText({ text, project, onOpenLink, streaming, className = "" }: Props) {
  const openLightbox = useLightbox();

  const components = useMemo<Components>(() => ({
    a: ({ href, children }) => {
      const resolved = resolveMediaUrl(href, project) ?? href ?? "";
      return (
        <a
          href={resolved}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => {
            if (resolved && onOpenLink?.(resolved)) e.preventDefault();
          }}
        >
          {children}
        </a>
      );
    },
    img: ({ src, alt }) => {
      const resolved = resolveMediaUrl(typeof src === "string" ? src : "", project);
      if (!resolved) return <span className="text-zinc-400">[{alt || "image"}]</span>;
      if (isVideoPath(resolved)) {
        return <video src={resolved} controls className="my-2 max-h-80 rounded-xl" />;
      }
      return (
        <img
          src={resolved}
          alt={alt || ""}
          loading="lazy"
          onClick={() => openLightbox([{ url: resolved, name: alt || undefined }])}
        />
      );
    },
    table: ({ children }) => (
      <div className="my-3 overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
        <table>{children}</table>
      </div>
    ),
  }), [project, onOpenLink, openLightbox]);

  return (
    <div className={`md ${streaming ? "md-streaming" : ""} ${className}`}>
      <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

export default memo(MarkdownText);
