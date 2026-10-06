import { CircleAlert, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { useHealth } from '@/hooks/queries';
import styles from './ModelBanner.module.css';

/** Shown above the thread when the local model runtime can't be reached. */
export function ModelBanner() {
  const { data, isError, refetch, isFetching } = useHealth();
  const down = isError || data?.modelRuntime === 'unavailable';
  if (!down) return null;

  return (
    <div className={styles.banner} role="alert">
      <CircleAlert size={18} aria-hidden className={styles.icon} />
      <p className={styles.text}>
        <strong>The local model is unavailable.</strong> Legal Lens can’t generate answers until the
        model runtime is running. Your documents and conversations are still available.
      </p>
      <Button size="sm" icon={<RotateCcw size={14} />} loading={isFetching} onClick={() => void refetch()}>
        Check again
      </Button>
    </div>
  );
}
