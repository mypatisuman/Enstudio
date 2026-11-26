import type { IssueStatus } from './types';

const KEY = (pid: string) => `engenie_validation_status_${pid || 'default'}`;

export type StatusMap = Record<string, IssueStatus>;

export function loadStatuses(pid: string): StatusMap {
  try {
    const raw = localStorage.getItem(KEY(pid));
    return raw ? (JSON.parse(raw) as StatusMap) : {};
  } catch {
    return {};
  }
}

export function saveStatuses(pid: string, map: StatusMap): void {
  try {
    const trimmed: StatusMap = {};
    for (const [id, st] of Object.entries(map)) {
      if (st !== 'open') trimmed[id] = st;
    }
    localStorage.setItem(KEY(pid), JSON.stringify(trimmed));
  } catch {}
}
