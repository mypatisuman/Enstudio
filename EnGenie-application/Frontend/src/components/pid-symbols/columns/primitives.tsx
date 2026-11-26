import { VerticalBody } from '../vessels/primitives'

// The tower shell — cylindrical body + dished heads — is the same ISO 10628
// primitive every vessel type already uses; columns are just a taller/
// narrower vessel with internals, so reuse it instead of redrawing it.
export function ColumnShell() {
  return <VerticalBody x={22} y={8} w={20} h={40} capRy={6} />
}

export function TopNozzle() {
  return <line x1="32" y1="8" x2="32" y2="2" />
}

export function BottomNozzle() {
  return <line x1="32" y1="54" x2="32" y2="60" />
}

// Horizontal dashed lines — tray convention (tray/stripper columns).
export function TrayLines({ rows = [16, 24, 32, 40, 48] }: { rows?: number[] }) {
  return <>{rows.map(y => <line key={y} x1="24" y1={y} x2="40" y2={y} strokeDasharray="3 2" />)}</>
}

// Stacked diamond mesh — packing convention (packed column / absorber).
export function PackingMesh({ rows = [16, 24, 32, 40] }: { rows?: number[] }) {
  return <>
    {rows.slice(0, -1).map((y, i) => {
      const y2 = rows[i + 1]
      return <g key={y}>
        <line x1="24" y1={y} x2="40" y2={y2} />
        <line x1="40" y1={y} x2="24" y2={y2} />
      </g>
    })}
  </>
}
