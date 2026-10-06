import clsx from 'clsx';
import type { ReactNode } from 'react';
import styles from './Badge.module.css';

export type BadgeTone =
  | 'neutral'
  | 'ask'
  | 'summary'
  | 'draft'
  | 'clarify'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info';

export function Badge({
  tone = 'neutral',
  icon,
  children,
  className,
}: {
  tone?: BadgeTone;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={clsx(styles.badge, styles[tone], className)}>
      {icon}
      {children}
    </span>
  );
}
