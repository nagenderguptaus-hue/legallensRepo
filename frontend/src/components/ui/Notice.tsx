import clsx from 'clsx';
import type { ReactNode } from 'react';
import styles from './Notice.module.css';

interface NoticeProps {
  tone?: 'info' | 'warning' | 'danger' | 'neutral';
  icon?: ReactNode;
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  role?: 'alert' | 'status';
  className?: string;
}

export function Notice({ tone = 'info', icon, title, children, actions, role, className }: NoticeProps) {
  return (
    <div className={clsx(styles.notice, styles[tone], className)} role={role}>
      {icon && <span className={styles.icon}>{icon}</span>}
      <div className={styles.body}>
        {title && <p className={styles.title}>{title}</p>}
        {children && <div className={styles.content}>{children}</div>}
        {actions && <div className={styles.actions}>{actions}</div>}
      </div>
    </div>
  );
}
