import workspace from './en/workspace'
import resources from './en/resources'

const en = {
  ...workspace,
  ...resources,
} as const

export default en
