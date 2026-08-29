import { useMemo, type SVGProps } from 'react'

import { useVikingFsList } from '../-hooks/viking-fm'
import type { VikingFsEntry } from '../-types/viking-fm'

const LIST_OPTIONS = {
  output: 'agent' as const,
  showAllHidden: true,
  nodeLimit: 500,
  sortBy: 'name' as const,
  sortOrder: 'asc' as const,
}

function ChevronIcon({ open, ...props }: SVGProps<SVGSVGElement> & { open: boolean }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" {...props}>
      <path
        d="m6 3.5 4.5 4.5L6 12.5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.4"
        transform={open ? 'rotate(90 8 8)' : undefined}
      />
    </svg>
  )
}

function FolderIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path
        d="M2.75 5.4c0-.91.74-1.65 1.65-1.65h3.05l1.5 1.75h6.65c.91 0 1.65.74 1.65 1.65v7.45c0 .91-.74 1.65-1.65 1.65H4.4c-.91 0-1.65-.74-1.65-1.65V5.4Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.35"
      />
    </svg>
  )
}

function FileIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path
        d="M5 2.75h6l4 4v10.5H5V2.75Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.35"
      />
      <path d="M11 2.75v4h4" stroke="currentColor" strokeWidth="1.35" />
      <path d="M7.5 10h5M7.5 12.75h5" stroke="currentColor" strokeLinecap="round" strokeWidth="1.15" />
    </svg>
  )
}

function sortEntries(entries: VikingFsEntry[]): VikingFsEntry[] {
  return [...entries].sort(
    (left, right) =>
      Number(right.isDir) - Number(left.isDir) ||
      left.name.localeCompare(right.name),
  )
}

function TreeLevel({
  depth,
  expandedUris,
  onExpandedUrisChange,
  onSelect,
  selectedUri,
  uri,
}: {
  depth: number
  expandedUris: Set<string>
  onExpandedUrisChange: (next: Set<string>) => void
  onSelect: (entry: VikingFsEntry) => void
  selectedUri: string
  uri: string
}) {
  const listQuery = useVikingFsList(uri, LIST_OPTIONS)
  const entries = useMemo(
    () => sortEntries(listQuery.data?.entries ?? []),
    [listQuery.data?.entries],
  )

  if (listQuery.isLoading) {
    return <div className="ov-tree-state">Loading...</div>
  }
  if (listQuery.isError) {
    const error = listQuery.error as {
      code?: string
      message?: string
      statusCode?: number
    }
    const message = error?.message || 'Unable to load this directory'
    const detail = error?.statusCode
      ? `${message} (${error.statusCode})`
      : message
    return (
      <div className="ov-tree-state ov-tree-state-error" role="alert">
        <span>{detail}</span>
        <button
          type="button"
          className="ov-tree-retry"
          onClick={() => void listQuery.refetch()}
        >
          Retry
        </button>
      </div>
    )
  }
  if (entries.length === 0) {
    return <div className="ov-tree-state">Empty directory</div>
  }

  return (
    <ul className="ov-tree-level" role={depth === 0 ? 'tree' : 'group'}>
      {entries.map((entry) => {
        const open = entry.isDir && expandedUris.has(entry.uri)
        const selected = entry.uri === selectedUri
        return (
          <li key={entry.uri} role="none">
            <button
              type="button"
              className={`ov-tree-row${selected ? ' is-selected' : ''}`}
              style={{ paddingLeft: `${8 + depth * 16}px` }}
              role="treeitem"
              aria-expanded={entry.isDir ? open : undefined}
              aria-selected={selected}
              title={entry.uri}
              onClick={() => {
                onSelect(entry)
                if (!entry.isDir) return
                const next = new Set(expandedUris)
                if (open) next.delete(entry.uri)
                else next.add(entry.uri)
                onExpandedUrisChange(next)
              }}
            >
              <span className="ov-tree-disclosure">
                {entry.isDir ? <ChevronIcon open={open} /> : null}
              </span>
              {entry.isDir ? (
                <FolderIcon className="ov-tree-kind" />
              ) : (
                <FileIcon className="ov-tree-kind" />
              )}
              <span className="ov-tree-name">{entry.name}</span>
            </button>
            {open ? (
              <TreeLevel
                depth={depth + 1}
                expandedUris={expandedUris}
                onExpandedUrisChange={onExpandedUrisChange}
                onSelect={onSelect}
                selectedUri={selectedUri}
                uri={entry.uri}
              />
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

export function ResourceContextTree({
  expandedUris,
  onExpandedUrisChange,
  onSelect,
  rootUri,
  selectedUri,
}: {
  expandedUris: Set<string>
  onExpandedUrisChange: (next: Set<string>) => void
  onSelect: (entry: VikingFsEntry) => void
  rootUri: string
  selectedUri: string
}) {
  return (
    <TreeLevel
      depth={0}
      expandedUris={expandedUris}
      onExpandedUrisChange={onExpandedUrisChange}
      onSelect={onSelect}
      selectedUri={selectedUri}
      uri={rootUri}
    />
  )
}
