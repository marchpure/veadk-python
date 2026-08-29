import * as React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2Icon,
  ChevronRightIcon,
  CircleDashedIcon,
  CircleXIcon,
  ClipboardListIcon,
  LayersIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  RotateCcwIcon,
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Badge } from '#/components/ui/badge'
import { Button } from '#/components/ui/button'
import { Card } from '#/components/ui/card'
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from '#/components/ui/pagination'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '#/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '#/components/ui/table'
import { postResources } from '#/gen/ov-client'
import { useAppConnection } from '#/hooks/use-app-connection'
import { ovClient } from '#/lib/ov-client'
import { commitSession } from '#/lib/sessions/api'
import { cn } from '#/lib/utils'

import { TaskDetailSheet } from './-components/task-detail-sheet'
import { fetchTasks, MAX_TASKS } from './-lib/task-list'
import type { TaskStatusFilter, TaskTypeFilter } from './-lib/task-list'
import { normalizeTaskStatus } from './-lib/task-record'
import type { TaskRecord, TaskStatus } from './-lib/task-record'
import { formatTaskDuration, getTaskDate } from './-lib/task-time'

const DEFAULT_PAGE_SIZE = 20
const PAGE_SIZE_OPTIONS = [20, 50, 100] as const
const TASK_TYPE_OPTIONS: Exclude<TaskTypeFilter, 'all'>[] = [
  'session_commit',
  'add_resource',
  'add_skill',
  'connector_import',
  'admin_reindex',
  'snapshot_restore_reindex',
  'legacy_migration',
  'legacy_cleanup',
]
const TASK_STATUS_OPTIONS: Exclude<TaskStatusFilter, 'all'>[] = [
  'pending',
  'running',
  'cancelling',
  'completed',
  'failed',
  'cancelled',
]

function formatTaskTime(task: TaskRecord): string {
  const date = getTaskDate(task)
  if (!date) return '-'
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date)
}

function taskKey(task: TaskRecord, index: number): string {
  return (
    task.task_id ||
    [task.task_type, task.resource_id, task.created_at, index].join(':')
  )
}

function StatusBadge({ status }: { status: TaskStatus }) {
  const { t } = useTranslation('tasksPage')
  const Icon =
    status === 'completed'
      ? CheckCircle2Icon
      : status === 'failed' || status === 'cancelled'
        ? CircleXIcon
        : status === 'running' || status === 'cancelling'
          ? LoaderCircleIcon
          : CircleDashedIcon

  return (
    <Badge
      variant={
        status === 'failed'
          ? 'destructive'
          : status === 'completed'
            ? 'secondary'
            : 'outline'
      }
      className="gap-1.5 font-normal"
    >
      <Icon
        className={
          status === 'running' || status === 'cancelling'
            ? 'size-3.5 animate-spin'
            : 'size-3.5'
        }
      />
      {t(`status.${status}`)}
    </Badge>
  )
}

