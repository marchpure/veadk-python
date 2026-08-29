import axios, { AxiosHeaders } from 'axios'
import type { AxiosRequestConfig } from 'axios'
import { afterEach, describe, expect, it } from 'vitest'

import { getContentRead, getFsLs, getFsStat } from '#/gen/ov-client'
import { setActiveOpenVikingProfileId } from '#/hooks/use-app-connection'
import { createOvClient, registerOpenVikingRoot } from './client'

function createRecordingClient() {
  const requests: AxiosRequestConfig[] = []
  const instance = axios.create({
    adapter: async (config) => {
      requests.push(config)
      return {
        config,
        data: { data: { result: {} }, meta: { request_id: 'request-1' } },
        headers: {},
        status: 200,
        statusText: 'OK',
      }
    },
  })
  return {
    client: createOvClient({ axios: instance, bindSdkClient: false }),
    requests,
  }
}

afterEach(() => setActiveOpenVikingProfileId(''))

describe('createOvClient AgentKit BFF boundary', () => {
  it('rewrites an allowlisted call and strips browser credentials', async () => {
    setActiveOpenVikingProfileId('ovp_profile')
    registerOpenVikingRoot('viking://workspace/', 'ovr_signed-root')
    const { client, requests } = createRecordingClient()

    await client.instance.get('/api/v1/fs/ls', {
      headers: {
        'X-API-Key': 'must-not-leak',
        'X-OpenViking-Account': 'account-a',
      },
      params: { uri: 'viking://workspace/' },
    })

    const request = requests[0]
    const headers =
      request.headers instanceof AxiosHeaders
        ? request.headers
        : new AxiosHeaders(request.headers as Record<string, string>)
    expect(request.url).toBe(
      '/api/knowledge/v1/openviking/profiles/ovp_profile/operations/fs_list',
    )
    expect(request.method).toBe('POST')
    expect(headers.has('X-API-Key')).toBe(false)
    expect(headers.has('X-OpenViking-Account')).toBe(false)
    expect(request.data).toBe(
      JSON.stringify({ payload: { resource_ref: 'ovr_signed-root' } }),
    )
  })

  it('converts generated SDK URL queries into opaque BFF resource refs', async () => {
    setActiveOpenVikingProfileId('ovp_profile')
    registerOpenVikingRoot(
      'viking://workspace/stat.md',
      'ovr_preview-stat-resource',
    )
    registerOpenVikingRoot(
      'viking://workspace/read.md',
      'ovr_preview-read-resource',
    )
    const { client, requests } = createRecordingClient()

    await getFsStat({
      client: client.client,
      query: { uri: 'viking://workspace/stat.md' },
    })
    await getContentRead({
      client: client.client,
      query: {
        limit: 50,
        offset: 10,
        raw: true,
        uri: 'viking://workspace/read.md',
      } as Parameters<typeof getContentRead>[0]['query'] & { raw: boolean },
    })

    expect(requests[0].url).toBe(
      '/api/knowledge/v1/openviking/profiles/ovp_profile/operations/fs_stat',
    )
    expect(requests[0].data).toBe(
      JSON.stringify({
        payload: { resource_ref: 'ovr_preview-stat-resource' },
      }),
    )
    expect(requests[1].url).toBe(
      '/api/knowledge/v1/openviking/profiles/ovp_profile/operations/content_read',
    )
    expect(requests[1].data).toBe(
      JSON.stringify({
        payload: {
          limit: 50,
          offset: 10,
          raw: true,
          resource_ref: 'ovr_preview-read-resource',
        },
      }),
    )
    for (const request of requests) {
      expect(request.url).not.toContain('?')
      expect(request.params).toBeUndefined()
      expect(request.data).not.toContain('viking://')
    }
  })

  it('preserves generated SDK query booleans and integers for the BFF', async () => {
    setActiveOpenVikingProfileId('ovp_profile')
    registerOpenVikingRoot('viking://workspace/', 'ovr_typed-root')
    const { client, requests } = createRecordingClient()

    await getFsLs({
      client: client.client,
      query: {
        limit: 50,
        show_all_hidden: true,
        uri: 'viking://workspace/',
      },
    })

    expect(requests[0].data).toBe(
      JSON.stringify({
        payload: {
          limit: 50,
          show_all_hidden: true,
          resource_ref: 'ovr_typed-root',
        },
      }),
    )
  })

  it('rejects paths that are not on the operation allowlist', async () => {
    setActiveOpenVikingProfileId('ovp_profile')
    const { client } = createRecordingClient()

    await expect(client.instance.get('/api/v1/admin/accounts')).rejects.toMatchObject({
      code: 'OPERATION_NOT_ALLOWED',
    })
  })

  it('retries a task only after its resource URI has an opaque BFF ref', async () => {
    setActiveOpenVikingProfileId('ovp_profile')
    const { client, requests } = createRecordingClient()

    await expect(
      client.instance.post('/api/v1/content/reindex', {
        uri: 'viking://workspace/missing.md',
        wait: false,
      }),
    ).rejects.toMatchObject({
      code: 'OPENVIKING_RESOURCE_REF_REQUIRED',
    })

    registerOpenVikingRoot('viking://workspace/missing.md', 'ovr_task-resource')
    await client.instance.post('/api/v1/content/reindex', {
      uri: 'viking://workspace/missing.md',
      wait: false,
    })

    expect(requests[0].data).toBe(
      JSON.stringify({
        payload: { resource_ref: 'ovr_task-resource', wait: false },
      }),
    )
  })

  it('routes session commit retry through the scoped BFF without credentials', async () => {
    setActiveOpenVikingProfileId('ovp_profile')
    const { client, requests } = createRecordingClient()

    await client.instance.post(
      '/api/v1/sessions/session_123/commit',
      { keep_recent_count: 3 },
      { headers: { 'X-API-Key': 'must-not-leak' } },
    )

    const request = requests[0]
    const headers =
      request.headers instanceof AxiosHeaders
        ? request.headers
        : new AxiosHeaders(request.headers as Record<string, string>)
    expect(request.url).toBe(
      '/api/knowledge/v1/openviking/profiles/ovp_profile/operations/session_commit/session_123',
    )
    expect(headers.has('X-API-Key')).toBe(false)
    expect(request.data).toBe(
      JSON.stringify({ payload: { keep_recent_count: 3 } }),
    )
  })

  it('requires an opaque profile before every request', async () => {
    const { client } = createRecordingClient()

    await expect(client.instance.get('/api/v1/fs/ls')).rejects.toMatchObject({
      code: 'OPENVIKING_PROFILE_REQUIRED',
    })
  })
})
