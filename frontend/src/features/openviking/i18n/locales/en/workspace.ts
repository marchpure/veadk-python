const workspace = {
  tasksPage: {
    title: 'Task Center',
    description:
      'Track background work such as resource processing, session commits, and reindexing.',
    refresh: 'Refresh',
    loading: 'Loading tasks...',
    empty: 'No background tasks',
    emptyDescription:
      'Asynchronous work will appear here with its status and update time.',
    emptyFiltered: 'No matching tasks',
    emptyFilteredDescription: 'Adjust or clear the filters to see other tasks.',
    loadFailed: 'Could not load tasks',
    summary: '{{count}} tasks',
    detail: {
      title: 'Task details',
      loading: 'Loading task details...',
      loadFailed: 'Could not load task details',
      retry: 'Retry',
      openLabel: 'View details for task {{taskId}}',
      fields: {
        status: 'Task status',
        type: 'Task type',
        stage: 'Current stage',
        duration: 'Duration',
        resource: 'Resource',
        createdAt: 'Created',
        updatedAt: 'Updated',
      },
      error: 'Failure reason',
      result: 'Result',
    },
    filters: {
      label: 'Filter',
      type: 'Task type',
      status: 'Task status',
      allTypes: 'All types',
      allStatuses: 'All statuses',
      clear: 'Clear filters',
      latestPerResource: 'Latest per resource',
      individualTasks: 'Individual tasks',
    },
    pagination: {
      next: 'Next',
      page: 'Page {{page}}',
      pageSize: 'Rows per page',
      pageSizeValue: '{{count}} per page',
      previous: 'Previous',
      scope:
        'Showing the latest {{count}} tasks (the API returns at most {{limit}})',
    },
    table: {
      task: 'Task',
      type: 'Type',
      resource: 'Resource',
      createdAt: 'Created',
      status: 'Status',
      duration: 'Duration',
    },
    retry: {
      action: 'Retry task',
      missingResource: 'This task has no resource ID and cannot be retried.',
      submitted: 'The task was submitted again.',
    },
    status: {
      cancelled: 'Cancelled',
      cancelling: 'Cancelling',
      completed: 'Completed',
      failed: 'Failed',
      pending: 'Pending',
      running: 'Running',
      unknown: 'Unknown',
    },
    types: {
      session_commit: 'Session commit',
      add_resource: 'Resource processing',
      add_skill: 'Skill import',
      connector_import: 'Connector import',
      admin_reindex: 'Reindex',
      snapshot_restore_reindex: 'Snapshot reindex',
      legacy_migration: 'Legacy migration',
      legacy_cleanup: 'Legacy cleanup',
    },
  },
  watchesPage: {
    title: 'Scheduled Sync',
    description:
      'Keep remote resources current with recurring Watch tasks and manage their schedules.',
    refresh: 'Refresh',
    add: 'Add',
    adding: 'Adding...',
    loading: 'Loading scheduled syncs...',
    loadFailed: 'Could not load scheduled syncs',
    empty: 'No scheduled syncs',
    emptyDescription:
      'Add a remote resource and enable scheduled sync to get started.',
    never: 'Not synced yet',
    cancel: 'Cancel',
    save: 'Save',
    creation: {
      title: 'Creating scheduled sync',
      description:
        'The resource was submitted in the background. The list will refresh automatically.',
    },
    columns: {
      resource: 'Resource',
      source: 'Source',
      status: 'Status',
      interval: 'Interval',
      lastRun: 'Last sync',
      nextRun: 'Next sync',
      actions: 'Actions',
    },
    status: {
      active: 'Enabled',
      disabled: 'Disabled',
    },
    actions: {
      trigger: 'Sync now',
      syncing: 'Syncing...',
      disable: 'Disable',
      enable: 'Enable',
      more: 'More',
      history: 'Processing history',
      edit: 'Edit',
      delete: 'Delete',
    },
    interval: {
      minutes_one: 'Every minute',
      minutes_other: 'Every {{count}} minutes',
      hours_one: 'Every hour',
      hours_other: 'Every {{count}} hours',
      days_one: 'Every day',
      days_other: 'Every {{count}} days',
    },
    addDialog: {
      title: 'Add scheduled sync',
      description:
        'Add a remote resource and configure how often OpenViking checks for updates.',
    },
    editDialog: {
      title: 'Edit scheduled sync',
      interval: 'Interval (minutes)',
      intervalHint: 'For example, 60 for hourly or 1440 for daily.',
      reason: 'Reason (optional)',
      reasonPlaceholder: 'Why should this resource stay synchronized?',
      instruction: 'Processing instruction (optional)',
      instructionPlaceholder:
        'Special processing instructions for this resource.',
    },
    deleteDialog: {
      title: 'Delete scheduled sync?',
      description:
        'The resource {{uri}} will remain available, but it will no longer update automatically.',
    },
    history: {
      title: 'Processing history',
      description:
        'Background tasks filtered by this resource. Results may include the initial import, manual processing, and scheduled syncs.',
      loading: 'Loading processing history...',
      loadFailed: 'Could not load processing history',
      empty: 'No processing history',
      emptyDescription:
        'No background processing tasks were found for this resource.',
      stage: 'Stage',
    },
    toast: {
      creating: 'Creating scheduled sync. Please wait...',
      created: 'Scheduled sync added',
      createTimeout: 'The new task is not visible yet. Refresh again shortly.',
      updated: 'Scheduled sync updated',
      triggered: 'Sync scheduled',
      deleted: 'Scheduled sync deleted',
    },
  },
} as const

export default workspace
