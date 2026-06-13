import { useState } from "react";

import { Loader2, MessageSquare, Sparkles } from "lucide-react";

import { chatWithPapers } from "@/lib/api";

import type { ApiVersion, ChatResponse, ChatResponseV2, QueryStrategy, RetrievalMode, RetrievalMetaV2 } from "@/types/api";

import { ResultCard } from "./ResultCard";

import { MarkdownAnswer } from "./MarkdownAnswer";



function FunnelMeta({ retrieval }: { retrieval: RetrievalMetaV2 | null | undefined }) {

  if (!retrieval) return null;

  const parts: string[] = [];

  if (retrieval.child_candidates != null) {

    parts.push(`${retrieval.child_candidates} dzieci`);

  }

  if (retrieval.parent_candidates != null) {

    parts.push(`${retrieval.parent_candidates} rodziców`);

  }

  if (retrieval.rerank_top_score != null) {

    parts.push(`rerank ${(retrieval.rerank_top_score * 100).toFixed(0)}%`);

  }

  if (retrieval.llm_context_count != null && retrieval.accepted !== false) {
    parts.push(`${retrieval.llm_context_count} do LLM`);
  }

  if (parts.length === 0) return null;

  return (

    <p className="mb-3 text-xs text-zinc-600">

      Lejek: {parts.join(" → ")}

      {retrieval.answer_verified === true && " · odpowiedź zweryfikowana"}

      {retrieval.accepted === false && " · brak trafnych źródeł"}

    </p>

  );

}



export function ChatPanel() {

  const [question, setQuestion] = useState("");

  const [apiVersion, setApiVersion] = useState<ApiVersion>("v2");

  const [mode, setMode] = useState<RetrievalMode>("hierarchical");

  const [queryStrategy, setQueryStrategy] = useState<QueryStrategy>("rewrite");

  const [rag, setRag] = useState(true);

  const [topK, setTopK] = useState(5);

  const [loading, setLoading] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const [response, setResponse] = useState<ChatResponse | ChatResponseV2 | null>(null);



  const effectiveStrategy: QueryStrategy =

    apiVersion === "v2" ? "rewrite" : queryStrategy;



  async function handleSubmit(e: React.FormEvent) {

    e.preventDefault();

    const q = question.trim();

    if (!q) return;



    setLoading(true);

    setError(null);

    try {

      const data = await chatWithPapers(q, {

        topK,

        rag,

        mode,

        queryStrategy: effectiveStrategy,

        apiVersion,

      });

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



          {apiVersion === "v1" && (

            <label className="flex items-center gap-2 text-zinc-400">

              Zapytanie

              <select

                value={queryStrategy}

                onChange={(e) =>

                  setQueryStrategy(e.target.value as QueryStrategy)

                }

                className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200"

              >

                <option value="classic">Klasyczne (embed surowe)</option>

                <option value="rewrite">Rewrite (EN)</option>

              </select>

            </label>

          )}



          <label className="flex items-center gap-2 text-zinc-400">

            API

            <select

              value={apiVersion}

              onChange={(e) => setApiVersion(e.target.value as ApiVersion)}

              className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200"

            >

              <option value="v2">v2 lejek (hybrid + rerank)</option>

              <option value="v1">v1 legacy</option>

            </select>

          </label>



          {rag && apiVersion === "v1" && (

            <label className="flex items-center gap-2 text-zinc-400">

              Retrieval

              <select

                value={mode}

                onChange={(e) => setMode(e.target.value as RetrievalMode)}

                className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200"

              >

                <option value="hierarchical">Hierarchical</option>

                <option value="chunks">Chunki</option>

              </select>

            </label>

          )}



          {rag && (

            <label className="flex items-center gap-2 text-zinc-400">

              {apiVersion === "v2" ? "Źródła (rodzice)" : "Top-K"}

              <select

                value={topK}

                onChange={(e) => setTopK(Number(e.target.value))}

                className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-zinc-200"

              >

                {(apiVersion === "v2" ? [3, 5, 8, 10] : [3, 5, 8, 10]).map((n) => (

                  <option key={n} value={n}>

                    {n}

                  </option>

                ))}

              </select>

            </label>

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



        {apiVersion === "v2" && rag && (

          <p className="text-xs text-zinc-600">

            v2 lejek: ~100 dzieci → rerank 50 rodziców → wybrane źródła (max 8)

            trafiają do LLM jako kontekst.

          </p>

        )}

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

              {response.retrieval_query && (

                <p className="mb-3 text-xs text-zinc-500">

                  Zapytanie do bazy (EN):{" "}

                  <span className="text-zinc-400">{response.retrieval_query}</span>

                  {response.user_language && (

                    <> · odpowiedź: {response.user_language}</>

                  )}

                </p>

              )}

              {apiVersion === "v2" && (

                <FunnelMeta retrieval={(response as ChatResponseV2).retrieval} />

              )}

              <MarkdownAnswer content={response.answer} />

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

                    const key = "child_id" in src ? src.child_id : src.chunk_id;

                    const hit =

                      "child_id" in src

                        ? {

                            child_id: src.child_id,

                            parent_id: src.parent_id,

                            paper_id: src.paper_id,

                            arxiv_id: src.arxiv_id,

                            title: src.title,

                            arxiv_url: paper?.arxiv_url ?? null,

                            section_name: src.section_name,

                            subsection_name: null,

                            child_snippet: src.child_snippet,

                            content: src.content,

                            vector_distance: src.vector_distance,

                            text_score: src.text_score,

                            score: src.score,

                          }

                        : {

                            chunk_id: src.chunk_id,

                            paper_id: src.paper_id,

                            arxiv_id: src.arxiv_id,

                            title: src.title,

                            arxiv_url: paper?.arxiv_url ?? null,

                            section_name: src.section_name,

                            subsection_name: null,

                            chunk_index: null,

                            content: src.content,

                            content_original: src.content_original,

                            score: src.score,

                          };

                    return <ResultCard key={key} hit={hit} compact />;

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


