// Reusable vessel-body fragments shared by VerticalVessel, FlashDrum,
// Accumulator (vertical bodies) and HorizontalVessel, KnockoutDrum
// (horizontal bodies) — the actual ISA cylinder-with-dished-heads outline,
// so every "vertical pressure vessel" symbol stays geometrically identical
// and only the nozzle arrangement differs per equipment type.

export function VerticalBody({ x = 20, y = 16, w = 24, h = 32, capRy = 6 }:
  { x?: number; y?: number; w?: number; h?: number; capRy?: number }) {
  const capRx = w / 2
  const cx = x + capRx
  return <>
    <rect x={x} y={y} width={w} height={h} />
    <ellipse cx={cx} cy={y} rx={capRx} ry={capRy} />
    <ellipse cx={cx} cy={y + h} rx={capRx} ry={capRy} />
  </>
}

export function HorizontalBody({ x = 10, y = 22, w = 44, h = 18 }:
  { x?: number; y?: number; w?: number; h?: number }) {
  const capRx = h / 2
  const cy = y + h / 2
  return <>
    <rect x={x} y={y} width={w} height={h} />
    <ellipse cx={x} cy={cy} rx={capRx} ry={h / 2} />
    <ellipse cx={x + w} cy={cy} rx={capRx} ry={h / 2} />
  </>
}
