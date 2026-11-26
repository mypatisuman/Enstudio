// IEC 60617 rotating-machine circle (motor "M" / generator "G") with top/
// bottom terminal leads — the base every motor/generator variant composes.
export function MachineCircle({ letter, color }: { letter: string; color: string }) {
  return <>
    <circle cx="32" cy="32" r="18" />
    <text x="32" y="33" textAnchor="middle" dominantBaseline="central"
      fontSize="16" fontWeight="700" stroke="none" fill={color}>{letter}</text>
    <line x1="32" y1="6" x2="32" y2="14" />
    <line x1="32" y1="50" x2="32" y2="58" />
  </>
}

// Standard cabinet/panel outline with a top terminal lead.
export function PanelBox() {
  return <>
    <rect x="12" y="14" width="40" height="38" />
    <line x1="32" y1="6" x2="32" y2="14" />
  </>
}
