import { useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { api, type Paper } from '../api';
import styles from './PaperDetail.module.css';

export function PaperDetail() {
  const { id } = useParams<{ id: string }>();
  const fetcher = useCallback(() => api.getPaper(id!), [id]);
  const { data: paper, loading, error } = useApi<Paper>(fetcher);

  if (loading) return <p className={styles.state}>Loading…</p>;
  if (error) return <p className={styles.state}>Error: {error}</p>;
  if (!paper) return <p className={styles.state}>Paper not found.</p>;

  return (
    <article className={styles.article}>
      <Link to="/" className={styles.back}>← Back to papers</Link>
      <h1 className={styles.title}>{paper.title}</h1>
      <p className={styles.meta}>
        Published: {paper.published ? new Date(paper.published).toLocaleDateString() : '—'}
      </p>

      {paper.authors && paper.authors.length > 0 && (
        <section className={styles.section}>
          <h2>Authors</h2>
          <p>{paper.authors.map((a) => a.name).join(', ')}</p>
        </section>
      )}

      {paper.llmSummary && (
        <section className={styles.section}>
          <h2>AI Summary</h2>
          <p>{paper.llmSummary}</p>
        </section>
      )}

      {paper.arxivSummary && (
        <section className={styles.section}>
          <h2>Abstract</h2>
          <p>{paper.arxivSummary}</p>
        </section>
      )}

      {paper.topics && paper.topics.length > 0 && (
        <section className={styles.section}>
          <h2>Topics</h2>
          <ul className={styles.chips}>
            {paper.topics.map((t) => (
              <li key={t.name} className={styles.chip}>{t.name}</li>
            ))}
          </ul>
        </section>
      )}

      {paper.citations && paper.citations.length > 0 && (
        <section className={styles.section}>
          <h2>Citations</h2>
          <ul className={styles.citations}>
            {paper.citations.map((c) => (
              <li key={c.id}>
                <Link to={`/papers/${encodeURIComponent(c.id)}`}>{c.title}</Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
