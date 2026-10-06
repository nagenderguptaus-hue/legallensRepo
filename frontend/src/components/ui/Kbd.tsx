import clsx from 'clsx';
import type { ReactNode } from 'react';
import styles from './Kbd.module.css';

export function Kbd({ children, tone = 'default' }: { children: ReactNode; tone?: 'default' | 'inverse' }) {
  return <kbd className={clsx(styles.kbd, tone === 'inverse' && styles.inverse)}>{children}</kbd>;
}
