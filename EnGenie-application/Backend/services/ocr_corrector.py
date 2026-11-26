"""
ISA-5.1 OCR Auto-Correction — ported from Engram-Main.

Fixes common character substitutions that OCR mis-reads in instrument tags:
  O→0, I→1, l→1, S→5, Z→2, B→8, em-dash→hyphen
"""

import re
import logging

logger = logging.getLogger(__name__)

_ISA_TAG_RE = re.compile(
    r'^([A-Z]{1,5})'
    r'[\s\-_—–]?'
    r'(\d{2,6})'
    r'([A-Z]?)$',
    re.IGNORECASE,
)

_DIGIT_SUBS: dict = {
    'O': '0', 'o': '0',
    'I': '1', 'l': '1',
    'S': '5',
    'Z': '2',
    'B': '8',
}

_SEP_RE = re.compile(r'[—–‒―—–‒―]')

_SKIP_RE = re.compile(
    r'^(\d+[\.\-]?\d*\s*(PSI|BAR|°C|°F|GPM|LPM|MM|M3|IN|FT)|'
    r'REV\s+\w+|'
    r'SHEET\s+\d+|'
    r'DWG\s*\w+)',
    re.IGNORECASE,
)


def correct_isa_tag(text: str) -> tuple:
    if not text or not isinstance(text, str):
        return text, False
    original = text.strip()
    if _SKIP_RE.match(original):
        return original, False
    normalised = _SEP_RE.sub('-', original)
    m = _ISA_TAG_RE.match(normalised.strip())
    if not m:
        return original, False
    prefix = m.group(1).upper()
    digits_fixed = ''.join(_DIGIT_SUBS.get(ch, ch) for ch in m.group(2))
    suffix = m.group(3).upper()
    corrected = f"{prefix}-{digits_fixed}{suffix}"
    was_corrected = corrected != original
    if was_corrected:
        logger.debug("[ocr_corrector] '%s' → '%s'", original, corrected)
    return corrected, was_corrected


def batch_correct(detections: list) -> tuple:
    correction_count = 0
    result = []
    for det in detections:
        raw_text = det.get('text', '')
        corrected, was_corrected = correct_isa_tag(raw_text)
        if was_corrected:
            det = dict(det)
            det['original_text'] = raw_text
            det['text'] = corrected
            det['ocr_corrected'] = True
            correction_count += 1
        result.append(det)
    if correction_count:
        logger.info("[ocr_corrector] Auto-corrected %d / %d OCR detections",
                    correction_count, len(detections))
    return result, correction_count
