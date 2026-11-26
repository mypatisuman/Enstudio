# SKILL.md — DCS HMI Reading
# Status: PLACEHOLDER — Phase 2
# DO NOT USE until validation test passes
# See ES-IN-08 in REQUIREMENTS.md

## Validation Required Before Use

Run manual test first:
1. Upload a DCS HMI screenshot to Claude with this prompt:
   "Read this DCS HMI screen. List all equipment and instrument tags you can see. Return JSON."
2. Check accuracy — target >70% tag extraction
3. Record results in knowledge/validation/dcs_hmi_test.yaml
4. Only then write vendor skill files and activate this skill

## Vendor Files to Create (after validation)
- honeywell_experion.md
- emerson_deltav.md
- aveva_system_platform.md
- yokogawa_centum.md
- generic_dcs.md

## Key Difference from P&ID Reading
- Tag names are DISPLAYED on screen — read them exactly, do not infer
- Color = alarm state — record but do not confuse with topology
- PV/SP values shown = live data — use for range estimation only
