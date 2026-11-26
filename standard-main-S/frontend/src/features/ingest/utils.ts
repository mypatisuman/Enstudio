import { open } from '@tauri-apps/plugin-dialog'
import { toast } from 'sonner'
import { parseSqliteUtc } from '../../domain/formatting/datetime'

export function formatDate(iso: string) {
  if (!iso) return '—'
  try {
    const d = parseSqliteUtc(iso)
    if (!d) return iso.slice(0, 16).replace('T', ' ')
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }
  catch { return iso.slice(0, 16).replace('T', ' ') }
}

export async function openFileDialog(): Promise<string | null> {
  try {
    const result = await open({
      multiple:  false,
      directory: false,
      filters:   [{ name: 'P&ID files', extensions: ['pdf', 'png', 'jpg', 'jpeg'] }],
    })
    return typeof result === 'string' ? result : null
  } catch (err) {
    toast.error('File dialog error: ' + String(err))
    return null
  }
}
