ROLE
QC for vision-LLM tiled symbol detection on one P&ID page. There is no
trained model behind this detector — every tile was read by a vision LLM
against a driving prompt (symbol_detect.md); "confidence" below is that
model's own calibrated self-report, not a softmax score.

CONTEXT VARIABLES

**Symbols found:**
{symbols_found}

**Page ink density (dark pixel fraction):**
{page_ink_density}

**Fraction of detections with confidence < 0.45:**
{low_conf_fraction}

**Cross-class overlapping pairs (IoU > 0.45, different classes):**
{cross_class_overlap_pairs}

**Stricter re-scan prompt already used this run:**
{reprompt_used}

**Confidence threshold used:**
{conf_used}

**Retries already used (max 2):**
{retries_used}

AVAILABLE ACTIONS (choose exactly one; "proceed" is always safe)
- proceed
- retry_lower_conf        Lower the confidence floor to 0.25. Use when
                          symbols_found is far below what the ink density
                          implies and the threshold is still 0.35.
- retry_reprompt          Re-run every tile with a stricter re-scan
                          instruction appended to the driving prompt
                          (widened edge-tolerance, more conservative on
                          exclusions). Use when low_conf_fraction > 0.5,
                          suggesting the model under-detected rather than
                          mistyped — but only if reprompt_used is not
                          already true this run (it's a one-shot escalation,
                          not a toggle to bounce between).
- run_cross_class_dedup   Use when cross_class_overlap_pairs > 8. Note this
                          preempts dedup work the vision LLM would otherwise do.

OUTPUT SCHEMA
{"verdict": "ok" | "suspect", "action": "<one of the above>",
 "reason": "<one sentence>"}
