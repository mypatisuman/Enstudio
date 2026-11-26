"""
Report assembly for the UI / download.

Outputs:
  - build_report(): JSON bundle (run + results) — backs the JSON export endpoint
    and the client-side jsPDF download.
  - generate_pdf_bytes() / render_pdf(): a DETAILED server-side PDF via reportlab
    (optional dep). Per run it renders a header, executive summary, run metadata,
    LLM-metrics summary, per-model breakdown, and one rich CARD per test case
    (metrics strip, per-LLM-call breakdown table, response, validation, the
    agent's output fields, and a per-node workflow-steps table). The title adapts
    per agent (e.g. "Chat Agent Benchmark Report"). Returns (None, reason) when
    reportlab isn't installed so the API can answer 501.
"""
import io
from typing import Any

from common.monitoring.benchmarking import store


def build_report(run_id: str) -> dict[str, Any] | None:
    """Return {run, results} for a run, or None if the run does not exist."""
    run = store.get_run(run_id)
    if not run:
        return None
    return {"run": run, "results": store.get_results(run_id)}


def generate_pdf_bytes(run_id: str) -> tuple[bytes | None, str | None]:
    """Render a detailed run report to PDF bytes. (bytes, None) or (None, error)."""
    report = build_report(run_id)
    if report is None:
        return None, "Run not found"
    return render_pdf(report)


