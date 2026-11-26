export interface ScanRecord {
  filename: string
  model: string
  provider: string
  tokens_in: number
  tokens_out: number
  cost_usd: number
  timestamp: string
  pass: number
}

export interface UsageRecord {
  pid: string
  name: string
  total_tokens: number
  total_cost: number
  last_scan: string
  scans: ScanRecord[]
}
