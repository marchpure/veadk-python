import type { AxiosInstance, AxiosResponse } from 'axios'

import type { Client } from '#/gen/ov-client/client'

export interface OvClientOptions {
  axios?: AxiosInstance
  bindSdkClient?: boolean
  defaultHeaders?: Record<string, string>
  defaultTelemetry?: boolean
}

export interface OvClientAdapter {
  client: Client
  instance: AxiosInstance
  getOptions: () => Readonly<{
    baseUrl: string
    defaultTelemetry: boolean
  }>
}

export interface OvErrorEnvelope {
  status?: string
  error?: {
    code?: string
    detail?: unknown
    details?: unknown
    message?: string
  }
}

export interface OvClientErrorOptions {
  code: string
  details?: unknown
  message: string
  requestId?: string
  responseBody?: unknown
  statusCode?: number
}

export interface OvSuccessEnvelope<TResult = unknown> {
  result?: TResult
  status?: string
  telemetry?: unknown
}

export type OvResponse<TResult = unknown> = AxiosResponse<unknown> & {
  data: OvSuccessEnvelope<TResult> | TResult | unknown
}
