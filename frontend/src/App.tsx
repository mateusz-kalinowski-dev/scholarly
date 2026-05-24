import { useEffect, useState } from "react";
import { BookOpen, MessageSquare, Search } from "lucide-react";
import { checkHealth } from "@/lib/api";
import { ChatPanel } from "@/components/ChatPanel";
import { SearchPanel } from "@/components/SearchPanel";

type Tab = "search" | "chat";

function App() {
  const [tab, setTab] = useState<Tab>("chat");
  const [apiOk, setApiOk] = useState<boolean | null>(null);

  useEffect(() => {
    checkHealth()
      .then(() => setApiOk(true))
      .catch(() => setApiOk(false));
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-zinc-950 text-zinc-100">
      <header className="shrink-0 border-b border-zinc-800/80 bg-zinc-950/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-600/20 text-violet-400">
              <BookOpen className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight">Scholarly</h1>
              <p className="text-xs text-zinc-500">RAG nad pracami arXiv</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span
              className={`hidden rounded-full px-2.5 py-1 text-xs sm:inline ${
                apiOk === true
                  ? "bg-emerald-500/15 text-emerald-400"
                  : apiOk === false
                    ? "bg-red-500/15 text-red-400"
                    : "bg-zinc-800 text-zinc-500"
              }`}
            >
              API {apiOk === true ? "online" : apiOk === false ? "offline" : "…"}
            </span>

            <nav className="flex rounded-lg border border-zinc-800 bg-zinc-900/50 p-1">
              <button
                type="button"
                onClick={() => setTab("chat")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition ${
                  tab === "chat"
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                <MessageSquare className="h-4 w-4" />
                Chat
              </button>
              <button
                type="button"
                onClick={() => setTab("search")}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition ${
                  tab === "search"
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                <Search className="h-4 w-4" />
                Szukaj
              </button>
            </nav>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-4 py-6 sm:px-6">
        <div className="flex min-h-[calc(100vh-8rem)] flex-1 flex-col rounded-2xl border border-zinc-800/60 bg-zinc-900/30 p-4 sm:p-6">
          {tab === "search" ? <SearchPanel /> : <ChatPanel />}
        </div>
      </main>
    </div>
  );
}

export default App;
