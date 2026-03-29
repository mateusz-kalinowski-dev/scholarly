const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:3000';

export interface Paper {
  id: string;
  title: string;
  arxivSummary: string;
  llmSummary: string;
  published: string;
  objectName: string;
  authors?: { name: string }[];
  topics?: { name: string }[];
  citations?: Paper[];
}

export interface ScraperStatus {
  status: string;
  queueLength: number;
}

export interface ScraperFile {
  name: string;
  size: number;
  lastModified: string;
}

export interface GraphNode {
  id: string;
  label: string;
  title?: string;
  name?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export const api = {
  getPapers: () => apiFetch<Paper[]>('/api/papers'),
  getPaper: (id: string) => apiFetch<Paper>(`/api/papers/${encodeURIComponent(id)}`),
  getScraperStatus: () => apiFetch<ScraperStatus>('/api/scraper/status'),
  getScraperFiles: () => apiFetch<ScraperFile[]>('/api/scraper/files'),
  getGraph: () => apiFetch<GraphData>('/api/graph/papers'),
};
