import { LoaderCircle } from 'lucide-react';

export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  return (
    <LoaderCircle
      size={size}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? 'status' : undefined}
      style={{ animation: 'spin 0.9s linear infinite', flexShrink: 0 }}
    />
  );
}
