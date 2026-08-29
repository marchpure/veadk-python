import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CircleXIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '#/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '#/components/ui/sheet'
import { getOvResult, getTaskByTaskId } from '#/lib/ov-client'
import { formatTaskDuration, getTaskDate } from '#/routes/tasks/-lib/task-time'

import {
  hasTaskResult,
  normalizeTaskRecord,
  normalizeTaskStatus,
} from '../-lib/task-record'
import type { TaskRecord } from '../-lib/task-record'

type TaskDetailSheetProps = {
  identityScopeKey: string
  onOpenChange: (open: boolean) => void
  open: boolean
  taskId: string | null
}

async function fetchTask(taskId: string): Promise<TaskRecord> {
  const result = await getOvResult<unknown>(
    getTaskByTaskId({ path: { task_id: taskId } }),
  )
  const task = normalizeTaskRecord(result)
  if (!task) throw new Error('Task response is invalid')
  return task
}

function formatTime(task: TaskRecord, kind: 'created' | 'updated'): string {
  const date =
    kind === 'created'
      ? getTaskDate(task)
      : getTaskDate({
          created_at: task.updated_at,
          created_at_iso: task.updated_at_iso,
        })
  if (!date) return '-'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date)
}

function formatResult(result: unknown): string {
  if (typeof result === 'string') return result
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return String(result)
  }
}

export function TaskDetailSheet({
  identityScopeKey,
  onOpenChange,
  open,
  taskId,
}: TaskDetailSheetProps) {
  const { i18n, t } = useTranslation('tasksPage')
  const detailQuery = useQuery({
    enabled: open && Boolean(taskId),
    queryFn: () => fetchTask(taskId || ''),
    queryKey: ['task-detail', identityScopeKey, taskId],
    refetchInterval: (query) => {
      const status = normalizeTaskStatus(query.state.data?.status)
      return status === 'pending' ||
        status === 'running' ||
        status === 'cancelling'
        ? 3_000
        : false
    },
  })
  const task = detailQuery.data

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="gap-0 data-[side=right]:sm:max-w-2xl">
        <SheetHeader className="border-b px-6 py-5">
          <SheetTitle className="text-base">{t('detail.title')}</SheetTitle>
          <SheetDescription className="truncate font-mono text-xs">
            {taskId}
          </SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {detailQuery.isLoading ? (
            <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t('detail.loading')}
            </div>
          ) : detailQuery.isError ? (
            <div className="flex min-h-48 flex-col items-center justify-center gap-3 text-center">
              <CircleXIcon className="size-7 text-destructive/70" />
              <div className="grid gap-1">
                <p className="text-sm font-medium">{t('detail.loadFailed')}</p>
                <p className="max-w-md text-xs text-muted-foreground">
                  {detailQuery.error instanceof Error
                    ? detailQuery.error.message
                    : String(detailQuery.error)}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void detailQuery.refetch()}
              >
                <RefreshCwIcon />
                {t('detail.retry')}
              </Button>
            </div>
          ) : task ? (
            <div className="grid gap-6">
              <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
                <DetailField
                  label={t('detail.fields.status')}
                  value={t(`status.${normalizeTaskStatus(task.status)}`)}
                />
                <DetailField
                  label={t('detail.fields.type')}
                  value={
                    task.task_type
                      ? t(`types.${task.task_type}`, {
                          defaultValue: task.task_type,
                        })
                      : '-'
                  }
                />
                <DetailField
                  label={t('detail.fields.stage')}
                  value={task.stage || '-'}
                />
                <DetailField
                  label={t('detail.fields.duration')}
                  value={formatTaskDuration(
                    task,
                    i18n.language.startsWith('zh'),
                  )}
                />
                <DetailField
                  className="sm:col-span-2"
                  label={t('detail.fields.resource')}
                  value={task.resource_id || '-'}
                  mono
                />
                <DetailField
                  label={t('detail.fields.createdAt')}
                  value={formatTime(task, 'created')}
                />
                <DetailField
                  label={t('detail.fields.updatedAt')}
                  value={formatTime(task, 'updated')}
                />
              </dl>

              {task.error ? (
                <DetailSection title={t('detail.error')}>
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-lg border border-destructive/25 bg-destructive/5 p-4 font-mono text-xs leading-5 text-destructive">
                    {task.error}
                  </pre>
                </DetailSection>
              ) : null}

              {hasTaskResult(task.result) ? (
                <DetailSection title={t('detail.result')}>
                  <pre className="max-h-[28rem] overflow-auto rounded-lg border bg-muted/25 p-4 font-mono text-xs leading-5">
                    {formatResult(task.result)}
                  </pre>
                </DetailSection>
              ) : null}
            </div>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function DetailField({
  className,
  label,
  mono = false,
  value,
}: {
  className?: string
  label: string
  mono?: boolean
  value: string
}) {
  return (
    <div className={`min-w-0 border-b pb-3 ${className || ''}`}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd
        className={`mt-1 break-words text-sm font-medium ${mono ? 'font-mono text-xs' : ''}`}
        title={value}
      >
        {value}
      </dd>
    </div>
  )
}

function DetailSection({
  children,
  title,
}: {
  children: React.ReactNode
  title: string
}) {
  return (
    <section className="grid gap-2.5">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}
