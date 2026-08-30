import { beforeEach, describe, expect, it, vi } from 'vitest'

import { deleteFsResource, fetchFsList } from './api'

const { deleteMock, getFsLsMock } = vi.hoisted(() => ({
  deleteMock: vi.fn(),
  getFsLsMock: vi.fn(),
}))

vi.mock('#/lib/ov-client', async (importOriginal) => {
  const original = await importOriginal<Record<string, unknown>>()
  return {
    ...original,
    getFsLs: getFsLsMock,
    ovClient: { client: { delete: deleteMock } },
  }
})

describe('fetchFsList', () => {
  beforeEach(() => {
    getFsLsMock.mockReset()
    getFsLsMock.mockResolvedValue({
      data: { status: 'ok', result: [] },
      headers: {},
      status: 200,
    })
  })

  it('requests newest entries before the server applies node_limit', async () => {
    await fetchFsList('viking://session', { nodeLimit: 200 })

    expect(getFsLsMock).toHaveBeenCalledWith({
      query: expect.objectContaining({
        node_limit: 200,
        sort_by: 'mtime',
        sort_order: 'desc',
      }),
    })
  })

  it('deletes a resource recursively through the authenticated adapter', async () => {
    deleteMock.mockResolvedValue({
      data: { status: 'ok', result: { estimated_deleted_count: 2 } },
      headers: {},
      status: 200,
    })

    await deleteFsResource('viking://resources/guide', true)

    expect(deleteMock).toHaveBeenCalledWith({
      query: {
        uri: 'viking://resources/guide',
        recursive: true,
        wait: true,
      },
      url: '/api/v1/fs',
    })
  })
})
