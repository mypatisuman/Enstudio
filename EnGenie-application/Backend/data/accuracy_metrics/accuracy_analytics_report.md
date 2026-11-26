# P&ID Accuracy & Agent Diagnostic Analytics Report
Generated: 2026-09-25T12:39:15.405442+00:00

## 1. Overall Performance
- **Total Evaluations Logged:** 2
- **Average Accuracy Score:** 60.9%

## 2. Performance by Agent Type
| Agent / Workflow | Total Runs | Avg Accuracy | Min | Max |
| :--- | :--- | :--- | :--- | :--- |
| `greenfield` | 1 | **60.9%** | 60.9% | 60.9% |
| `brownfield` | 1 | **60.9%** | 60.9% | 60.9% |

## 3. Top Recurring Structural Gaps
- **(4x)** Loop NA is incomplete: missing transmitter, controller, control valve
- **(4x)** Loop N is incomplete: missing controller, control valve
- **(2x)** N orphan node(s) with no piping or signal connections: [...]
- **(2x)** N edge(s) reference non-existent nodes.
- **(2x)** N node(s) not yet mapped into a plant subsystem.

## 4. Greenfield Agent Functionality & Prompt Improvements
- [ ] Ensure all synthesized instrument packages include explicit valve_between=[tag_a, tag_b] so control valves are inserted inline without becoming orphan nodes.
- [ ] Always call create_subsystem / assign_to_subsystem immediately after synthesizing equipment trains to maintain 100% hierarchy coverage.
- [ ] Verify suction and discharge line connectivity on all synthesized pumps (e.g. P-101A/B) to eliminate orphan pump ratings.

## 5. Brownfield Agent Functionality & Prompt Improvements
- [ ] When tying into existing header nozzles (TP-01 / TP-02), confirm line continuity with break_line rather than creating isolated branches.
- [ ] Preserve existing digitised tag numbers; do not rename existing transmitters during retrofit passes.
- [ ] In Qwen3-VL visual digitisation passes, prompt explicitly for field control valves (PV/TV/FV/LV) inline with process headers.