def render_pdf(report: dict[str, Any]) -> tuple[bytes | None, str | None]:
    """Render a {run, results} bundle to a detailed PDF. (bytes, None)|(None, err)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable, KeepTogether, PageBreak, Paragraph,
            SimpleDocTemplate, Spacer, Table, TableStyle)
    except Exception:
        return None, "reportlab is not installed (pip install reportlab)"

    run, results = report["run"], report.get("results", [])
    summary = run.get("summary", {}) or {}
    env = run.get("environment", {}) or {}
    agent_key = (run.get("agent_type") or "agent").lower()
    agent_title = agent_key.capitalize()
    CW = 18 * cm

    NAVY = colors.HexColor("#1A2B4A")
    BLUE = colors.HexColor("#2563EB")
    TEAL = colors.HexColor("#0D9488")
    GREEN = colors.HexColor("#16A34A")
    RED = colors.HexColor("#DC2626")
    GREY_BG = colors.HexColor("#F8FAFC")
    GREY_LT = colors.HexColor("#F1F5F9")
    GREY_BD = colors.HexColor("#CBD5E1")
    GREY_DK = colors.HexColor("#64748B")
    L_BLUE, L_GREEN, L_RED, L_TEAL, L_AMBER, L_PURPLE = (
        colors.HexColor(c) for c in ("#DBEAFE", "#DCFCE7", "#FEE2E2", "#CCFBF1", "#FEF3C7", "#EDE9FE"))
    HDR = TEAL if agent_key == "chat" else (BLUE if agent_key == "solution" else NAVY)

    def ps(name, **kw):
        return ParagraphStyle(name, **kw)
    S = {
        "h1": ps("h1", fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, spaceBefore=10, spaceAfter=6, leading=22),
        "h2": ps("h2", fontName="Helvetica-Bold", fontSize=12, textColor=BLUE, spaceBefore=10, spaceAfter=4, leading=15),
        "h3": ps("h3", fontName="Helvetica-Bold", fontSize=9.5, textColor=NAVY, leading=12),
        "sub": ps("sub", fontName="Helvetica", fontSize=9.5, textColor=GREY_DK, leading=13),
        "cell": ps("cell", fontName="Helvetica", fontSize=8.5, textColor=colors.HexColor("#1E293B"), leading=11),
        "cell_b": ps("cell_b", fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.HexColor("#1E293B"), leading=11),
        "cell_w": ps("cell_w", fontName="Helvetica-Bold", fontSize=8.5, textColor=colors.white, leading=11),
        "cell_r": ps("cell_r", fontName="Helvetica", fontSize=8.5, leading=11, alignment=TA_RIGHT),
        "stat_v": ps("stat_v", fontName="Helvetica-Bold", fontSize=18, textColor=NAVY, alignment=TA_CENTER, leading=22),
        "stat_l": ps("stat_l", fontName="Helvetica", fontSize=8, textColor=GREY_DK, alignment=TA_CENTER, leading=10),
        "resp": ps("resp", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#1E293B"),
                   backColor=GREY_BG, leftIndent=6, rightIndent=6, spaceAfter=3, leading=11),
    }

    def P(t, sty="cell"):
        return Paragraph(str(t), S[sty])

    def badge(label, bg, w=2.5 * cm, h=0.45 * cm):
        st = ps("_b", fontName="Helvetica-Bold", fontSize=7.5, textColor=colors.white, alignment=TA_CENTER)
        t = Table([[Paragraph(str(label), st)]], colWidths=[w], rowHeights=[h])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
        return t

    def table(data, widths, header_bg=NAVY, right_cols=None):
        right = set(right_cols or [])
        wrapped = []
        for ri, row in enumerate(data):
            wr = []
            for ci, c in enumerate(row):
                if isinstance(c, (Paragraph, Table)):
                    wr.append(c)
                elif ri == 0:
                    wr.append(Paragraph(str(c), S["cell_w"]))
                else:
                    wr.append(Paragraph(str(c), S["cell_r"] if ci in right else S["cell"]))
            wrapped.append(wr)
        t = Table(wrapped, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), header_bg), ("GRID", (0, 0), (-1, -1), 0.4, GREY_BD),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY_LT]),
        ]))
        return t

    def stat_cards(stats):
        w = CW / len(stats)
        cells = []
        for label, value, bg in stats:
            inner = Table([[P(value, "stat_v")], [P(label, "stat_l")]], colWidths=[w - 0.3 * cm])
            inner.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                       ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
            cells.append(inner)
        outer = Table([cells], colWidths=[w] * len(stats))
        outer.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
        return outer

    total = run.get("total_tests", 0) or (run.get("passed", 0) + run.get("failed", 0))
    pass_pct = f"{run.get('passed', 0) / total * 100:.0f}%" if total else "—"
    story: list = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(P(f"{agent_title} Agent Benchmark Report", "h1"))
    story.append(HRFlowable(width=CW, thickness=2, color=HDR, spaceAfter=6))
    story.append(P(f"Provider: <b>{env.get('provider', '-')}</b> &nbsp;·&nbsp; "
                   f"Suite: {run.get('suite_name', '-')} &nbsp;·&nbsp; "
                   f"Status: {str(run.get('status', '-')).upper()} &nbsp;·&nbsp; "
                   f"Run: {run.get('run_id', '-')}", "sub"))
    story.append(Spacer(1, 0.3 * cm))

    # ── Executive summary cards ───────────────────────────────────────────────
    story.append(stat_cards([
        ("Tests", total, L_BLUE),
        ("Passed", run.get("passed", 0), L_GREEN),
        ("Failed", run.get("failed", 0), L_RED if run.get("failed", 0) else GREY_LT),
        ("Pass Rate", pass_pct, L_TEAL),
        ("Total Cost", f"${summary.get('total_cost_usd', 0):.4f}", L_AMBER),
        ("Duration", f"{run.get('duration_ms', 0) / 1000:.0f}s", L_PURPLE),
    ]))
    story.append(Spacer(1, 0.4 * cm))

    # ── LLM metrics summary ───────────────────────────────────────────────────
    story.append(P("LLM Metrics Summary", "h2"))
    lm_rows = [
        ["Total LLM Calls", summary.get("total_llm_calls", 0), "Total Tokens", f"{summary.get('total_tokens', 0):,}"],
        ["Input Tokens", f"{summary.get('total_input_tokens', 0):,}", "Output Tokens", f"{summary.get('total_output_tokens', 0):,}"],
        ["Total Cost (USD)", f"${summary.get('total_cost_usd', 0):.6f}", "Avg Tokens / Test", f"{summary.get('avg_tokens_per_test', 0):.0f}"],
        ["Avg LLM Calls / Test", f"{summary.get('avg_llm_calls_per_test', 0):.2f}", "Avg Response Time", f"{summary.get('avg_response_time_ms', 0):.0f} ms"],
    ]
    lt = Table(lm_rows, colWidths=[4.5 * cm, 4.5 * cm, 4.5 * cm, 4.5 * cm])
    lt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), HDR), ("BACKGROUND", (2, 0), (2, -1), HDR),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white), ("TEXTCOLOR", (2, 0), (2, -1), colors.white),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("GRID", (0, 0), (-1, -1), 0.4, GREY_BD),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, GREY_LT]),
        ("ROWBACKGROUNDS", (3, 0), (3, -1), [colors.white, GREY_LT]),
    ]))
    story.append(lt)
    story.append(Spacer(1, 0.3 * cm))

    # ── Per-model breakdown ───────────────────────────────────────────────────
    models = summary.get("model_breakdown", {}) or {}
    if models:
        story.append(P("Per-Model LLM Breakdown", "h2"))
        rows = [["Model", "Provider", "Calls", "Total Tokens", "Cost (USD)"]]
        for name, m in models.items():
            rows.append([name, m.get("provider", "-"), m.get("llm_calls", 0),
                         f"{m.get('total_tokens', 0):,}", f"${m.get('total_cost_usd', 0):.6f}"])
        story.append(table(rows, [5.5 * cm, 3 * cm, 2.5 * cm, 4 * cm, 3 * cm], header_bg=HDR, right_cols={2, 3, 4}))
    story.append(PageBreak())

    # ── Per-test cards ────────────────────────────────────────────────────────
    story.append(P("Test Case Results", "h1"))
    story.append(HRFlowable(width=CW, thickness=2, color=HDR, spaceAfter=6))

    for idx, tc in enumerate(results, 1):
        status = tc.get("status", "failed")
        lm = tc.get("llm_metrics", {}) or {}
        out = tc.get("output", {}) or {}
        val = tc.get("validation", {}) or {}
        ok = status == "passed"
        pass_bg, pass_col = (L_GREEN, GREEN) if ok else (L_RED, RED)

        # Header chip row
        hdr = Table([[badge(f"#{idx}", HDR, w=0.9 * cm),
                      P(f"<b>{tc.get('test_id', '')}</b> &nbsp;·&nbsp; {tc.get('test_name', '')}", "h3"),
                      badge("PASS" if ok else "FAIL", pass_col, w=1.5 * cm)]],
                    colWidths=[1.1 * cm, 14.4 * cm, 2.5 * cm])
        hdr.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), pass_bg), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                                 ("ALIGN", (2, 0), (2, 0), "RIGHT"), ("RIGHTPADDING", (2, 0), (2, 0), 8),
                                 ("LINEBELOW", (0, 0), (-1, -1), 1.2, pass_col)]))

        # Metrics strip
        ms_rows = [
            ["Time", f"{tc.get('execution_time_ms', 0):.0f} ms", "LLM Calls", lm.get("total_llm_calls", 0), "Tokens", f"{lm.get('total_tokens', 0):,}"],
            ["Input", f"{lm.get('total_input_tokens', 0):,}", "Output", f"{lm.get('total_output_tokens', 0):,}", "Cost", f"${lm.get('total_cost_usd', 0):.6f}"],
        ]
        mw = CW / 6
        mt = Table(ms_rows, colWidths=[mw, mw, mw, mw, mw, mw])
        mt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), NAVY), ("BACKGROUND", (2, 0), (2, -1), NAVY), ("BACKGROUND", (4, 0), (4, -1), NAVY),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.white), ("TEXTCOLOR", (2, 0), (2, -1), colors.white), ("TEXTCOLOR", (4, 0), (4, -1), colors.white),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"), ("FONTNAME", (4, 0), (4, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.4, GREY_BD),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, GREY_LT]), ("ROWBACKGROUNDS", (3, 0), (5, -1), [colors.white, GREY_LT]),
        ]))

        card = [hdr, mt]

        # LLM call breakdown
        cb = lm.get("llm_call_breakdown", [])
        if cb:
            cb_rows = [["#", "Purpose", "Model", "In", "Out", "Total", "ms", "Cost"]]
            for c in cb:
                cb_rows.append([c.get("call_number", "?"), str(c.get("purpose", "—"))[:22], str(c.get("model", "?"))[:18],
                                f"{c.get('input_tokens', 0):,}", f"{c.get('output_tokens', 0):,}", f"{c.get('total_tokens', 0):,}",
                                f"{c.get('response_time_ms', 0):.0f}", f"${c.get('cost_usd', 0):.6f}"])
            card.append(Spacer(1, 0.15 * cm))
            card.append(P("<b>LLM CALL BREAKDOWN</b>", "cell_b"))
            card.append(table(cb_rows, [0.7 * cm, 3.4 * cm, 3.4 * cm, 1.8 * cm, 1.8 * cm, 2 * cm, 1.6 * cm, 3.3 * cm],
                              header_bg=BLUE, right_cols={3, 4, 5, 6, 7}))

        # Two-column: left = response + validation; right = output fields + workflow steps
        resp = (out.get("response") or "").strip()
        resp = (resp[:350] + " …") if len(resp) > 350 else (resp or "— (empty response)")
        left = [P("<b>AGENT RESPONSE</b>", "cell_b"), Spacer(1, 0.08 * cm), P(resp, "resp"), Spacer(1, 0.15 * cm),
                P("<b>VALIDATION</b>", "cell_b"), Spacer(1, 0.08 * cm)]
        if val.get("failed_checks"):
            left.append(P(f"<font color='#DC2626'>✗ Failed:</font> {'; '.join(val['failed_checks'])[:200]}", "cell"))
        else:
            left.append(P("<font color='#16A34A'>✓ All checks passed</font>", "cell"))
        if tc.get("error"):
            left.append(P(f"<font color='#DC2626'>Error: {str(tc['error'])[:200]}</font>", "cell"))

        right = []
        if agent_key == "chat":
            cls = out.get("classification", out.get("intent", "—"))
            cls_col = {"VALID_NEW_QUERY": TEAL, "VALID_FOLLOWUP": BLUE, "INVALID": RED}.get(cls, GREY_DK)
            right += [P("<b>CLASSIFICATION</b>", "cell_b"), Spacer(1, 0.08 * cm), badge(cls, cls_col, w=4 * cm, h=0.5 * cm), Spacer(1, 0.15 * cm)]
            right.append(table([["Field", "Value"], ["Intent", out.get("intent", "—")],
                                ["Response Length", f"{out.get('response_length', 0)} chars"]],
                               [4 * cm, 4.4 * cm], header_bg=TEAL))
        else:
            fields = [["Field", "Value"], ["Intent", out.get("intent", "—")]]
            if agent_key == "search":
                fields += [["Products Found", out.get("results_count", 0)], ["Missing Fields", "Yes" if out.get("has_missing_fields") else "No"]]
            elif agent_key == "solution":
                fields += [["Instruments", out.get("instruments_count", 0)], ["Standards Applied", out.get("standards_applied", False)]]
            fields.append(["Response Length", f"{out.get('response_length', 0)} chars"])
            right.append(table(fields, [4 * cm, 4.4 * cm], header_bg=BLUE))

        steps = out.get("workflow_steps_analysis", [])
        if steps:
            right.append(Spacer(1, 0.15 * cm))
            right.append(P("<b>WORKFLOW STEPS</b>", "cell_b"))
            srows = [["#", "Node", "What it did"]]
            for s in steps:
                srows.append([s.get("step_num", "?"), s.get("node", "?"), s.get("description", "")])
            right.append(table(srows, [0.7 * cm, 3.3 * cm, 4.4 * cm], header_bg=NAVY))

        body = Table([[Table([[x] for x in left], colWidths=[8.7 * cm]),
                       Table([[x] for x in right], colWidths=[8.7 * cm])]], colWidths=[9 * cm, 9 * cm])
        body.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, GREY_BD), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                  ("BACKGROUND", (1, 0), (1, -1), GREY_LT)]))
        card += [body, Spacer(1, 0.35 * cm)]
        story.append(KeepTogether(card))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"{agent_title} Benchmark {run.get('run_id', '')}",
                            leftMargin=1.4 * cm, rightMargin=1.4 * cm, topMargin=1.4 * cm, bottomMargin=1.4 * cm)
    doc.build(story)
    return buf.getvalue(), None
