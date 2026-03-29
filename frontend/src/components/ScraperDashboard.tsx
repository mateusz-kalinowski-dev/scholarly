import { useCallback } from 'react';
import { useApi } from '../hooks/useApi';
import { api, type ScraperStatus, type ScraperFile } from '../api';
import styles from './ScraperDashboard.module.css';

export function ScraperDashboard() {
  const statusFetcher = useCallback(() => api.getScraperStatus(), []);
  const filesFetcher = useCallback(() => api.getScraperFiles(), []);

  const {
    data: status,
    loading: statusLoading,
    error: statusError,
    refetch: refetchStatus,
  } = useApi<ScraperStatus>(statusFetcher);

  const {
    data: files,
    loading: filesLoading,
    error: filesError,
    refetch: refetchFiles,
  } = useApi<ScraperFile[]>(filesFetcher);

  return (
    <div>
      <h1 className={styles.heading}>Scraper Dashboard</h1>

      <section className={styles.card}>
        <h2>Status</h2>
        {statusLoading && <p className={styles.muted}>Loading…</p>}
        {statusError && <p className={styles.error}>Error: {statusError} <button onClick={refetchStatus}>Retry</button></p>}
        {status && (
          <dl className={styles.dl}>
            <dt>State</dt>
            <dd>
              <span className={status.status === 'running' ? styles.running : styles.idle}>
                {status.status}
              </span>
            </dd>
            <dt>Queue length</dt>
            <dd>{status.queueLength}</dd>
          </dl>
        )}
      </section>

      <section className={styles.card}>
        <div className={styles.cardHeader}>
          <h2>Stored PDFs</h2>
          <button className={styles.refreshBtn} onClick={refetchFiles}>↻ Refresh</button>
        </div>
        {filesLoading && <p className={styles.muted}>Loading…</p>}
        {filesError && <p className={styles.error}>Error: {filesError}</p>}
        {files && files.length === 0 && <p className={styles.muted}>No files stored yet.</p>}
        {files && files.length > 0 && (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>File name</th>
                <th>Size (KB)</th>
                <th>Last modified</th>
              </tr>
            </thead>
            <tbody>
              {files.map((f) => (
                <tr key={f.name}>
                  <td>{f.name}</td>
                  <td>{(f.size / 1024).toFixed(1)}</td>
                  <td>{new Date(f.lastModified).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
