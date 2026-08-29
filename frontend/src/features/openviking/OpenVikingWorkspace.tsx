import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type SVGProps,
} from 'react'
import { I18nextProvider } from 'react-i18next'
import { Toaster } from 'sonner'

import { Navbar } from '../../ui/Navbar'
import { Sidebar } from '../../ui/Sidebar'
import { openVikingApi } from './api'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from './components/ui/dialog'
import {
  AppConnectionProvider,
  type OpenVikingProfile,
} from './hooks/use-app-connection'
import i18n from './i18n'
import { registerOpenVikingRoot } from './lib/ov-client/client'
import { ResourceContextTree } from './routes/resources/-components/context-tree'
import { FindPalette } from './routes/resources/-components/find-palette'
import { LazyFilePreview } from './routes/resources/-components/lazy-file-preview'
import { useInvalidateVikingFs } from './routes/resources/-hooks/viking-fm'
import { fetchFsStat } from './routes/resources/-lib/api'
import {
  fileNameFromUri,
  normalizeDirUri,
  parentUri,
} from './routes/resources/-lib/normalize'
import type { VikingFsEntry } from './routes/resources/-types/viking-fm'
import {
  AddResourceForm,
  ResourceUploadProvider,
} from './routes/resources/resource-upload'
import { RetrievalPage } from './routes/retrieval/route'
import { TasksRoute } from './routes/tasks/route'
import { WatchesRoute } from './routes/watches/route'
import './openviking.css'

type OpenVikingPage =
  | 'resources'
  | 'retrieval'
  | 'tasks'
  | 'watches'
  | 'connection'

const CANONICAL_BASE_URL =
  'https://api.vikingdb.cn-beijing.volces.com/openviking'
const OPENVIKING_BRANDING = { logoUrl: '', title: 'OpenViking' }
const queryClient = new QueryClient()

function ResourcesIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M3 4.25h5l1.45 1.6H17v9.9H3V4.25Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.45" />
      <path d="M6.25 9h7.5M6.25 12h5" stroke="currentColor" strokeLinecap="round" strokeWidth="1.3" />
    </svg>
  )
}

function RetrievalIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <circle cx="8.6" cy="8.6" r="4.85" stroke="currentColor" strokeWidth="1.45" />
      <path d="m12.25 12.25 4 4" stroke="currentColor" strokeLinecap="round" strokeWidth="1.45" />
    </svg>
  )
}

function TasksIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <rect x="4" y="3" width="12" height="14" rx="1.5" stroke="currentColor" strokeWidth="1.4" />
      <path d="m6.8 8 1 1 1.8-2M11 8h2.5m-6.7 4.25 1 1 1.8-2M11 12.25h2.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.25" />
    </svg>
  )
}

function WatchesIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M15.5 7.2A6.1 6.1 0 1 0 16 12" stroke="currentColor" strokeLinecap="round" strokeWidth="1.45" />
      <path d="M15.5 3.5v3.7h-3.7M10 6.5v4l2.65 1.55" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.35" />
    </svg>
  )
}

function ConnectionIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M7.5 6.75 5.25 9a3 3 0 0 0 4.25 4.25l1.25-1.25m1.75 1.25L14.75 11A3 3 0 0 0 10.5 6.75L9.25 8" stroke="currentColor" strokeLinecap="round" strokeWidth="1.45" />
    </svg>
  )
}

function SearchIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <circle cx="8.6" cy="8.6" r="4.6" stroke="currentColor" strokeWidth="1.45" />
      <path d="m12.1 12.1 3.8 3.8" stroke="currentColor" strokeLinecap="round" strokeWidth="1.45" />
    </svg>
  )
}

function AddIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M10 4v12M4 10h12" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" />
    </svg>
  )
}

function RefreshIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M15.6 7.1A6 6 0 1 0 16 12" stroke="currentColor" strokeLinecap="round" strokeWidth="1.45" />
      <path d="M15.6 3.7v3.4h-3.4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.45" />
    </svg>
  )
}

function DeleteIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M4.5 6h11M8 3.75h4M6.25 6l.65 10.25h6.2L13.75 6M8.25 8.5v5.25m3.5-5.25v5.25" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.35" />
    </svg>
  )
}

function ShieldIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M10 2.75 16 5v4.4c0 3.7-2.25 6.25-6 7.85-3.75-1.6-6-4.15-6-7.85V5l6-2.25Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.4" />
      <path d="m7.25 9.9 1.75 1.75 3.75-4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.4" />
    </svg>
  )
}

function rootEntry(uri: string): VikingFsEntry {
  return {
    uri,
    name: fileNameFromUri(uri) || 'OpenViking',
    isDir: true,
    size: '',
    sizeBytes: null,
    modTime: '',
    modTimestamp: null,
    abstract: '',
    overview: '',
  }
}

function expandedAncestors(uri: string, rootUri: string): Set<string> {
  const root = normalizeDirUri(rootUri)
  const values = new Set<string>()
  let current = parentUri(uri)
  while (current.startsWith(root) && current !== root) {
    values.add(current)
    const next = parentUri(current)
    if (next === current) break
    current = next
  }
  return values
}

function ProfileForm({
  onCreated,
}: {
  onCreated: (profile: OpenVikingProfile) => void
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    setPending(true)
    setError('')
    const fields = new FormData(form)
    try {
      const profile = await openVikingApi.createProfile({
        display_name: String(fields.get('display_name') || ''),
        base_url: String(fields.get('base_url') || ''),
        api_key: String(fields.get('api_key') || ''),
        workspace_uri: String(fields.get('workspace_uri') || ''),
      })
      onCreated(await openVikingApi.validateProfile(profile.profile_id))
      form.reset()
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Connection failed')
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="ov-profile-form" onSubmit={submit}>
      <div className="ov-profile-heading">
        <span className="ov-profile-heading-icon"><ShieldIcon /></span>
        <div>
          <h2>Add connection</h2>
          <p>The API key is encrypted by the AgentKit server.</p>
        </div>
      </div>
      <div className="ov-form-grid">
        <label>
          Name
          <input name="display_name" required defaultValue="OpenViking" />
        </label>
        <label>
          Workspace URI
          <input name="workspace_uri" required defaultValue="viking://resources/" />
        </label>
      </div>
      <label>
        Base URL
        <input
          name="base_url"
          required
          type="url"
          defaultValue={CANONICAL_BASE_URL}
        />
      </label>
      <label>
        API key
        <input name="api_key" required type="password" autoComplete="off" />
      </label>
      {error ? <p className="ov-form-error" role="alert">{error}</p> : null}
      <div className="ov-form-actions">
        <button className="ov-primary-button" disabled={pending} type="submit">
          {pending ? 'Validating...' : 'Connect'}
        </button>
      </div>
    </form>
  )
}

function ConnectionPage({
  activeProfile,
  onCreated,
  onRevoke,
}: {
  activeProfile: OpenVikingProfile | null
  onCreated: (profile: OpenVikingProfile) => void
  onRevoke: (profile: OpenVikingProfile) => void
}) {
  return (
    <div className="ov-connection-page">
      <header className="ov-page-heading">
        <p className="ov-eyebrow">Settings</p>
        <h1>Connection</h1>
      </header>
      {activeProfile ? (
        <section className="ov-active-connection" aria-label="Active connection">
          <div>
            <span className="ov-connection-state"><span /> Connected</span>
            <h2>{activeProfile.display_name}</h2>
            <p>{activeProfile.workspace_uri}</p>
          </div>
          <button
            className="ov-danger-button"
            type="button"
            onClick={() => onRevoke(activeProfile)}
          >
            <DeleteIcon />
            Revoke
          </button>
        </section>
      ) : null}
      <ProfileForm onCreated={onCreated} />
    </div>
  )
}

function ResourceWorkspace({ rootUri }: { rootUri: string }) {
  const normalizedRoot = normalizeDirUri(rootUri)
  const [searchOpen, setSearchOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [selectedFile, setSelectedFile] = useState<VikingFsEntry>(() =>
    rootEntry(normalizedRoot),
  )
  const [expandedUris, setExpandedUris] = useState<Set<string>>(new Set())
  const { invalidateList, invalidatePreview } = useInvalidateVikingFs()

  useEffect(() => {
    setSelectedFile(rootEntry(normalizedRoot))
    setExpandedUris(new Set())
  }, [normalizedRoot])

  useEffect(() => {
    const open = () => setAddOpen(true)
    window.addEventListener('openviking:add-resource', open)
    return () => window.removeEventListener('openviking:add-resource', open)
  }, [])

  const openUri = useCallback(
    async (uri: string) => {
      const entry = await fetchFsStat(uri, { throwOnError: true })
      setSelectedFile(entry)
      setExpandedUris((current) => {
        const next = new Set(current)
        for (const ancestor of expandedAncestors(entry.uri, normalizedRoot)) {
          next.add(ancestor)
        }
        if (entry.isDir) next.add(normalizeDirUri(entry.uri))
        return next
      })
    },
    [normalizedRoot],
  )

  const refresh = useCallback(async () => {
    await Promise.all([
      invalidateList(),
      invalidatePreview(selectedFile.uri),
    ])
  }, [invalidateList, invalidatePreview, selectedFile.uri])

  return (
    <ResourceUploadProvider>
      <div className="ov-resource-workbench">
        <section
          className="ov-context-explorer"
          aria-label="OpenViking context tree"
        >
          <header className="ov-context-header">
            <div className="ov-context-title">
              <span className="ov-context-glyph"><ResourcesIcon /></span>
              <span>Context tree</span>
            </div>
            <div className="ov-icon-actions">
              <button type="button" title="Search resources" aria-label="Search resources" onClick={() => setSearchOpen(true)}>
                <SearchIcon />
              </button>
              <button type="button" title="Import resource" aria-label="Import resource" onClick={() => setAddOpen(true)}>
                <AddIcon />
              </button>
              <button type="button" title="Refresh resources" aria-label="Refresh resources" onClick={() => void refresh()}>
                <RefreshIcon />
              </button>
            </div>
          </header>
          <div className="ov-context-scope" title={normalizedRoot}>{normalizedRoot}</div>
          <div className="ov-context-tree-scroll">
            <ResourceContextTree
              expandedUris={expandedUris}
              onExpandedUrisChange={setExpandedUris}
              onSelect={setSelectedFile}
              rootUri={normalizedRoot}
              selectedUri={selectedFile.uri}
            />
          </div>
        </section>
        <section className="ov-resource-preview" aria-label="Resource preview">
          <LazyFilePreview
            file={selectedFile}
            onClose={() => setSelectedFile(rootEntry(normalizedRoot))}
            onNavigate={(uri) => void openUri(uri)}
            showCloseButton={false}
          />
        </section>
      </div>
      <FindPalette
        open={searchOpen}
        scopeUri={normalizedRoot}
        onClose={() => setSearchOpen(false)}
        onNavigate={(uri) => void openUri(uri)}
        onNavigateDir={(uri) => void openUri(uri)}
      />
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="ov-import-dialog sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Import resource</DialogTitle>
            <DialogDescription>Add files, text, remote sources, or connected resources.</DialogDescription>
          </DialogHeader>
          <AddResourceForm
            onCompleted={() => {
              setAddOpen(false)
              void refresh()
            }}
          />
        </DialogContent>
      </Dialog>
    </ResourceUploadProvider>
  )
}

export function OpenVikingWorkspace() {
  const [profiles, setProfiles] = useState<OpenVikingProfile[]>([])
  const [activeId, setActiveId] = useState('')
  const [page, setPage] = useState<OpenVikingPage>('resources')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const activeProfile = useMemo(
    () => profiles.find((profile) => profile.profile_id === activeId) ?? null,
    [activeId, profiles],
  )

  useEffect(() => {
    if (!activeProfile) return
    registerOpenVikingRoot(
      activeProfile.workspace_uri,
      activeProfile.root_resource_ref,
    )
    registerOpenVikingRoot('viking://', activeProfile.root_resource_ref)
    registerOpenVikingRoot('viking://resources/', activeProfile.root_resource_ref)
  }, [activeProfile])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const values = await openVikingApi.listProfiles()
      setProfiles(values)
      setActiveId((current) =>
        values.some((item) => item.profile_id === current)
          ? current
          : (values[0]?.profile_id ?? ''),
      )
      if (values.length === 0) setPage('connection')
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Unable to load profiles')
      setPage('connection')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const handleCreated = useCallback((profile: OpenVikingProfile) => {
    setProfiles((current) => [
      profile,
      ...current.filter((item) => item.profile_id !== profile.profile_id),
    ])
    setActiveId(profile.profile_id)
    setPage('resources')
  }, [])

  const handleRevoke = useCallback(async (profile: OpenVikingProfile) => {
    if (!window.confirm(`Revoke ${profile.display_name}?`)) return
    await openVikingApi.revokeProfile(profile.profile_id)
    await load()
  }, [load])

  const pageLabel = page[0].toUpperCase() + page.slice(1)
  const canUseWorkspace = Boolean(activeProfile)
  const showWorkspaceRequired = page !== 'connection' && !canUseWorkspace

  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <AppConnectionProvider profile={activeProfile}>
          <div className="layout openviking-studio">
            <Sidebar
              branding={OPENVIKING_BRANDING}
              cloudProvider="volcengine"
              contextNavigation={{
                activeId: page,
                onBrandClick: () => setPage('resources'),
                items: [
                  { id: 'resources', label: 'Resources', icon: ResourcesIcon, onSelect: () => setPage('resources') },
                  { id: 'retrieval', label: 'Retrieval', icon: RetrievalIcon, onSelect: () => setPage('retrieval') },
                  { id: 'tasks', label: 'Tasks', icon: TasksIcon, onSelect: () => setPage('tasks') },
                  { id: 'watches', label: 'Watches', icon: WatchesIcon, onSelect: () => setPage('watches') },
                  { id: 'connection', label: 'Connection', icon: ConnectionIcon, onSelect: () => setPage('connection') },
                ],
                footer: activeProfile ? (
                  <button className="ov-sidebar-connection" type="button" onClick={() => setPage('connection')} title={activeProfile.display_name}>
                    <span className="ov-sidebar-status" />
                    <span className="ov-sidebar-profile">
                      <strong>{activeProfile.display_name}</strong>
                      <span>{activeProfile.status}</span>
                    </span>
                  </button>
                ) : null,
              }}
            />
            <section className="main-shell">
              <main className="main openviking-main">
                <Navbar
                  appName=""
                  onAppChange={() => {}}
                  agentsSource="local"
                  localApps={[]}
                  runtimeScope="mine"
                  crumbs={[
                    { label: 'OpenViking', onClick: () => setPage('resources') },
                    { label: pageLabel },
                  ]}
                  rightContent={activeProfile ? (
                    <div className="ov-navbar-profile">
                      <span className="ov-navbar-status" title={activeProfile.status} />
                      <select
                        aria-label="OpenViking profile"
                        value={activeId}
                        onChange={(event) => setActiveId(event.target.value)}
                      >
                        {profiles.map((profile) => (
                          <option key={profile.profile_id} value={profile.profile_id}>
                            {profile.display_name}
                          </option>
                        ))}
                      </select>
                    </div>
                  ) : null}
                />
                {error ? <div className="error" role="alert">{error}</div> : null}
                {loading ? (
                  <div className="ov-loading" role="status">Loading OpenViking...</div>
                ) : showWorkspaceRequired ? (
                  <div className="ov-disconnected">
                    <ConnectionIcon />
                    <h1>Connect OpenViking</h1>
                    <button type="button" onClick={() => setPage('connection')}>Open connection settings</button>
                  </div>
                ) : page === 'resources' && activeProfile ? (
                  <ResourceWorkspace rootUri={activeProfile.workspace_uri} />
                ) : page === 'retrieval' ? (
                  <div className="ov-page-scroll"><div className="ov-page-content"><RetrievalPage /></div></div>
                ) : page === 'tasks' ? (
                  <div className="ov-page-scroll"><div className="ov-page-content"><TasksRoute /></div></div>
                ) : page === 'watches' ? (
                  <div className="ov-page-scroll"><div className="ov-page-content"><WatchesRoute /></div></div>
                ) : (
                  <div className="ov-page-scroll">
                    <ConnectionPage
                      activeProfile={activeProfile}
                      onCreated={handleCreated}
                      onRevoke={(profile) => void handleRevoke(profile)}
                    />
                  </div>
                )}
              </main>
            </section>
          </div>
          <Toaster richColors position="bottom-right" />
        </AppConnectionProvider>
      </QueryClientProvider>
    </I18nextProvider>
  )
}
