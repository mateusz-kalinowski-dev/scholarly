import { NavLink } from 'react-router-dom';
import styles from './Nav.module.css';

export function Nav() {
  return (
    <nav className={styles.nav}>
      <span className={styles.brand}>📚 Scholarly</span>
      <ul className={styles.links}>
        <li>
          <NavLink to="/" end className={({ isActive }) => (isActive ? styles.active : '')}>
            Papers
          </NavLink>
        </li>
        <li>
          <NavLink to="/graph" className={({ isActive }) => (isActive ? styles.active : '')}>
            Graph
          </NavLink>
        </li>
        <li>
          <NavLink to="/scraper" className={({ isActive }) => (isActive ? styles.active : '')}>
            Scraper
          </NavLink>
        </li>
      </ul>
    </nav>
  );
}
