// Shared ISO 10628 quarter-turn/globe valve body — the open bow-tie every
// 2-way valve in this library uses; only the internal mechanism and
// actuator/handle on top differ per valve type.
export function BowtieBody() {
  return <>
    <polygon points="4,16 4,48 32,32" />
    <polygon points="60,16 60,48 32,32" />
  </>
}

export function FlowLine() {
  return <>
    <line x1="0" y1="32" x2="4" y2="32" />
    <line x1="60" y1="32" x2="64" y2="32" />
  </>
}

// Diaphragm actuator (pneumatic) — control valves.
export function DiaphragmActuator() {
  return <>
    <line x1="32" y1="16" x2="32" y2="6" />
    <path d="M 20,6 A 12 8 0 0 1 44,6 Z" />
  </>
}

// Handwheel actuator — manual quarter-turn valves (ball/butterfly).
export function Handwheel() {
  return <>
    <line x1="32" y1="16" x2="32" y2="6" />
    <line x1="24" y1="6" x2="40" y2="6" />
  </>
}
