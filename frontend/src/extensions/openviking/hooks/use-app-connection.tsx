import * as React from 'react'

export type OpenVikingProfile = {
  created_at: string
  display_name: string
  profile_id: string
  root_resource_ref: string
  status: 'pending' | 'ready' | 'error'
  updated_at: string
  workspace_uri: string
}

type AppConnectionContextValue = {
  activeProfile: OpenVikingProfile | null
  identityScopeKey: string
  setActiveProfile: (profile: OpenVikingProfile | null) => void
}

const AppConnectionContext =
  React.createContext<AppConnectionContextValue | null>(null)

let activeProfileId = ''

export function getActiveOpenVikingProfileId(): string {
  return activeProfileId
}

export function setActiveOpenVikingProfileId(profileId: string): void {
  activeProfileId = profileId
}

export function AppConnectionProvider({
  children,
  profile,
}: {
  children: React.ReactNode
  profile: OpenVikingProfile | null
}) {
  const [activeProfile, setActiveProfileState] = React.useState(profile)
  const setActiveProfile = React.useCallback(
    (next: OpenVikingProfile | null) => {
      setActiveOpenVikingProfileId(next?.profile_id ?? '')
      setActiveProfileState(next)
    },
    [],
  )

  React.useEffect(() => {
    setActiveOpenVikingProfileId(profile?.profile_id ?? '')
    setActiveProfileState(profile)
    return () => {
      setActiveOpenVikingProfileId('')
    }
  }, [profile])

  return (
    <AppConnectionContext.Provider
      value={{
        activeProfile,
        identityScopeKey: activeProfile?.profile_id ?? 'openviking-disconnected',
        setActiveProfile,
      }}
    >
      {children}
    </AppConnectionContext.Provider>
  )
}

export function useAppConnection(): AppConnectionContextValue {
  const value = React.useContext(AppConnectionContext)
  if (!value) {
    throw new Error(
      'useAppConnection must be used within AppConnectionProvider.',
    )
  }
  return value
}
