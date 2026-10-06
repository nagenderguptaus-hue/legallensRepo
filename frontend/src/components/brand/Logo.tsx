import styles from './Logo.module.css';

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className={styles.mark}>
      <rect width="32" height="32" rx="8" fill="var(--primary)" />
      <g fill="none" stroke="#FAF9F6" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M16 7v18M11 25h10M9 11h14" />
        <path d="M9 11l-3.5 7h7z" />
        <path d="M23 11l-3.5 7h7z" />
      </g>
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className={styles.wordmark}>
      <LogoMark />
      <span className={styles.name}>Legal Lens</span>
    </span>
  );
}
