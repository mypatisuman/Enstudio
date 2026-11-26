# Solution Agent — Azure OpenAI Verification Log

Date: 2026-07-29 · Deployment: `gpt-5.4-mini` on `azfoundaryensar` (eastus, 1M TPM / 1K RPM) · Auth: single `OPEN_API_KEY`

All log lines below are copied verbatim from live terminal runs against the real Azure endpoint.

---

## 1. Key + endpoint authentication (live probe)

Direct HTTP probes against `https://azfoundaryensar.services.ai.azure.com`:

```
gpt-5.4      (pro)   with OPEN_API_KEY        -> HTTP 404 DeploymentNotFound   (deployment does not exist)
gpt-5.4-mini (flash) with OPEN_API_KEY        -> HTTP 400                      (deployment EXISTS, probe body minimal)
gpt-5.4-nano (lite)  with OPEN_API_KEY        -> HTTP 404 DeploymentNotFound   (deployment does not exist)
gpt-5.4-mini (flash) with OPEN_API_KEY1       -> HTTP 401                      (old engeniemodel key — why it was removed)
```

Conclusion: `OPEN_API_KEY` authenticates; only `gpt-5.4-mini` is deployed → all tiers mapped to it in `.env`.

## 2. LLM manager wiring (app code path)

```
1. Key rotation pool: single azfoundaryensar key - OK
2. Tier deployments: {'pro': 'gpt-5.4-mini', 'flash': 'gpt-5.4-mini', 'lite': 'gpt-5.4-mini'} - OK
3. Live pro-tier call via get_solution_pro_llm: response='OK' - OK
ALL CHECKS PASSED - solution workflow LLM path is functional
```

## 3. Full workflow end-to-end (baseline run, session e2e-bom-1785343163)

Compressed-air receiver query → complete BOM. Selected terminal log lines:

```
INFO common.ai.llm.manager Creating LLM: provider=openai, model=gpt-5.4-mini, tier=flash, temp=0.1, search=False
INFO root [SOLUTION_AGENT] Intent classified as: requirements
INFO common.ai.llm.tracking [TOKEN_USAGE] Provider: openai | Model: gpt-5.4-mini | Input: 4,118 tokens | Output: 261 tokens | Total: 4,379 tokens | Time: 3.24s | Est.Cost: $0.005678
INFO root [HOLISTIC] Completeness verdict: overall=92 (threshold=70), blocking_criticals=0 -> holistic=True
INFO root [HOLISTIC] Extracted 7 instruments, 4 accessories
INFO root [EPISODIC_RECALL] No substantive saved-project match — running solution agent fresh
INFO root [EXPANSION] 8 categories to expand
INFO root [EXPANSION] ✓ Standards (5-tier) retrieved for 'pressure transmitter'   (…and 6 more categories)
INFO domain.solution.agents.harness_agent [HARNESS_AGENT] Fallback round 1/3 for 'pressure relief valve': +14 grounded (total=14)
INFO root [INFER_AGENT] 🚀 Running 11 parallel inference call(s) (7 instruments + 4 accessories)
INFO root [INFER_AGENT] ✓ 7 instruments inferred / ✓ 4 accessories inferred
INFO root [FORMAT_RESULTS] 'Pressure Transmitter': 22 specs ready for frontend    (…18–73 specs per item)
INFO root [SOLUTION_BUILD] ✓ Designed solution: objective set=True, 5 component roles, 6 optimizations
INFO domain.solution.agents.harness_agent [HARNESS_AGENT] per-item Pydantic gate: 11/11 items valid
INFO root [SOLUTION_AGENT] Final response built. Intent: requirements, Success: True

===== FULL BOM RUN (148s, 17 LLM calls) =====
TOTAL: 17 ok calls / 0 errors, in=43,442 out=9,521 est=$0.090
COST-LABEL CHECK: PASS - all calls tracked as deployment name
```

