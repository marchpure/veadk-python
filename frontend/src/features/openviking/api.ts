import { withAuth } from '../../adk/auth'
import { withLocalUser } from '../../adk/identity'
import type { OpenVikingProfile } from './hooks/use-app-connection'
import { getActiveOpenVikingProfileId } from './hooks/use-app-connection'
import { getOpenVikingResourceRef } from './lib/ov-client/client'

const ROOT = '/api/knowledge/v1/openviking'

type Envelope<T> = { data: T; meta: { request_id: string } }
export type ConnectionResource = {
  resource_id: string
  kind: string
  display_name: string
  status: string
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = withLocalUser(new Headers(init.headers))
  if (init.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(withAuth(`${ROOT}${path}`), { ...init, headers })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(
      payload?.error?.message ??
        payload?.detail?.message ??
        `OpenViking request failed (${response.status})`,
    )
  }
  if (response.status === 204) return undefined as T
  const envelope = (await response.json()) as Envelope<T>
  return envelope.data
}

async function knowledgeRequest<T>(path: string): Promise<T> {
  const headers = withLocalUser(new Headers())
  const response = await fetch(withAuth(`/api/knowledge/v1${path}`), { headers })
  if (!response.ok) throw new Error(`Knowledge request failed (${response.status})`)
  return ((await response.json()) as Envelope<T>).data
}

function activeProfilePath(suffix: string): string {
  const profileId = getActiveOpenVikingProfileId()
  if (!profileId) throw new Error('Select an OpenViking profile first')
  return `/profiles/${encodeURIComponent(profileId)}${suffix}`
}

function parentRef(uri: string): string {
  const ref = getOpenVikingResourceRef(uri)
  if (!ref) throw new Error('Refresh the OpenViking directory before importing')
  return ref
}

type CreateOpenVikingProfile = {
  api_key: string
  base_url: string
  display_name: string
  workspace_uri: string
}

export const openVikingApi = {
  listProfiles: (signal?: AbortSignal) =>
    request<OpenVikingProfile[]>('/profiles', { signal }),
  createProfile: (input: CreateOpenVikingProfile) =>
    request<OpenVikingProfile>('/profiles', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  validateProfile: (profileId: string) =>
    request<OpenVikingProfile>(
      `/profiles/${encodeURIComponent(profileId)}/validate`,
      { method: 'POST' },
    ),
  revokeProfile: (profileId: string) =>
    request<void>(`/profiles/${encodeURIComponent(profileId)}`, {
      method: 'DELETE',
    }),
  importText: (input: { parent_uri: string; filename: string; content: string }) =>
    request<unknown>(activeProfilePath('/text'), {
      method: 'POST',
      body: JSON.stringify({
        parent_ref: parentRef(input.parent_uri),
        filename: input.filename,
        content: input.content,
      }),
    }),
  importConnectionResource: (input: {
    parent_uri: string
    filename: string
    resource_id: string
  }) =>
    request<unknown>(activeProfilePath('/connection-resource'), {
      method: 'POST',
      body: JSON.stringify({
        parent_ref: parentRef(input.parent_uri),
        filename: input.filename,
        resource_id: input.resource_id,
      }),
    }),
  listConnectionResources: () =>
    knowledgeRequest<ConnectionResource[]>('/resources'),
}
