import { ExternalLink } from "lucide-react";
import type { SearchHit } from "@/types/api";

interface Props {
  hit: SearchHit;
  compact?: boolean;
}

export function ResultCard({ hit, compact = false }: Props) {
  const section = [hit.section_name, hit.subsection_name]
    .filter(Boolean)
    .join(" › ");

  return (
    <article className="rounded-xl border border-zinc-800/80 bg-zinc-900/50 p-4 transition hover:border-zinc-700">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="font-medium leading-snug text-zinc-100">{hit.title}</h3>
          <p className="mt-0.5 text-xs text-zinc-500">
            {hit.arxiv_id}
            {section && ` · ${section}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="rounded-md bg-violet-500/15 px-2 py-0.5 text-xs font-medium text-violet-300">
            {(hit.score * 100).toFixed(0)}%
          </span>
          {hit.arxiv_url && (
            <a
              href={hit.arxiv_url}
              target="_blank"
              rel="noreferrer"
              className="text-zinc-500 hover:text-violet-400"
              title="Otwórz na arXiv"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          )}
        </div>
      </div>
      <p
        className={`text-sm leading-relaxed text-zinc-400 ${compact ? "line-clamp-3" : "line-clamp-5"}`}
      >
        {hit.content}
      </p>
    </article>
  );
}
