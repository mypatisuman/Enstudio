// Shared design tokens for the canvas — colors and stroke widths.
// ISANodes.tsx and CanvasScreen.tsx both read from here instead of
// hardcoding hex values so the palette stays consistent.

export const Theme = {
  canvas: '#0B1220',
  grid: '#1B2435',
  gridOpacity: 0.04,

  processPipe: '#D6DCE5',
  signalPipe: '#3b82f6',

  equipment: '#5EEB93',
  valve: '#F4B23A',
  instrument: '#A86DFF',
  offPage: '#64748B',

  selection: '#4DD7FF',
  hover: '#70DFFF',

  text: '#EDF2F7',
  textMuted: '#8B95A7',

  labelBackground: '#111827',
  labelBorder: '#263347',

  junction: '#E5E7EB',

  symbolFill: 'rgba(255,255,255,0.02)',
} as const

export const STROKE = {
  symbol: 2,
  pipe: 2,
  signal: 1.5,
  selection: 3,
} as const

export const RADIUS = {
  node: 6,
  label: 5,
  panel: 8,
  pipe: 5,
} as const

export const ANIMATION = {
  fast: 100,
  normal: 150,
  slow: 250,
} as const
