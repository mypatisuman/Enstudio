"""
bootstrap/browser.py — startup helper that opens the default browser once
the Flask dev server is listening.

Extracted from main.py (Phase 9), moved verbatim.
"""
from __future__ import annotations

import webbrowser


def open_browser():
    webbrowser.open('http://localhost:8000')
