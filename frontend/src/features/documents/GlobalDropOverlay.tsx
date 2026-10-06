import { Upload } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useUploadFiles } from './useUploadFiles';
import styles from './GlobalDropOverlay.module.css';

const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');

/** Lets users drop files anywhere in the app, not just on the dropzone. */
export function GlobalDropOverlay() {
  const [active, setActive] = useState(false);
  const depth = useRef(0);
  const uploadFiles = useUploadFiles();

  useEffect(() => {
    const onEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current += 1;
      setActive(true);
    };
    const onLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    };
    const onOver = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setActive(false);
      uploadFiles(Array.from(e.dataTransfer?.files ?? []));
    };
    window.addEventListener('dragenter', onEnter);
    window.addEventListener('dragleave', onLeave);
    window.addEventListener('dragover', onOver);
    window.addEventListener('drop', onDrop);
    return () => {
      window.removeEventListener('dragenter', onEnter);
      window.removeEventListener('dragleave', onLeave);
      window.removeEventListener('dragover', onOver);
      window.removeEventListener('drop', onDrop);
    };
  }, [uploadFiles]);

  if (!active) return null;
  return (
    <div className={styles.overlay} aria-hidden>
      <div className={styles.target}>
        <Upload size={28} />
        <p className={styles.title}>Drop to upload</p>
        <p className={styles.hint}>PDF or Word documents, up to 25 MB each</p>
      </div>
    </div>
  );
}
