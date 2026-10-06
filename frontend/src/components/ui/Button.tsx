import clsx from 'clsx';
import type { ComponentProps, ReactNode } from 'react';
import { Spinner } from './Spinner';
import { Tooltip } from './Tooltip';
import styles from './Button.module.css';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md';

interface ButtonProps extends ComponentProps<'button'> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={clsx(styles.button, styles[variant], styles[size], className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner size={14} /> : icon}
      {children}
    </button>
  );
}

interface IconButtonProps extends ComponentProps<'button'> {
  /** Accessible name; also shown as the tooltip. */
  label: string;
  /** Optional shortcut hint shown in the tooltip, e.g. "Ctrl+K". */
  shortcut?: string;
  variant?: 'ghost' | 'secondary' | 'primary';
  size?: Size;
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left';
}

export function IconButton({
  label,
  shortcut,
  variant = 'ghost',
  size = 'md',
  tooltipSide = 'bottom',
  className,
  type = 'button',
  ...rest
}: IconButtonProps) {
  return (
    <Tooltip content={label} shortcut={shortcut} side={tooltipSide}>
      <button
        type={type}
        aria-label={label}
        className={clsx(styles.iconButton, styles[variant], styles[size], className)}
        {...rest}
      />
    </Tooltip>
  );
}