export function TasksRoute() {
  const { i18n, t } = useTranslation('tasksPage')
  const { identityScopeKey } = useAppConnection()
  const queryClient = useQueryClient()
  const [page, setPage] = React.useState(1)
  const [pageSize, setPageSize] = React.useState(DEFAULT_PAGE_SIZE)
  const [taskType, setTaskType] = React.useState<TaskTypeFilter>('all')
  const [statusFilter, setStatusFilter] =
    React.useState<TaskStatusFilter>('all')
  const [dedupByResource, setDedupByResource] = React.useState(true)
  const [selectedTaskId, setSelectedTaskId] = React.useState<string | null>(
    null,
  )

  const tasksQuery = useQuery({
    queryFn: () => fetchTasks(taskType, statusFilter),
    queryKey: ['tasks', identityScopeKey, taskType, statusFilter],
    refetchInterval: 10_000,
  })
  const rawTasks = tasksQuery.data ?? []
  const allTasks = React.useMemo(() => {
    if (!dedupByResource) return rawTasks
    const latestByResource = new Map<string, TaskRecord>()
    for (const task of rawTasks) {
      const key = task.resource_id
        ? `resource:${task.resource_id}`
        : `task:${task.task_id}`
      if (!latestByResource.has(key)) latestByResource.set(key, task)
    }
    return Array.from(latestByResource.values())
  }, [dedupByResource, rawTasks])

  const pageOffset = (page - 1) * pageSize
  const tasks = allTasks.slice(pageOffset, pageOffset + pageSize)
  const totalPages = Math.max(1, Math.ceil(allTasks.length / pageSize))
  const hasActiveFilters = taskType !== 'all' || statusFilter !== 'all'

  React.useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const retryMutation = useMutation({
    mutationFn: async (task: TaskRecord) => {
      if (!task.resource_id) {
        throw new Error(t('retry.missingResource'))
      }

      if (task.task_type === 'session_commit') {
        return commitSession(task.resource_id)
      }

      if (
        task.resource_id.startsWith('http://') ||
        task.resource_id.startsWith('https://')
      ) {
        return postResources({
          body: {
            path: task.resource_id,
            reason: `Re-queued task: ${task.task_id || 'unknown'}`,
            wait: false,
          },
        })
      }

      const response = await ovClient.instance.post('/api/v1/content/reindex', {
        uri: task.resource_id,
        wait: false,
      })
      return response.data
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : String(error))
    },
    onSuccess: async () => {
      toast.success(t('retry.submitted'))
      await queryClient.invalidateQueries({ queryKey: ['tasks'] })
    },
  })

  return (
    <div className="flex w-full min-w-0 flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <h1 className="text-xl font-semibold">{t('title')}</h1>
          <p className="max-w-3xl text-sm leading-5 text-muted-foreground">
            {t('description')}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={tasksQuery.isFetching}
          onClick={() => void tasksQuery.refetch()}
        >
          <RefreshCwIcon
            className={tasksQuery.isFetching ? 'animate-spin' : undefined}
          />
          {t('refresh')}
        </Button>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-y border-border/70 py-3">
        <span className="mr-1 text-xs font-medium text-muted-foreground">
          {t('filters.label')}
        </span>
        <Select
          value={taskType}
          onValueChange={(value) => {
            setTaskType(value as TaskTypeFilter)
            setPage(1)
          }}
        >
          <SelectTrigger
            size="sm"
            className="min-w-40 bg-background"
            aria-label={t('filters.type')}
          >
            <SelectValue>
              {taskType === 'all'
                ? t('filters.allTypes')
                : t(`types.${taskType}`)}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('filters.allTypes')}</SelectItem>
            {TASK_TYPE_OPTIONS.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`types.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={statusFilter}
          onValueChange={(value) => {
            setStatusFilter(value as TaskStatusFilter)
            setPage(1)
          }}
        >
          <SelectTrigger
            size="sm"
            className="min-w-32 bg-background"
            aria-label={t('filters.status')}
          >
            <SelectValue>
              {statusFilter === 'all'
                ? t('filters.allStatuses')
                : t(`status.${statusFilter}`)}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('filters.allStatuses')}</SelectItem>
            {TASK_STATUS_OPTIONS.map((option) => (
              <SelectItem key={option} value={option}>
                {t(`status.${option}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          type="button"
          variant={dedupByResource ? 'secondary' : 'outline'}
          size="sm"
          onClick={() => {
            setDedupByResource((current) => !current)
            setPage(1)
          }}
        >
          <LayersIcon />
          {t(
            dedupByResource
              ? 'filters.latestPerResource'
              : 'filters.individualTasks',
          )}
        </Button>
        {hasActiveFilters ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-muted-foreground"
            onClick={() => {
              setTaskType('all')
              setStatusFilter('all')
              setPage(1)
            }}
          >
            {t('filters.clear')}
          </Button>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {t('summary', { count: allTasks.length })}
        </span>
      </div>

      {tasksQuery.isLoading ? (
        <PageState icon={<LoaderCircleIcon className="animate-spin" />}>
          {t('loading')}
        </PageState>
      ) : tasksQuery.isError ? (
        <PageState icon={<CircleXIcon />}>
          <span>{t('loadFailed')}</span>
          <span className="max-w-xl text-xs text-muted-foreground">
            {tasksQuery.error instanceof Error
              ? tasksQuery.error.message
              : String(tasksQuery.error)}
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void tasksQuery.refetch()}
          >
            <RefreshCwIcon />
            {t('detail.retry')}
          </Button>
        </PageState>
      ) : tasks.length === 0 ? (
        <PageState icon={<ClipboardListIcon />}>
          <span>{t(hasActiveFilters ? 'emptyFiltered' : 'empty')}</span>
          <span className="max-w-md text-xs text-muted-foreground">
            {t(
              hasActiveFilters
                ? 'emptyFilteredDescription'
                : 'emptyDescription',
            )}
          </span>
        </PageState>
      ) : (
        <Card className="gap-0 overflow-hidden rounded-lg py-0 shadow-none ring-1 ring-border">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/35 hover:bg-muted/35">
                  <TableHead>{t('table.task')}</TableHead>
                  <TableHead>{t('table.type')}</TableHead>
                  <TableHead>{t('table.resource')}</TableHead>
                  <TableHead>{t('table.status')}</TableHead>
                  <TableHead>{t('table.duration')}</TableHead>
                  <TableHead className="text-right">
                    {t('table.createdAt')}
                  </TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {tasks.map((task, index) => {
                  const taskId = task.task_id
                  const status = normalizeTaskStatus(task.status)
                  const isRetrying =
                    retryMutation.isPending &&
                    retryMutation.variables?.task_id === taskId
                  return (
                    <TableRow
                      key={taskKey(task, index)}
                      tabIndex={taskId ? 0 : undefined}
                      aria-label={
                        taskId ? t('detail.openLabel', { taskId }) : undefined
                      }
                      className={cn(
                        taskId &&
                          'cursor-pointer outline-none hover:bg-muted/30 focus-visible:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-inset',
                      )}
                      onClick={() => taskId && setSelectedTaskId(taskId)}
                      onKeyDown={(event) => {
                        if (
                          taskId &&
                          (event.key === 'Enter' || event.key === ' ')
                        ) {
                          event.preventDefault()
                          setSelectedTaskId(taskId)
                        }
                      }}
                    >
                      <TableCell>
                        <code className="block max-w-52 truncate text-xs">
                          {taskId || `#${pageOffset + index + 1}`}
                        </code>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs font-medium">
                        {task.task_type
                          ? t(`types.${task.task_type}`, {
                              defaultValue: task.task_type,
                            })
                          : '-'}
                      </TableCell>
                      <TableCell>
                        <span
                          className="block max-w-72 truncate text-xs text-muted-foreground"
                          title={task.resource_id || undefined}
                        >
                          {task.resource_id || '-'}
                        </span>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={status} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatTaskDuration(
                          task,
                          i18n.language.startsWith('zh'),
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right text-xs text-muted-foreground">
                        {formatTaskTime(task)}
                      </TableCell>
                      <TableCell>
                        {status === 'failed' ? (
                          <Button
                            type="button"
                            size="icon-xs"
                            variant="ghost"
                            disabled={isRetrying}
                            aria-label={t('retry.action')}
                            title={t('retry.action')}
                            onClick={(event) => {
                              event.stopPropagation()
                              retryMutation.mutate(task)
                            }}
                          >
                            {isRetrying ? (
                              <LoaderCircleIcon className="animate-spin" />
                            ) : (
                              <RotateCcwIcon />
                            )}
                          </Button>
                        ) : taskId ? (
                          <ChevronRightIcon className="size-4 text-muted-foreground/60" />
                        ) : null}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
          <div className="flex flex-col gap-3 border-t px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs text-muted-foreground">
                {t('pagination.scope', {
                  count: allTasks.length,
                  limit: MAX_TASKS,
                })}
              </span>
              <Select
                value={String(pageSize)}
                onValueChange={(value) => {
                  setPageSize(Number(value))
                  setPage(1)
                }}
              >
                <SelectTrigger
                  size="sm"
                  aria-label={t('pagination.pageSize')}
                >
                  <SelectValue>
                    {t('pagination.pageSizeValue', { count: pageSize })}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZE_OPTIONS.map((option) => (
                    <SelectItem key={option} value={String(option)}>
                      {t('pagination.pageSizeValue', { count: option })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground">
                {t('pagination.page', { page })}
              </span>
              <Pagination className="mx-0 w-auto justify-end">
                <PaginationContent>
                  <PaginationItem>
                    <PaginationPrevious
                      href="#"
                      text={t('pagination.previous')}
                      aria-disabled={page <= 1}
                      className={cn(
                        page <= 1 && 'pointer-events-none opacity-50',
                      )}
                      onClick={(event) => {
                        event.preventDefault()
                        if (page > 1) setPage((current) => current - 1)
                      }}
                    />
                  </PaginationItem>
                  <PaginationItem>
                    <PaginationNext
                      href="#"
                      text={t('pagination.next')}
                      aria-disabled={page >= totalPages}
                      className={cn(
                        page >= totalPages &&
                          'pointer-events-none opacity-50',
                      )}
                      onClick={(event) => {
                        event.preventDefault()
                        if (page < totalPages) {
                          setPage((current) => current + 1)
                        }
                      }}
                    />
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            </div>
          </div>
        </Card>
      )}

      <TaskDetailSheet
        identityScopeKey={identityScopeKey}
        open={Boolean(selectedTaskId)}
        taskId={selectedTaskId}
        onOpenChange={(open) => {
          if (!open) setSelectedTaskId(null)
        }}
      />
    </div>
  )
}

function PageState({
  children,
  icon,
}: {
  children: React.ReactNode
  icon: React.ReactNode
}) {
  return (
    <div className="flex min-h-64 flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 text-center text-sm [&_svg]:size-7 [&_svg]:text-muted-foreground">
      {icon}
      {children}
    </div>
  )
}
