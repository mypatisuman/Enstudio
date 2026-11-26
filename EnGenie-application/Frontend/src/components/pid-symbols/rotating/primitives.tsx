// Shared ISO 10628 rotating-equipment fragments: circular casing, base
// support (skid legs), and horizontal suction/discharge nozzles — every
// pump/compressor/blower symbol below is this casing plus a different
// internal (impeller/lobe/piston/blade) and stroke color.
export function Casing({ r = 18 }: { r?: number }) {
  return <circle cx="32" cy="30" r={r} />
}

export function BaseSupport() {
  return <path d="M 20,48 L 16,58 L 48,58 L 44,48" />
}

export function SuctionNozzle() {
  return <line x1="6" y1="30" x2="14" y2="30" />
}

export function DischargeNozzle() {
  return <line x1="50" y1="30" x2="58" y2="30" />
}
