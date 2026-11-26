import { Keyboard } from 'lucide-react'
import { SHORTCUTS } from './shortcuts'

/**
 * Renders the keyboard-shortcut reference from the centralized SHORTCUTS
 * config. Reusable so any dialog (Help today, a dedicated palette later) can
 * drop it in and stay in sync — rows are never hardcoded in JSX.
 */
export function ShortcutsSection() {
  return (
    <section>
      <div className="help-h"><Keyboard size={15} /> Keyboard shortcuts</div>
      <div className="kbd-groups">
        {SHORTCUTS.map(group => (
          <div key={group.category} className="kbd-group">
            <div className="kbd-group__title">{group.category}</div>
            {group.items.map((s, i) => (
              <div key={i} className="kbd-row">
                <span className="kbd-row__desc">{s.description}</span>
                <span className="kbd-row__keys">
                  {s.keys.split(' + ').map((k, j) => (
                    <kbd key={j} className="kbd">{k}</kbd>
                  ))}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  )
}
