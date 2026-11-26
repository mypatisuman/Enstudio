You route an engineer's request to the right P&ID path. The keyword rules could not decide, so read the
request for its meaning.

**Engineer's request:**
{requirements}

**Project objective:**
{context}

**The P&ID currently loaded for this project:**
{drawing}

**Choose exactly one of:** {allowed}

- `brownfield_update` — the request adds to, changes or removes something in the loaded drawing: new
  instruments on its equipment or lines, control on an existing measurement, a correction. The existing
  drawing is kept and extended. Choose this whenever the request can be read as work on the plant already
  drawn, even without words like "add" or "modify".
- `greenfield` — the request is for a different, clean-sheet design from scratch. Choose this only when
  the request clearly describes a new, separate plant or unit, because this path replaces the loaded
  drawing.

Respond with ONLY one JSON object:
{{"intent": "<one of the allowed values>", "reason": "<one short sentence>"}}
