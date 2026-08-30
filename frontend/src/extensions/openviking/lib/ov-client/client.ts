import axios, { AxiosHeaders } from 'axios'
import type { InternalAxiosRequestConfig } from 'axios'

import { withAuth } from '../../../../adk/auth'
import { withLocalUser } from '../../../../adk/identity'
import { createClient } from '#/gen/ov-client/client'
import { client as sdkClient } from '#/gen/ov-client/client.gen'

import { normalizeOvClientError, OvClientError } from './errors'
import { getActiveOpenVikingProfileId } from '#/hooks/use-app-connection'
import type {
  OvClientAdapter,
  OvClientOptions,
  OvErrorEnvelope,
} from './types'

const DEFAULT_TELEMETRY_PATHS = new Set([
  '/api/v1/search/find',
  '/api/v1/search/search',
  '/api/v1/resources',
])
const SESSION_COMMIT_PATH = /^\/api\/v1\/sessions\/[^/]+\/commit$/
const BFF_ROOT = '/api/knowledge/v1/openviking'
const resourceRefs = new Map<string, string>()
const preserveTypedQueryParams = () => ''

export function getOpenVikingResourceRef(uri: string): string | undefined {
  const value = uri.trim()
  return (
    resourceRefs.get(value) ??
    resourceRefs.get(value.endsWith('/') ? value.slice(0, -1) : `${value}/`)
  )
}
const OPERATION_PATHS = new Map<string, string>([
  ['/api/v1/fs/ls', 'fs_list'],
  ['/api/v1/fs/tree', 'fs_tree'],
  ['/api/v1/fs/stat', 'fs_stat'],
  ['/api/v1/fs', 'fs_delete'],
  ['/api/v1/content/read', 'content_read'],
  ['/api/v1/content/abstract', 'content_abstract'],
  ['/api/v1/content/overview', 'content_overview'],
  ['/api/v1/content/reindex', 'content_reindex'],
  ['/api/v1/content/write', 'content_write'],
  ['/api/v1/resources', 'resource_import'],
  ['/api/v1/search/find', 'find'],
  ['/api/v1/search/search', 'search'],
  ['/api/v1/search/grep', 'grep'],
  ['/api/v1/search/glob', 'glob'],
  ['/api/v1/tasks', 'tasks'],
  ['/api/v1/watches', 'watches'],
])

function resolveBffOperation(pathname: string, method: string) {
  const sessionCommitMatch = pathname.match(
    /^\/api\/v1\/sessions\/([^/]+)\/commit$/,
  )
  if (sessionCommitMatch && method === 'POST') {
    return { operation: 'session_commit', itemId: sessionCommitMatch[1] }
  }
  const watchMatch = pathname.match(/^\/api\/v1\/watches\/([^/]+)(\/trigger)?$/)
  if (watchMatch) {
    const operation = watchMatch[2]
      ? 'watch_trigger'
      : method === 'PATCH'
        ? 'watch_update'
        : method === 'DELETE'
          ? 'watch_delete'
          : 'watch_get'
    return { operation, itemId: watchMatch[1] }
  }
  const taskMatch = pathname.match(/^\/api\/v1\/tasks\/([^/]+)$/)
  if (taskMatch) return { operation: 'task_get', itemId: taskMatch[1] }
  const operation = OPERATION_PATHS.get(pathname)
  if (!operation) return null
  if (operation === 'watches' && method === 'POST') {
    return { operation: 'watch_create' }
  }
  return { operation }
}
function isBrowser(): boolean {
  return typeof window !== 'undefined'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function rememberResourceRefs(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(rememberResourceRefs)
    return
  }
  if (!isRecord(value)) return
  const pairs = [
    ['uri', 'resource_ref'],
    ['target_uri', 'target_ref'],
    ['resource_id', 'resource_id_ref'],
    ['root_uri', 'root_ref'],
    ['to_uri', 'to_ref'],
    ['parent', 'parent_ref'],
    ['to', 'destination_ref'],
  ] as const
  for (const [uriKey, refKey] of pairs) {
    const uri = typeof value[uriKey] === 'string' ? value[uriKey] : undefined
    const ref = typeof value[refKey] === 'string' ? value[refKey] : undefined
    if (uri && ref) {
      resourceRefs.set(uri, ref)
      if (uri.startsWith('viking://') && uri !== 'viking://') {
        const withoutSlash = uri.endsWith('/') ? uri.slice(0, -1) : uri
        resourceRefs.set(withoutSlash, ref)
        resourceRefs.set(`${withoutSlash}/`, ref)
      }
    }
  }
  Object.values(value).forEach(rememberResourceRefs)
}

function opaquePayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(opaquePayload)
  if (!isRecord(value)) return value
  const result: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (
      [
        'uri',
        'target_uri',
        'resource_id',
        'root_uri',
        'to_uri',
        'parent',
        'to',
      ].includes(
        key,
      ) &&
      typeof item === 'string' &&
      item.startsWith('viking://')
    ) {
      const ref = resourceRefs.get(item)
      if (!ref) {
        throw new OvClientError({
          code: 'OPENVIKING_RESOURCE_REF_REQUIRED',
          message: 'Refresh the OpenViking resource before using it',
        })
      }
      const refKey: Record<string, string> = {
        uri: 'resource_ref',
        target_uri: 'target_ref',
        resource_id: 'resource_id_ref',
        root_uri: 'root_ref',
        to_uri: 'to_ref',
        parent: 'parent_ref',
        to: 'destination_ref',
      }
      result[refKey[key]] = ref
    } else {
      result[key] = opaquePayload(item)
    }
  }
  return result
}

function sameOriginBaseUrl(): string {
  return isBrowser() ? window.location.origin.replace(/\/+$/, '') : ''
}

function resolvePathname(rawUrl?: string): string {
  if (!rawUrl) {
    return ''
  }

  try {
    return new URL(rawUrl, 'http://openviking.local').pathname
  } catch {
    return rawUrl.startsWith('/') ? rawUrl : ''
  }
}

function parseQueryValue(key: string, value: string): unknown {
  if (key === 'raw' && /^(true|false)$/i.test(value)) {
    return value.toLowerCase() === 'true'
  }
  if ((key === 'offset' || key === 'limit') && /^-?\d+$/.test(value)) {
    return Number.parseInt(value, 10)
  }
  return value
}

function readUrlQuery(rawUrl?: string): Record<string, unknown> {
  if (!rawUrl) return {}

  try {
    const result: Record<string, unknown> = {}
    const searchParams = new URL(rawUrl, 'http://openviking.local').searchParams
    for (const [key, value] of searchParams) {
      const parsed = parseQueryValue(key, value)
      const previous = result[key]
      result[key] = previous !== undefined
        ? Array.isArray(previous)
          ? [...previous, parsed]
          : [previous, parsed]
        : parsed
    }
    return result
  } catch {
    return {}
  }
}

function readHeader(headers: unknown, name: string): string | undefined {
  if (headers instanceof AxiosHeaders) {
    const value = headers.get(name)
    return typeof value === 'string' ? value : undefined
  }

  if (isRecord(headers)) {
    const value = headers[name] ?? headers[name.toLowerCase()]
    return typeof value === 'string' ? value : undefined
  }

  return undefined
}

function shouldInjectTelemetry(
  config: InternalAxiosRequestConfig,
  defaultTelemetry: boolean,
): boolean {
  if (!defaultTelemetry || config.method?.toUpperCase() !== 'POST') {
    return false
  }

  const pathname = resolvePathname(config.url)
  return (
    DEFAULT_TELEMETRY_PATHS.has(pathname) || SESSION_COMMIT_PATH.test(pathname)
  )
}

function maybeInjectTelemetry(
  config: InternalAxiosRequestConfig,
  defaultTelemetry: boolean,
): void {
  if (!shouldInjectTelemetry(config, defaultTelemetry)) {
    return
  }

  if (!isRecord(config.data) || config.data.telemetry !== undefined) {
    return
  }

  config.data = {
    ...config.data,
    telemetry: true,
  }
}

function isEnvelopeError(value: unknown): value is OvErrorEnvelope & {
  error: NonNullable<OvErrorEnvelope['error']>
  status: 'error'
} {
  return isRecord(value) && value.status === 'error' && isRecord(value.error)
}

