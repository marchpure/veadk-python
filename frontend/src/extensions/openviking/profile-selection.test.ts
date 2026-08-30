import { describe, expect, it } from 'vitest'

import type { OpenVikingProfile } from './hooks/use-app-connection'
import {
  ACTIVE_OPENVIKING_PROFILE_KEY,
  selectReadyProfileId,
} from './profile-selection'

const profile = (
  profile_id: string,
  status: OpenVikingProfile['status'],
): OpenVikingProfile => ({
  profile_id,
  display_name: profile_id,
  workspace_uri: 'viking://workspace/',
  root_resource_ref: `ovr_${profile_id}`,
  status,
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z',
})

describe('selectReadyProfileId', () => {
  it('uses a stable storage key for refresh recovery', () => {
    expect(ACTIVE_OPENVIKING_PROFILE_KEY).toBe('openviking.activeProfileId')
  })

  it('keeps an existing Ready selection', () => {
    expect(
      selectReadyProfileId(
        [profile('ready-a', 'ready'), profile('ready-b', 'ready')],
        'ready-b',
      ),
    ).toBe('ready-b')
  })

  it('replaces stale or non-Ready selections with the first Ready profile', () => {
    const profiles = [
      profile('pending', 'pending'),
      profile('ready', 'ready'),
      profile('failed', 'error'),
    ]
    expect(selectReadyProfileId(profiles, 'missing')).toBe('ready')
    expect(selectReadyProfileId(profiles, 'pending')).toBe('ready')
    // Revoked profiles disappear from the list, leaving a stale prior ID.
    expect(selectReadyProfileId(profiles, 'revoked')).toBe('ready')
  })

  it('selects nothing when no Ready profile exists', () => {
    expect(
      selectReadyProfileId(
        [profile('pending', 'pending'), profile('failed', 'error')],
        'pending',
      ),
    ).toBe('')
  })
})
