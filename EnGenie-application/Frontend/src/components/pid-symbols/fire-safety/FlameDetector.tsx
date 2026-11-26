import { SymbolSvg } from './base'
import type { PidSymbolProps } from './types'

// Flame detector — wall/pole-mount housing (not a ceiling dome, since flame
// detectors are line-of-sight mounted) with an internal flame mark and a
// field-of-view cone.
export default function FlameDetector(props: PidSymbolProps) {
  return (
    <SymbolSvg {...props}>
      <rect x="14" y="20" width="20" height="20" />
      <path d="M 24,26 Q 28,30 24,34 Q 20,30 24,26" />
      <path d="M 34,24 L 50,16 M 34,36 L 50,44" />
    </SymbolSvg>
  )
}
