import { useCallback } from 'react';
import { toast } from 'sonner';
import { useUploadDocument } from '@/hooks/queries';
import { validateFile } from '@/lib/files';
import { useUiStore } from '@/store/uiStore';

/** Validates files client-side, uploads the valid ones and reveals the library. */
export function useUploadFiles() {
  const upload = useUploadDocument();

  return useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const ui = useUiStore.getState();
      ui.setPanelTab('library');
      for (const file of files) {
        const problem = validateFile(file);
        if (problem) {
          toast.error('Can’t upload this file', { description: problem });
          continue;
        }
        upload.mutate(file);
      }
      ui.announce(`Uploading ${files.length === 1 ? files[0]!.name : `${files.length} files`}.`);
    },
    [upload],
  );
}
