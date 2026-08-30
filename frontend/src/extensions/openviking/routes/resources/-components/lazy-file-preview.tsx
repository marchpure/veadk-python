import type { VikingFsEntry } from '../-types/viking-fm'
import { FilePreview } from './file-preview'

export function LazyFilePreview({
  file,
  hideDirectoryHeader,
  onClose,
  onNavigate,
  showCloseButton,
}: {
  file: VikingFsEntry | null
  hideDirectoryHeader?: boolean
  onClose: () => void
  onNavigate?: (uri: string) => void
  showCloseButton?: boolean
}) {
  return (
    <FilePreview
      file={file}
      hideDirectoryHeader={hideDirectoryHeader}
      onClose={onClose}
      onNavigate={onNavigate}
      showCloseButton={showCloseButton}
    />
  )
}
