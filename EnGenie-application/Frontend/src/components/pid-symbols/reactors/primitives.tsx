import { VerticalBody } from '../vessels/primitives'

// Reactor shell — same dished-head cylinder every vessel type uses.
export function ReactorShell() {
  return <VerticalBody x={20} y={16} w={24} h={32} capRy={8} />
}

export function TopNozzle() {
  return <line x1="32" y1="8" x2="32" y2="1" />
}

export function BottomNozzle() {
  return <line x1="32" y1="56" x2="32" y2="63" />
}

export function SideNozzle({ y, side = 'left' }: { y: number; side?: 'left' | 'right' }) {
  return side === 'left'
    ? <line x1="20" y1={y} x2="13" y2={y} />
    : <line x1="44" y1={y} x2="51" y2={y} />
}

// Agitator shaft + bowtie impeller — reused by CSTR and BatchReactor.
export function Impeller({ y = 43 }: { y?: number }) {
  return (
    <path d={`M 26,${y - 3} L 32,${y + 1} L 26,${y + 5} Z M 38,${y - 3} L 32,${y + 1} L 38,${y + 5} Z`} />
  )
}
