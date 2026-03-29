import { ScraperDashboard } from '../components/ScraperDashboard';
import styles from './ScraperPage.module.css';

export function ScraperPage() {
  return (
    <main className={styles.main}>
      <ScraperDashboard />
    </main>
  );
}
