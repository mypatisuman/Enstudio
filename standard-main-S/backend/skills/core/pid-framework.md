# PlantSketch — Editor Rendering Rules

Rendering rules that govern which nodes appear on the editor canvas
and how unconnected / non-physical nodes are displayed.

---

## 1. Non-Physical ISA Filter — `classify_node()` in engine.py

Non-physical tags are alarm outputs, relay/compute blocks, and operator-output
tags that live in DCS/SIS logic but have **no physical symbol** on the P&ID.

`classify_node()` returns `physical = false` for:

| Rule | Tag pattern | Examples |
|---|---|---|
| Second letter Y | prefix[1] == 'Y' | FY, PY, TY, LY, AY |
| Alarm suffix | prefix ends in AH, AL, AHH, ALL | FAH, FAL, FAHH, FALL, PAH, PAHH |
| Non-physical prefix | starts with HS, HC, HIC, AL, AH, XA, YA, ZA | AH-101, HS-201 |

Non-physical nodes: `pid_layer = 0`, `physical = false`.
Still included in VIDS/YMPL exports — excluded from the editor canvas only.

---

## 2. Placeholder / Incomplete Filter

Nodes with `quality = placeholder` or `quality = incomplete` are **not** sent to the editor
and are logged in the excluded count. They still appear in VIDS/YMPL exports.

---

## 3. Server Filter — `GET /api/editor/<pid>` in main.py

After `classify_node()`, exclude nodes where:
- `physical = false`  → counted in `excluded.non_physical`
- `quality` is `placeholder` or `incomplete` → counted in `excluded.placeholder`

Response includes: `{ excluded: { non_physical: N, placeholder: M } }`

Status bar shows: `752 blocks (52 excluded) · 1104 connections`

---

## 4. Unconnected Visibility — `applyLayers()` in editor.html

A node is **unconnected** when it has zero edges (not referenced by any from/to).

### "Show Unconnected" toggle (Layers panel, OFF by default)

**When OFF:**
- Unconnected nodes that are **Layer 1 equipment** → visible with dashed orange border + `?` marker
- Unconnected nodes that are **not** Layer 1 equipment → hidden (`opacity: 0`)

**When ON:**
- All nodes visible per standard layer rules
- Unconnected nodes rendered at **50% opacity**

### View presets

| Preset | Layers | show_unconnected |
|---|---|---|
| Process Only | equipment + pipes | OFF |
| Process + Control | + connected instruments + signals | OFF |
| Full P&ID | all layers | ON (unconnected at 50%) |

---

## 5. Flagged Equipment — `renderNode()` in editor.html

Every node SVG group contains two always-rendered but CSS-hidden elements:

- `.node-unconnected-border` — dashed orange rect (`stroke:#f97316`, `stroke-dasharray:4,2`)
- `.node-unconnected-marker` — orange `?` text above the tag label

Both are shown via CSS only when the parent `<g>` has class `unconnected-flag`.
`applyLayers()` adds/removes `unconnected-flag` based on connection status and
`layerState.show_unconnected`.

---

## 6. Layer Checkbox

Layers panel (bottom of left palette) has 11 checkboxes:

```
☑ Process Equipment
☑ Control Valves
☑ Instruments
☑ Motors
☐ Hand Valves
☐ Check Valves
☐ Relief Valves
☐ Isolation Valves
☑ Signal Lines
☑ Process Pipes
─────────────────
☐ Show Unconnected    ← added by this spec, OFF by default
```

Toggling "Show Unconnected" calls `toggleLayer('show_unconnected', checked)`
which calls `applyLayers()`.
