import { useState } from "react";

import { Loader2, Search } from "lucide-react";

import { searchPapers } from "@/lib/api";

import type {

  ApiVersion,

  QueryStrategy,

  RetrievalMode,

  SearchHit,

  SearchHitV2,

  SearchResponseV2,

} from "@/types/api";

import { ResultCard } from "./ResultCard";



export function SearchPanel() {

  const [query, setQuery] = useState("");

  const [apiVersion, setApiVersion] = useState<ApiVersion>("v2");

  const [mode, setMode] = useState<RetrievalMode>("hierarchical");

  const [queryStrategy, setQueryStrategy] = useState<QueryStrategy>("rewrite");

  const [topK, setTopK] = useState(5);

  const [loading, setLoading] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const [results, setResults] = useState<(SearchHit | SearchHitV2)[]>([]);

  const [searchedQuery, setSearchedQuery] = useState("");

  const [retrievalMeta, setRetrievalMeta] = useState<SearchResponseV2["retrieval"]>(null);



  const effectiveStrategy: QueryStrategy =

    apiVersion === "v2" ? "rewrite" : queryStrategy;



  async function handleSubmit(e: React.FormEvent) {

    e.preventDefault();

    const q = query.trim();

    if (!q) return;



    setLoading(true);

    setError(null);

    try {

      const data = await searchPapers(q, topK, mode, effectiveStrategy, apiVersion);

      setResults(data.results);

      setSearchedQuery(data.query);

      setRetrievalMeta(

        apiVersion === "v2" ? (data as SearchResponseV2).retrieval ?? null : null,

      );

    } catch (err) {

      setError(err instanceof Error ? err.message : "Search failed");

      setResults([]);

      setRetrievalMeta(null);

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

          {apiVersion === "v1" && (

            <label className="flex items-center gap-2 text-zinc-400">

              Zapytanie

              <select

                value={queryStrategy}

                onChange={(e) =>

                  setQueryStrategy(e.target.value as QueryStrategy)

                }

                className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200 outline-none focus:border-violet-500/50"

              >

                <option value="classic">Klasyczne</option>

                <option value="rewrite">Rewrite (EN)</option>

              </select>

            </label>

          )}



          <label className="flex items-center gap-2 text-zinc-400">

            API

            <select

              value={apiVersion}

              onChange={(e) => setApiVersion(e.target.value as ApiVersion)}

              className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200 outline-none focus:border-violet-500/50"

            >

              <option value="v2">v2 lejek (hybrid + rerank)</option>

              <option value="v1">v1 legacy</option>

            </select>

          </label>



          {apiVersion === "v1" && (

            <label className="flex items-center gap-2 text-zinc-400">

              Retrieval

              <select

                value={mode}

                onChange={(e) => setMode(e.target.value as RetrievalMode)}

                className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200 outline-none focus:border-violet-500/50"

              >

                <option value="hierarchical">Hierarchical</option>

                <option value="chunks">Wszystkie chunki</option>

              </select>

            </label>

          )}



          <label className="flex items-center gap-2 text-zinc-400">

            {apiVersion === "v2" ? "Wyniki (rodzice)" : "Top-K"}

            <select

              value={topK}

              onChange={(e) => setTopK(Number(e.target.value))}

              className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200 outline-none focus:border-violet-500/50"

            >

              {(apiVersion === "v2" ? [5, 10, 15, 20] : [3, 5, 10, 15]).map((n) => (

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

            {retrievalMeta?.child_candidates != null && (

              <span className="block text-xs text-zinc-600">

                Lejek: {retrievalMeta.child_candidates} dzieci →{" "}

                {retrievalMeta.parent_candidates} rodziców

                {retrievalMeta.rerank_top_score != null &&

                  ` · najlepszy rerank ${(retrievalMeta.rerank_top_score * 100).toFixed(0)}%`}

              </span>

            )}

          </p>

        )}

        <div className="space-y-3">

          {results.map((hit) => (

            <ResultCard

              key={"child_id" in hit ? hit.child_id : hit.chunk_id}

              hit={hit}

            />

          ))}

        </div>

        {!loading && searchedQuery && results.length === 0 && !error && (

          <p className="text-center text-zinc-500">Brak wyników.</p>

        )}

      </div>

    </div>

  );

}


