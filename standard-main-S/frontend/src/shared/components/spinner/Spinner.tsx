// Shared spin-ring indicator — was independently defined (byte-identical
// styling) in ExportScreen, IngestScreen, and DescribeScreen.
export function Spinner({ size = 13 }: { size?: number }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size, flexShrink: 0,
      border: '2px solid var(--bg-tertiary)', borderTopColor: 'var(--accent)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
    }} />
  )
}
