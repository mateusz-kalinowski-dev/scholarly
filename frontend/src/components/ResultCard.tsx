import { ExternalLink } from "lucide-react";
import type { SearchHit, SearchHitV2 } from "@/types/api";

type Hit = SearchHit | SearchHitV2;

function isV2(hit: Hit): hit is SearchHitV2 {
  return "child_id" in hit;
}

interface Props {
  hit: Hit;
  compact?: boolean;
}

export function ResultCard({ hit, compact = false }: Props) {
  const section = [hit.section_name, hit.subsection_name]
    .filter(Boolean)
    .join(" › ");

  const v2 = isV2(hit);
  const preview = v2 ? hit.content : hit.content;
  const snippet = v2 ? hit.child_snippet : null;

  return (
    <article className="rounded-xl border border-zinc-800/80 bg-zinc-900/50 p-4 transition hover:border-zinc-700">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="font-medium leading-snug text-zinc-100">{hit.title}</h3>
          <p className="mt-0.5 text-xs text-zinc-500">
            {hit.arxiv_id}
            {section && ` · ${section}`}
            {v2 && (
              <span className="ml-1 rounded bg-emerald-500/15 px-1.5 py-0.5 text-emerald-300">
                hybrid v2
              </span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="rounded-md bg-violet-500/15 px-2 py-0.5 text-xs font-medium text-violet-300">
            score {(hit.score * 100).toFixed(0)}%
          </span>
          {v2 && (
            <span className="text-[10px] text-zinc-600">
              vec {(1 - hit.vector_distance).toFixed(2)} · fts {hit.text_score.toFixed(3)}
            </span>
          )}
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
      {snippet && (
        <p className="mb-2 line-clamp-2 text-xs italic text-zinc-500">
          Dopasowany fragment: {snippet}
        </p>
      )}
      <p
        className={`text-sm leading-relaxed text-zinc-400 ${compact ? "line-clamp-3" : "line-clamp-5"}`}
      >
        {preview}
      </p>
      {!v2 && hit.content_original && (
        <p className="mt-2 line-clamp-2 text-xs text-zinc-600" title="Oryginał (EN)">
          EN: {hit.content_original}
        </p>
      )}
    </article>
  );
}
