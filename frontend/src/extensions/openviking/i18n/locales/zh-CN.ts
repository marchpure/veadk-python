import workspace from './zh-CN/workspace'
import resources from './zh-CN/resources'

const zhCN = {
  ...workspace,
  ...resources,
} as const

export default zhCN
