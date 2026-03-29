import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { api, type Paper } from '../api';
import styles from './PapersList.module.css';

export function PapersList() {
  const fetcher = useCallback(() => api.getPapers(), []);
  const { data: papers, loading, error, refetch } = useApi<Paper[]>(fetcher);

  if (loading) return <p className={styles.state}>Loading papers…</p>;
  if (error) return (
    <div className={styles.state}>
      <p>Error: {error}</p>
      <button onClick={refetch}>Retry</button>
    </div>
  );
  if (!papers || papers.length === 0)
    return <p className={styles.state}>No papers found yet. The scraper may still be running.</p>;

  return (
    <ul className={styles.list}>
      {papers.map((p) => (
        <li key={p.id} className={styles.card}>
          <Link to={`/papers/${encodeURIComponent(p.id)}`} className={styles.title}>
            {p.title || '(Untitled)'}
          </Link>
          <p className={styles.meta}>
            Published: {p.published ? new Date(p.published).toLocaleDateString() : '—'}
          </p>
          {p.llmSummary && <p className={styles.summary}>{p.llmSummary}</p>}
        </li>
      ))}
    </ul>
  );
}
