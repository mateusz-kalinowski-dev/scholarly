import { GraphView } from '../components/GraphView';
import styles from './GraphPage.module.css';

export function GraphPage() {
  return (
    <main className={styles.main}>
      <GraphView />
    </main>
  );
}
