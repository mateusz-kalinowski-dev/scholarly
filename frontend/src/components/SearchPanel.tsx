import { useState } from "react";
import { Loader2, Search } from "lucide-react";
import { searchPapers } from "@/lib/api";
import type { RetrievalMode, SearchHit } from "@/types/api";
import { ResultCard } from "./ResultCard";

export function SearchPanel() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<RetrievalMode>("hierarchical");
  const [topK, setTopK] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<SearchHit[]>([]);
  const [searchedQuery, setSearchedQuery] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;

    setLoading(true);
    setError(null);
    try {
      const data = await searchPapers(q, topK, mode);
      setResults(data.results);
      setSearchedQuery(data.query);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed");
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full flex-col gap-6">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Szukaj w pracach arXiv… np. Flash Attention"
            className="w-full rounded-xl border border-zinc-800 bg-zinc-900/80 py-3.5 pl-12 pr-4 text-zinc-100 placeholder:text-zinc-500 outline-none ring-violet-500/0 transition focus:border-violet-500/50 focus:ring-2 focus:ring-violet-500/20"
          />
        </div>

        <div className="flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-2 text-zinc-400">
            Tryb
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as RetrievalMode)}
              className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200 outline-none focus:border-violet-500/50"
            >
              <option value="hierarchical">Hierarchical</option>
              <option value="chunks">Wszystkie chunki</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-zinc-400">
            Top-K
            <select
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200 outline-none focus:border-violet-500/50"
            >
              {[3, 5, 10, 15].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="ml-auto flex items-center gap-2 rounded-lg bg-violet-600 px-5 py-2 font-medium text-white transition hover:bg-violet-500 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            Szukaj
          </button>
        </div>
      </form>

      {error && (
        <div className="rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {searchedQuery && !loading && (
          <p className="mb-4 text-sm text-zinc-500">
            {results.length} wyników dla „{searchedQuery}”
          </p>
        )}
        <div className="space-y-3">
          {results.map((hit) => (
            <ResultCard key={hit.chunk_id} hit={hit} />
          ))}
        </div>
        {!loading && searchedQuery && results.length === 0 && !error && (
          <p className="text-center text-zinc-500">Brak wyników.</p>
        )}
      </div>
    </div>
  );
}
