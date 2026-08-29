import {
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query'
import {
  Database,
  FolderTree,
  ListChecks,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from 'react'
import { I18nextProvider } from 'react-i18next'

import { openVikingApi } from './api'
import {
  AppConnectionProvider,
  type OpenVikingProfile,
} from './hooks/use-app-connection'
import i18n from './i18n'
import { registerOpenVikingRoot } from './lib/ov-client/client'
import { FindPalette } from './routes/resources/-components/find-palette'
import {
  AddResourceForm,
  ResourceUploadProvider,
} from './routes/resources/resource-upload'
import { RetrievalPage } from './routes/retrieval/route'
import { TasksRoute } from './routes/tasks/route'
import { WatchesRoute } from './routes/watches/route'
import './openviking.css'

type Tab = 'resources' | 'retrieval' | 'tasks' | 'watches'

const TABS: Array<{ id: Tab; label: string; icon: typeof FolderTree }> = [
  { id: 'resources', label: 'Resources', icon: FolderTree },
  { id: 'retrieval', label: 'Retrieval', icon: Search },
  { id: 'tasks', label: 'Tasks', icon: ListChecks },
  { id: 'watches', label: 'Watches', icon: Database },
]

const queryClient = new QueryClient()

function ProfileForm({
  onCreated,
}: {
  onCreated: (profile: OpenVikingProfile) => void
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPending(true)
    setError('')
    const fields = new FormData(event.currentTarget)
    try {
      const profile = await openVikingApi.createProfile({
        display_name: String(fields.get('display_name') || ''),
        base_url: String(fields.get('base_url') || ''),
        api_key: String(fields.get('api_key') || ''),
        workspace_uri: String(fields.get('workspace_uri') || ''),
      })
      onCreated(await openVikingApi.validateProfile(profile.profile_id))
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Connection failed')
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="ov-profile-form" onSubmit={submit}>
      <div className="ov-profile-heading">
        <ShieldCheck aria-hidden="true" />
        <div>
          <h2>Connect OpenViking</h2>
          <p>Credentials are encrypted and used only by the AgentKit server.</p>
        </div>
      </div>
      <label>
        Name
        <input name="display_name" required defaultValue="OpenViking" />
      </label>
      <label>
        Base URL
        <input
          name="base_url"
          required
          type="url"
          placeholder="https://openviking.example.com"
        />
      </label>
      <label>
        API key
        <input name="api_key" required type="password" autoComplete="off" />
      </label>
      <label>
        Workspace URI
        <input
          name="workspace_uri"
          required
          defaultValue="viking://resources/"
        />
      </label>
      {error ? <p className="ov-form-error">{error}</p> : null}
      <button className="ov-primary-button" disabled={pending} type="submit">
        {pending ? 'Validating...' : 'Connect'}
      </button>
    </form>
  )
}

function ResourceWorkspace() {
  const [paletteOpen, setPaletteOpen] = useState(true)
  const [addOpen, setAddOpen] = useState(false)
  const [scopeUri, setScopeUri] = useState('viking://workspace/')

  useEffect(() => {
    const open = () => setAddOpen(true)
    window.addEventListener('openviking:add-resource', open)
    return () => window.removeEventListener('openviking:add-resource', open)
  }, [])

  return (
    <ResourceUploadProvider>
      <div className="ov-resource-toolbar">
        <button type="button" onClick={() => setPaletteOpen(true)}>
          <Search aria-hidden="true" /> Browse
        </button>
        <button type="button" onClick={() => setAddOpen(true)}>
          <Plus aria-hidden="true" /> Import
        </button>
      </div>
      <div className="ov-resource-stage">
        <FindPalette
          open={paletteOpen}
          scopeUri={scopeUri}
          onClose={() => setPaletteOpen(false)}
          onNavigate={() => setPaletteOpen(true)}
          onNavigateDir={(uri) => {
            setScopeUri(uri)
            setPaletteOpen(true)
          }}
        />
      </div>
      {addOpen ? (
        <div className="ov-modal-backdrop" role="presentation">
          <section className="ov-modal" role="dialog" aria-modal="true">
            <header>
              <h2>Import resource</h2>
              <button type="button" onClick={() => setAddOpen(false)}>
                Close
              </button>
            </header>
            <AddResourceForm onCompleted={() => setAddOpen(false)} />
          </section>
        </div>
      ) : null}
    </ResourceUploadProvider>
  )
}

export function OpenVikingWorkspace() {
  const [profiles, setProfiles] = useState<OpenVikingProfile[]>([])
  const [activeId, setActiveId] = useState('')
  const [tab, setTab] = useState<Tab>('resources')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const activeProfile = useMemo(
    () => profiles.find((profile) => profile.profile_id === activeId) ?? null,
    [activeId, profiles],
  )
  useEffect(() => {
    if (activeProfile) {
      registerOpenVikingRoot(
        activeProfile.workspace_uri,
        activeProfile.root_resource_ref,
      )
      registerOpenVikingRoot('viking://', activeProfile.root_resource_ref)
      registerOpenVikingRoot(
        'viking://resources/',
        activeProfile.root_resource_ref,
      )
    }
  }, [activeProfile])
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const values = await openVikingApi.listProfiles()
      setProfiles(values)
      setActiveId((current) =>
        values.some((item) => item.profile_id === current)
          ? current
          : (values[0]?.profile_id ?? ''),
      )
    } catch (value) {
      setError(value instanceof Error ? value.message : 'Unable to load profiles')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) return <div className="ov-empty">Loading OpenViking...</div>
  if (!activeProfile) {
    return (
      <div className="ov-connect-page">
        {error ? <p className="ov-form-error">{error}</p> : null}
        <ProfileForm
          onCreated={(profile) => {
            setProfiles((current) => [...current, profile])
            setActiveId(profile.profile_id)
          }}
        />
      </div>
    )
  }

  return (
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <AppConnectionProvider profile={activeProfile}>
          <div className="ov-workspace">
            <header className="ov-header">
              <div>
                <h1>OpenViking</h1>
                <span>{activeProfile.display_name}</span>
              </div>
              <div className="ov-profile-actions">
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
                <button
                  aria-label="Revoke profile"
                  title="Revoke profile"
                  type="button"
                  onClick={async () => {
                    await openVikingApi.revokeProfile(activeProfile.profile_id)
                    await load()
                  }}
                >
                  <Trash2 aria-hidden="true" />
                </button>
              </div>
            </header>
            <nav className="ov-tabs" aria-label="OpenViking workspace">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  className={tab === id ? 'active' : ''}
                  key={id}
                  onClick={() => setTab(id)}
                  type="button"
                >
                  <Icon aria-hidden="true" />
                  {label}
                </button>
              ))}
            </nav>
            <main className="ov-content">
              {tab === 'resources' ? <ResourceWorkspace /> : null}
              {tab === 'retrieval' ? <RetrievalPage /> : null}
              {tab === 'tasks' ? <TasksRoute /> : null}
              {tab === 'watches' ? <WatchesRoute /> : null}
            </main>
          </div>
        </AppConnectionProvider>
      </QueryClientProvider>
    </I18nextProvider>
  )
}
