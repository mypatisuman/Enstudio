// Single source of truth for user-facing keyboard shortcuts. The Help dialog
// renders from this — future phases add a row here, nowhere else. Only list
// shortcuts that are actually wired up in code (no aspirational entries).

export interface Shortcut {
  keys: string        // display form, e.g. "Ctrl + K"
  description: string
}

export interface ShortcutGroup {
  category: string
  items: Shortcut[]
}

export const SHORTCUTS: ShortcutGroup[] = [
  {
    category: 'General',
    items: [
      { keys: 'Ctrl + K', description: 'Open Canvas Search' },
      { keys: 'Ctrl + Z', description: 'Undo' },
      { keys: 'Ctrl + Shift + Z', description: 'Redo' },
      { keys: 'Ctrl + Y', description: 'Redo' },
      { keys: 'Esc', description: 'Cancel selection / close dialog' },
    ],
  },
  {
    category: 'Canvas',
    items: [
      { keys: 'Delete', description: 'Delete selected node or pipe' },
      { keys: 'H', description: 'Align selected symbols horizontally' },
      { keys: 'V', description: 'Align selected symbols vertically' },
    ],
  },
  {
    category: 'Navigation',
    items: [
      { keys: 'Mouse Drag', description: 'Pan the canvas (view mode)' },
      { keys: 'Mouse Wheel', description: 'Zoom in / out' },
    ],
  },
  {
    category: 'Search',
    items: [
      { keys: '↑ / ↓', description: 'Move through search results' },
      { keys: 'Enter', description: 'Open the selected result' },
    ],
  },
]
