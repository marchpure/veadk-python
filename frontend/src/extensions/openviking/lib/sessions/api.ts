import { getOvResult, postSessionIdCommit } from '#/lib/ov-client'

type CommitSessionResult = {
  archive_uri: string
  archived: boolean
  session_id: string
  status: string
  task_id: string
}

export async function commitSession(
  sessionId: string,
  keepRecentCount?: number,
): Promise<CommitSessionResult> {
  return getOvResult<CommitSessionResult>(
    postSessionIdCommit({
      body:
        keepRecentCount === undefined
          ? undefined
          : { keep_recent_count: keepRecentCount },
      path: { session_id: sessionId },
    }),
  )
}