export function createOvClient(options: OvClientOptions = {}): OvClientAdapter {
  const bindSdkClient = options.bindSdkClient ?? false
  const runtimeOptions = {
    baseUrl: sameOriginBaseUrl(),
    defaultTelemetry: options.defaultTelemetry ?? true,
  }

  const instance = options.axios ?? axios.create()
  const defaultHeaders = { ...(options.defaultHeaders || {}) }
  const client = createClient({
    axios: instance,
    baseURL: runtimeOptions.baseUrl,
    headers: defaultHeaders,
    paramsSerializer: preserveTypedQueryParams,
    throwOnError: true,
  })

  instance.interceptors.request.use((config) => {
    const headers = AxiosHeaders.from(config.headers)
    const profileId = getActiveOpenVikingProfileId()
    const pathname = resolvePathname(config.url)
    const isUpload = pathname === '/api/v1/resources/temp_upload'
    const resolved = resolveBffOperation(
      pathname,
      (config.method ?? 'GET').toUpperCase(),
    )
    if (!profileId) {
      throw new OvClientError({
        code: 'OPENVIKING_PROFILE_REQUIRED',
        message: 'Select an OpenViking profile first',
      })
    }
    if (!resolved && !isUpload) {
      throw new OvClientError({
        code: 'OPERATION_NOT_ALLOWED',
        message: 'This OpenViking operation is not allowed by AgentKit',
      })
    }
    const payload = opaquePayload({
      ...readUrlQuery(config.url),
      ...(isRecord(config.params) ? config.params : {}),
      ...(isRecord(config.data) ? config.data : {}),
    })
    const suffix = resolved?.itemId
      ? `/${encodeURIComponent(resolved.itemId)}`
      : ''
    config.baseURL = ''
    config.url = isUpload
      ? `${BFF_ROOT}/profiles/${encodeURIComponent(profileId)}/upload`
      : `${BFF_ROOT}/profiles/${encodeURIComponent(profileId)}/operations/${resolved!.operation}${suffix}`
    config.method = 'POST'
    config.params = undefined
    if (!isUpload) config.data = { payload }

    for (const [key, value] of Object.entries(defaultHeaders)) {
      headers.set(key, value)
    }

    headers.delete('X-API-Key')
    headers.delete('X-OpenViking-Account')
    headers.delete('X-OpenViking-User')
    for (const [key, value] of withLocalUser()) {
      headers.set(key, value)
    }
    config.url = withAuth(config.url)
    if (!isUpload) headers.set('Content-Type', 'application/json')

    config.headers = headers
    maybeInjectTelemetry(config, runtimeOptions.defaultTelemetry)

    return config
  })

  instance.interceptors.response.use(
    (response) => {
      const requestId = readHeader(response.headers, 'x-request-id')

      if (isEnvelopeError(response.data)) {
        const { error } = response.data
        const message = error.message || 'OpenViking request failed'

        throw new OvClientError({
          code: error.code || 'ERROR',
          details: error.details ?? error.detail,
          message,
          requestId,
          responseBody: response.data,
          statusCode: response.status,
        })
      }

      if (
        isRecord(response.data) &&
        'data' in response.data &&
        'meta' in response.data
      ) {
        response.data = response.data.data
      }
      rememberResourceRefs(response.data)
      return response
    },
    (error) => {
      const normalized = normalizeOvClientError(error)
      return Promise.reject(normalized)
    },
  )

  function syncClientConfig(): void {
    client.setConfig({
      baseURL: runtimeOptions.baseUrl,
      throwOnError: true,
    })

    if (!bindSdkClient) {
      return
    }

    sdkClient.setConfig({
      axios: instance,
      baseURL: runtimeOptions.baseUrl,
      headers: defaultHeaders,
      paramsSerializer: preserveTypedQueryParams,
      throwOnError: true,
    })
  }

  function getOptions(): Readonly<typeof runtimeOptions> {
    return { ...runtimeOptions }
  }

  syncClientConfig()

  return {
    client,
    getOptions,
    instance,
  }
}

export const ovClient = createOvClient({
  bindSdkClient: true,
})

export function registerOpenVikingRoot(uri: string, ref: string): void {
  resourceRefs.set(uri, ref)
  if (uri.startsWith('viking://') && uri !== 'viking://') {
    const withoutSlash = uri.endsWith('/') ? uri.slice(0, -1) : uri
    resourceRefs.set(withoutSlash, ref)
    resourceRefs.set(`${withoutSlash}/`, ref)
  }
}
