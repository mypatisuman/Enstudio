# P&ID digitiser evaluation

Hand-made ground truth and scorers for the brownfield vision digitiser
(`domain/solution/services/brownfield_vision_service.py`). Live runs call the
configured vision models and spend provider credit.

| File | Purpose |
|---|---|
| `truth_manual.py` | Tags printed on each test drawing (pid3, 13-16, 18-20), symbol types, inferred valves, line labels |
| `conn_truth.py` | Connections of pid13 and pid15: required links, optional links, flags by position |
| `live_any.py` / `run.sh` | Full live digitisation of a drawing -> `runs/<pid>_analysis.json` |
| `read_bench.py` | Reading pass only, with any model: `python read_bench.py pid15 google/gemini-3.7-flash G` |
| `connect_eval.py` | Connection passes only, on the tags of a finished run |
| `score_manual.py` | Tag recall / precision / symbol types: `python score_manual.py pid13` |
| `score_live.py` | Connection F1 against `conn_truth`: `python score_live.py pid13` |
| `score_review.py` | Share of the run's errors that land in its review queue: `python score_review.py pid13` |
| `synth/generate.py`, `bench_synth.py` | Synthetic drawings with exact truth; live benchmark over them (see below) |

Drawings are read from `PID-Images/PID-Images/<pid>.png` (synthetic ones from `synth/out/`). `runs/` holds outputs (not source).

## Models (benchmark of 2026-10-04, pid13 / pid15)

Reading pass alone (no verification), tags found / correct:

| Model | pid13 | pid15 |
|---|---|---|
| anthropic/claude-sonnet-5-5 | 100 / 100 | 100 / 100 |
| google/gemini-3.7-flash | 98.7 / 98.7 | 100 / 100 |
| google/gemini-3.1-pro | 100 / 97.5 | 100 / 98.6 |
| Qwen3-VL-30B (previous default, with verification) | 100 / 100 | 88.7 / 96.9 |

Connection pass on the same tags (F1):

| Model | pid13 | pid15 |
|---|---|---|
| google/gemini-3.1-pro | 82.7 | 77.9 |
| anthropic/claude-sonnet-5-5 | 75.0 | 78.6 |
| google/gemini-3.7-flash (after the reasoning-token fix) | 84.8 | not run (402) |
| Qwen3-VL-235B (previous default) | 67.2 | 58.8 |
| either of Gemini Pro / Claude | 81.6 | 81.4 |
| both agree (precision) | 91% | 100% |

Gemini Flash reasons before it answers and its hidden reasoning counts against the reply cap;
before `BROWNFIELD_THINKING_ALLOWANCE` (default 6000 extra tokens for thinking models) its
connection replies were cut off after a few words.

Full run with the settings below (pid13R5, 2026-10-04): tags 78/78 found and correct, connections
F1 85.7% (was 74.6% with the Qwen defaults), 145 calls in 121 s; the review queue (32 items) held
9 of the 10 wrong links and pointed at 6 of the 12 missed ones. pid15 was stopped by the spending limit.

Box conventions differ by model (Gemini y-first, Claude pixels); the service converts them
(`_model_family`, `_to_norm`). Settings to try in a full run:

```
BROWNFIELD_READ_MODEL=anthropic/claude-sonnet-5-5
BROWNFIELD_VERIFY_MODEL=anthropic/claude-sonnet-5-5
BROWNFIELD_SYMBOL_MODEL=anthropic/claude-sonnet-5-5
BROWNFIELD_CONNECT_MODEL=google/gemini-3.1-pro
BROWNFIELD_CONNECT_SECOND_MODEL=anthropic/claude-sonnet-5-5
```

## Synthetic drawings (`synth/`)

Drawn P&IDs with exact truth, for measuring changes on more than two sheets. Each
sheet holds two process trains (flags, hand valves, a flow loop, a level loop, a
relief valve, a pump, an exchanger, a temperature loop) and a title block.

```
python synth/generate.py --level clean --count 3 --seed 1     # -> synth/out/sync001.png + .json ...
python synth/generate.py --level dense --count 3 --seed 1     # synd...: more, closer symbols
python synth/generate.py --level scan  --count 3 --seed 1     # syns...: skew, blur, fade, noise
python bench_synth.py [sync001 synd001 ...]                   # live digitise + score all (spends credit)
```

- Names are `sync` (clean), `synd` (dense) and `syns` (scan-like) plus a number. The
  same seed gives the same sheets, so `synth/out/` can be deleted and rebuilt.
- `<name>.json` holds `tags` and `connections`. `truth_manual.py` and `conn_truth.py`
  load them, so `live_any.py`, `read_bench.py`, `connect_eval.py` and the three scorers
  take a synthetic name like a real one.
- A perfect analysis scores 100% tags and 100% links (`tests/test_synthetic_pids.py`).
- Synthetic sheets are cleaner and more regular than real ones. Use them to compare
  models and settings and to catch regressions. Accuracy claims still need pid13 / pid15.

## Input quality step (`domain/solution/services/drawing_input.py`)

Before any reading pass, the upload goes through four steps:

1. A PDF page is rendered at 6000 px, and a phone photo's stored rotation is applied.
2. The page is normalised to grey with a white background: negatives are inverted,
   faint scans get their contrast stretched, and the long side is resized to 4800-8000 px.
3. One cheap vision call on the whole page asks: is it a P&ID, how much must it be
   turned to read upright, and is the text legible?
4. A gate stops an upload that is not a P&ID or cannot be read before any money is
   spent on it. Borderline drawings get a warning instead.

These are plain image operations plus one LLM call: no OCR or pixel analysis. What was
done is recorded in `analysis.stats.input`.

| Setting | Default | |
|---|---|---|
| `BROWNFIELD_INPUT_PREP` | on | the whole step |
| `BROWNFIELD_PROBE_MODEL` | reading model | model for the whole-page check |
| `BROWNFIELD_QUALITY_GATE` | `block` | `block`, `warn` (never stop) or `off` |
| `BROWNFIELD_MIN_LONG_SIDE` / `MAX_LONG_SIDE` / `PDF_LONG_SIDE` | 4800 / 8000 / 6000 | resolution targets |
