import { useState } from "react";
import { Loader2, MessageSquare, Sparkles } from "lucide-react";
import { chatWithPapers } from "@/lib/api";
import type { ChatResponse, RetrievalMode } from "@/types/api";
import { ResultCard } from "./ResultCard";

export function ChatPanel() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<RetrievalMode>("hierarchical");
  const [rag, setRag] = useState(true);
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<ChatResponse | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;

    setLoading(true);
    setError(null);
    try {
      const data = await chatWithPapers(q, { topK, rag, mode });
      setResponse(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed");
      setResponse(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full flex-col gap-6">
      <form onSubmit={handleSubmit} className="space-y-4">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          placeholder="Zadaj pytanie o literaturę naukową…"
          className="w-full resize-none rounded-xl border border-zinc-800 bg-zinc-900/80 px-4 py-3 text-zinc-100 placeholder:text-zinc-500 outline-none transition focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/20"
        />

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex cursor-pointer items-center gap-2 text-zinc-400">
            <input
              type="checkbox"
              checked={rag}
              onChange={(e) => setRag(e.target.checked)}
              className="rounded border-zinc-700 bg-zinc-900 text-violet-600 focus:ring-violet-500/30"
            />
            RAG (retrieval)
          </label>
          {rag && (
            <>
              <label className="flex items-center gap-2 text-zinc-400">
                Tryb
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value as RetrievalMode)}
                  className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200"
                >
                  <option value="hierarchical">Hierarchical</option>
                  <option value="chunks">Chunki</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-zinc-400">
                Top-K
                <select
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200"
                >
                  {[3, 5, 8, 10].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="ml-auto flex items-center gap-2 rounded-lg bg-violet-600 px-5 py-2 font-medium text-white transition hover:bg-violet-500 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            Zapytaj
          </button>
        </div>
      </form>

      {error && (
        <div className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto">
        {response && (
          <>
            <section className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5">
              <div className="mb-3 flex items-center gap-2 text-sm text-zinc-500">
                <MessageSquare className="h-4 w-4" />
                Odpowiedź
                {!response.rag_enabled && (
                  <span className="rounded bg-amber-500/15 px-2 py-0.5 text-xs text-amber-400">
                    LLM-only (baseline)
                  </span>
                )}
              </div>
              <div className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">
                {response.answer}
              </div>
            </section>

            {response.rag_enabled && response.sources.length > 0 && (
              <section>
                <h3 className="mb-3 text-sm font-medium text-zinc-400">
                  Źródła ({response.sources.length})
                </h3>
                <div className="space-y-3">
                  {response.sources.map((src) => {
                    const paper = response.papers.find(
                      (p) => p.paper_id === src.paper_id,
                    );
                    return (
                    <ResultCard
                      key={src.chunk_id}
                      hit={{
                        chunk_id: src.chunk_id,
                        paper_id: src.paper_id,
                        arxiv_id: src.arxiv_id,
                        title: src.title,
                        arxiv_url: paper?.arxiv_url ?? null,
                        section_name: src.section_name,
                        subsection_name: null,
                        chunk_index: null,
                        content: src.content,
                        score: src.score,
                      }}
                      compact
                    />
                    );
                  })}
                </div>
              </section>
            )}
          </>
        )}

        {!response && !loading && !error && (
          <p className="py-12 text-center text-sm text-zinc-600">
            Zadaj pytanie — z RAG odpowiedź opiera się na fragmentach z bazy.
          </p>
        )}
      </div>
    </div>
  );
}
