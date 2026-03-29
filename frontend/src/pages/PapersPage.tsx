import { PapersList } from '../components/PapersList';
import styles from './PapersPage.module.css';

export function PapersPage() {
  return (
    <main className={styles.main}>
      <h1 className={styles.heading}>Academic Papers</h1>
      <p className={styles.sub}>Browse papers discovered and summarised by the AI pipeline.</p>
      <PapersList />
    </main>
  );
}
