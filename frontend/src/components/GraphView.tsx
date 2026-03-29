import { useCallback } from 'react';
import { useApi } from '../hooks/useApi';
import { api, type GraphData } from '../api';
import styles from './GraphView.module.css';

export function GraphView() {
  const fetcher = useCallback(() => api.getGraph(), []);
  const { data, loading, error, refetch } = useApi<GraphData>(fetcher);

  if (loading) return <p className={styles.state}>Loading graph…</p>;
  if (error) return (
    <div className={styles.state}>
      <p>Error: {error}</p>
      <button onClick={refetch}>Retry</button>
    </div>
  );
  if (!data || data.nodes.length === 0)
    return <p className={styles.state}>No graph data yet. Papers will appear here once processed.</p>;

  const paperNodes = data.nodes.filter((n) => n.label === 'Paper');
  const otherNodes = data.nodes.filter((n) => n.label !== 'Paper');

  return (
    <div>
      <h1 className={styles.heading}>Knowledge Graph</h1>
      <p className={styles.sub}>
        {data.nodes.length} nodes · {data.edges.length} edges
      </p>

      <div className={styles.grid}>
        <section className={styles.panel}>
          <h2>Papers ({paperNodes.length})</h2>
          <ul className={styles.nodeList}>
            {paperNodes.map((n) => (
              <li key={n.id} className={styles.nodeItem}>
                <span className={styles.badge} data-label="Paper">P</span>
                {n.title ?? n.name ?? n.id}
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.panel}>
          <h2>Other Nodes ({otherNodes.length})</h2>
          <ul className={styles.nodeList}>
            {otherNodes.map((n) => (
              <li key={n.id} className={styles.nodeItem}>
                <span className={styles.badge} data-label={n.label}>
                  {n.label.charAt(0)}
                </span>
                {n.name ?? n.title ?? n.id}
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className={styles.panel} style={{ marginTop: '1.25rem' }}>
        <h2>Edges ({data.edges.length})</h2>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Source</th>
              <th>Relationship</th>
              <th>Target</th>
            </tr>
          </thead>
          <tbody>
            {data.edges.slice(0, 100).map((e, i) => (
              <tr key={i}>
                <td>{e.source}</td>
                <td><span className={styles.relType}>{e.type}</span></td>
                <td>{e.target}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.edges.length > 100 && (
          <p className={styles.muted}>Showing first 100 edges of {data.edges.length}</p>
        )}
      </section>
    </div>
  );
}
