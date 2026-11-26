"""
extraction_cli/status.py -- explicit extraction outcome states.

Phase 1: the pipeline had exactly one outcome. `_finish()` always emitted
`"stage": "done"`, and the Tauri shell marked the source COMPLETE whenever
`total_nodes > 0`. An LLM-B failure that produced zero edges therefore looked
identical to a clean run with a genuinely unconnected drawing.

Three states now, and they mean different things:

  SUCCESS  every page completed every stage
  PARTIAL  usable output, but at least one page lost a stage. Nodes are real
           CV+LLM-A output; edges may be geometry-only (never LLM-audited) or
           absent. NEVER reported as COMPLETE by the desktop shell.
  FAILED   no usable output for a page (LLM-A produced nothing, so there are
           no nodes to attach anything to).

`reason` names the first thing that went wrong, for the UI and the logs.
"""
from __future__ import annotations


class ExtractionStatus:
    SUCCESS = 'SUCCESS'
    PARTIAL = 'PARTIAL'
    FAILED  = 'FAILED'

    #: Worst-first, for rolling per-page results up into one run result.
    _SEVERITY = {SUCCESS: 0, PARTIAL: 1, FAILED: 2}

    @classmethod
    def worst(cls, statuses) -> str:
        """The most severe status in `statuses` (SUCCESS if empty)."""
        worst = cls.SUCCESS
        for s in statuses:
            if cls._SEVERITY.get(s, 2) > cls._SEVERITY[worst]:
                worst = s
        return worst

    @classmethod
    def rollup(cls, page_reports: list) -> tuple[str, str | None]:
        """Collapse per-page reports into (run_status, run_reason).

        A run is only SUCCESS when EVERY page succeeded. One bad page out of
        twenty is still a partial result — silently averaging that away is
        the exact failure mode this module exists to prevent.

        A run where every page FAILED is FAILED; a mix of FAILED and
        SUCCESS/PARTIAL pages is PARTIAL, because some pages did produce
        usable output.
        """
        if not page_reports:
            return cls.FAILED, Reason.NO_PAGES

        statuses = [p.get('status', cls.FAILED) for p in page_reports]
        if all(s == cls.SUCCESS for s in statuses):
            return cls.SUCCESS, None
        if all(s == cls.FAILED for s in statuses):
            run_status = cls.FAILED
        else:
            run_status = cls.PARTIAL

        # First non-SUCCESS page's reason is the headline.
        reason = next(
            (p.get('reason') for p in page_reports
             if p.get('status') != cls.SUCCESS and p.get('reason')),
            None,
        )
        return run_status, reason


class Reason:
    """Machine-readable `reason` codes paired with a non-SUCCESS status."""
    NO_PAGES                = 'NO_PAGES'
    SYMBOL_VERIFICATION_FAILED = 'SYMBOL_VERIFICATION_FAILED'   # LLM A
    LLM_VERIFICATION_FAILED = 'LLM_VERIFICATION_FAILED'         # LLM B
    CV_DETECTION_FAILED     = 'CV_DETECTION_FAILED'
    PERSIST_FAILED          = 'PERSIST_FAILED'


def _demo():
    """Self-check: the rollup rules above, which decide whether the desktop
    app is allowed to mark a source COMPLETE."""
    S, P, F = ExtractionStatus.SUCCESS, ExtractionStatus.PARTIAL, ExtractionStatus.FAILED
    r = ExtractionStatus.rollup

    assert r([{'status': S}]) == (S, None)
    assert r([{'status': S}, {'status': S}]) == (S, None)
    # One bad page cannot be averaged away into SUCCESS.
    assert r([{'status': S}, {'status': P, 'reason': Reason.LLM_VERIFICATION_FAILED}]) \
        == (P, Reason.LLM_VERIFICATION_FAILED)
    assert r([{'status': S}, {'status': F, 'reason': Reason.SYMBOL_VERIFICATION_FAILED}]) \
        == (P, Reason.SYMBOL_VERIFICATION_FAILED)
    assert r([{'status': F, 'reason': Reason.SYMBOL_VERIFICATION_FAILED}]) \
        == (F, Reason.SYMBOL_VERIFICATION_FAILED)
    assert r([]) == (F, Reason.NO_PAGES)
    assert ExtractionStatus.worst([S, P, S]) == P
    assert ExtractionStatus.worst([]) == S
    print('status.py self-check passed')


if __name__ == '__main__':
    _demo()
