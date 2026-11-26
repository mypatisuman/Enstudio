// Shared dashed system-boundary box — DCS/PLC/SIS are the same ISA
// "computer function" rectangle, differing only in default label, stroke
// color, and (for PLC) small I/O port ticks.
export function SystemBox({ ports = false }: { ports?: boolean }) {
  return <>
    <rect x="16" y="16" width="32" height="32" strokeDasharray="4 3" />
    <line x1="4" y1="24" x2="16" y2="24" strokeDasharray="3 2" />
    <line x1="4" y1="40" x2="16" y2="40" strokeDasharray="3 2" />
    <line x1="48" y1="24" x2="60" y2="24" strokeDasharray="3 2" />
    <line x1="48" y1="40" x2="60" y2="40" strokeDasharray="3 2" />
    {ports && <>
      <line x1="22" y1="16" x2="22" y2="10" />
      <line x1="42" y1="16" x2="42" y2="10" />
      <line x1="22" y1="48" x2="22" y2="54" />
      <line x1="42" y1="48" x2="42" y2="54" />
    </>}
  </>
}
