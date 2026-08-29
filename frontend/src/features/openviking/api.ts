import { withAuth } from '../../adk/auth'
import { withLocalUser } from '../../adk/identity'
import type { OpenVikingProfile } from './hooks/use-app-connection'

const ROOT = '/api/knowledge/v1/openviking'

type Envelope<T> = { data: T; meta: { request_id: string } }

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

export type CreateOpenVikingProfile = {
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
}