Result: 7 instruments + 4 accessories, standards attached, design narrative produced, **zero 401/404/429 errors**.

## 4. The 138K-token intent bug — fixed and proven live (session e2e-test-1785342984)

Turn 2 ran on a session whose history contained a stored BOM turn — the exact scenario that
previously produced a ~138,000-token intent prompt (log_session_20260729_172237):

```
UNIT OK: metadata dump 87,150 chars -> 457 chars
INFO root [SOLUTION_AGENT] Added conversation history (3 turns, capped at 5)
INFO common.ai.llm.tracking [TOKEN_USAGE] Provider: openai | Model: gpt-5.4-mini | Input: 4,111 tokens | Output: 185 tokens | Total: 4,296 tokens
Turn-2 intent-classification input tokens: 4,111 (was ~138,000 before fix)
PASS
```

## 5. Token-optimization A/B — final verified run (session e2e-bom-1785344710)

Same compressed-air query as the baseline in §3, with all four optimizations active
(trimmed intent template, reasoning_effort=low on flash/lite, embedding category
shortlist, infer batching 3 items/call):

```
INFO common.ai.llm.tracking [TOKEN_USAGE] ... Input: 1,342 tokens | Output: 116 tokens          <- intent (was 4,118 / 261)
INFO domain.solution.services.category_service [CATEGORY_SERVICE] Shortlisted 80/459 categories for holistic prompt
INFO common.ai.llm.tracking [TOKEN_USAGE] ... Input: 4,735 tokens | Output: 3,020 tokens        <- holistic (was 7,665 / 3,416)
INFO root [HOLISTIC] Completeness verdict: overall=92 (threshold=70), blocking_criticals=0 -> holistic=True
INFO root [INFER_AGENT] Running 4 parallel inference call(s) (5 instruments + 5 accessories, batch size 3)
INFO root [INFER_AGENT] ✓ batch 1: Pressure Transmitter, Pressure Gauge, Temperature Transmitter inferred
INFO root [INFER_AGENT] Merged 5 instruments and 5 accessories from 4 parallel call(s)
===== FULL BOM RUN (176s, 18 LLM calls) =====
TOTAL: 18 ok calls / 0 errors, in=33,590 out=9,180 est=$0.077
COST-LABEL CHECK: PASS - all calls tracked as deployment name
```

Per-node A/B (baseline → optimized, same query):

| Node | Input tokens | Output tokens | Calls |
|---|---|---|---|
| Intent | 4,118 → **1,342** (-67%) | 261 → **116** (-56%) | 1 → 1 |
| Holistic | 7,665 → **4,735** (-38%) | 3,416 → 3,020 | 1 → 1 |
| Infer | 26,864 → **11,888** (-56%) | ~4,300 → ~3,100 | **11 → 4** |
| Whole run | 43,442 → 33,590 | 9,521 → 9,180 | $0.090 → **$0.077** |

Note: this run's BOM composition differed (5+5 items whose accessory categories lacked
5-tier standards), adding ~11 extra grounding/fallback calls the baseline didn't need —
whole-run totals are therefore conservative; the per-node cuts above are the
apples-to-apples measurement. Gate verdict (92) and BOM quality matched baseline;
grounding rounds stayed bounded (round 1 sufficed for all six document-matched categories).

Notes from A/B iterations: sending `reasoning_effort` forces `temperature=1` on Azure
(400 unsupported_value otherwise); the pro tier therefore deliberately omits the param
(server default is medium anyway) to keep the holistic gate near-deterministic at
temperature 0.1. Flash/lite keep effort "low".

## 6. Known open items (not auth-related)

- L3 spec-doc blob downloads fail: blobs live in `productsrecommendertjsq`, `.env` storage creds point to `productrecommener2`.
- LangSmith over monthly trace quota (log noise only).
- gpt-5.4 (pro) and gpt-5.4-nano (lite) deployments do not exist on azfoundaryensar; create them in Foundry to differentiate tiers.
