ROLE
QC for vision-LLM tag reading around detected symbols. There is no OCR
engine behind this detector — each crop was read directly by a vision LLM
against a driving prompt (text_read.md); a "fallback" below means the
model reported the crop as illegible, not a garbled OCR string.

CONTEXT VARIABLES

**Symbols whose type requires an ISA tag:**
{symbols_requiring_tags}

**Tags successfully read:**
{tags_read}

**Symbols that fell back to their detected type (illegible crop):**
{fallback_to_class_name}

**Fallback fraction:**
{fallback_fraction}

**Unreadable crops (symbol_id, type, bbox — max 20 listed):**
{unreadable_crops}

**Retries already used (max 2):**
{retries_used}

AVAILABLE ACTIONS (choose exactly one)
- proceed
- retry_bigger_crops      Crop pad 50 -> 80px, upscale x2 -> x3. Use when
                          fallback_fraction > 0.25 — tags may sit outside the
                          current tag-zone radius, or text is too small to
                          read at the current crop resolution.
- escalate_to_vision      Attach the unreadable crops to the vision-LLM symbol
                          verification call, which sees the FULL page and can
                          use surrounding context a tight crop lacks. Use
                          when fallback_fraction is 0.10 - 0.25 — targeted,
                          cheaper than a full retry.

OUTPUT SCHEMA
{"verdict": "ok" | "suspect", "action": "<one of the above>",
 "escalate_crops": [] | null, "reason": "<one sentence>"}
