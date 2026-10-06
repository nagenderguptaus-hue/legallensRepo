import * as RadixMenu from '@radix-ui/react-dropdown-menu';
import clsx from 'clsx';
import type { ReactNode } from 'react';
import styles from './Menu.module.css';

export const Menu = RadixMenu.Root;
export const MenuTrigger = RadixMenu.Trigger;

export function MenuContent({
  children,
  align = 'start',
  side = 'bottom',
  onCloseAutoFocus,
}: {
  children: ReactNode;
  align?: 'start' | 'center' | 'end';
  side?: 'top' | 'right' | 'bottom' | 'left';
  onCloseAutoFocus?: (event: Event) => void;
}) {
  return (
    <RadixMenu.Portal>
      <RadixMenu.Content
        className={styles.content}
        align={align}
        side={side}
        sideOffset={4}
        onCloseAutoFocus={onCloseAutoFocus}
      >
        {children}
      </RadixMenu.Content>
    </RadixMenu.Portal>
  );
}

export function MenuItem({
  icon,
  children,
  danger = false,
  disabled = false,
  onSelect,
}: {
  icon?: ReactNode;
  children: ReactNode;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <RadixMenu.Item
      className={clsx(styles.item, danger && styles.danger)}
      disabled={disabled}
      onSelect={onSelect}
    >
      {icon}
      {children}
    </RadixMenu.Item>
  );
}

export function MenuSeparator() {
  return <RadixMenu.Separator className={styles.separator} />;
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <RadixMenu.Label className={styles.label}>{children}</RadixMenu.Label>;
}
