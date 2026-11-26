// Canonical export filename suffixes — HomeScreen and ExportScreen each
// independently hardcoded these same suffixes (as exact-match strings and
// as .endsWith() predicates respectively) before this extraction.
export const EXPORT_SUFFIXES = {
  vids:    '_vids.yaml',
  ympl:    '.ympl',
  markdown:'_report.md',
  mermaid: '_pid.mmd',
  svg:     '_pid.svg',
  dxf:     '_pid.dxf',
  connectivity: '_connectivity.json',
  connectivity_hierarchy: '_connectivity_2_1_0.json',
} as const

export type ExportKind = keyof typeof EXPORT_SUFFIXES

// HomeScreen's per-pid exact filename check.
export function exportFilename(kind: ExportKind, pid: string): string {
  return `${pid}${EXPORT_SUFFIXES[kind]}`
}
