"""
extraction_cli/parser.py -- argparse setup for the extract_cli command line.

Extracted from extract_cli.py's main() (Phase 11): the ArgumentParser
construction was pulled into its own build_parser() function (a mechanical
factoring -- main() previously built it inline) so parser.py can own "CLI
argument parsing" per the phase's module split, without changing the
parser's configuration, help text, or defaults in any way.
"""
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='CV + LLM verification pipeline for EngineeringStudio.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  cd C:\\standard\\studio
  python extract_cli.py "C:\\standard\\EngineeringHub\\EngineeringHub" ctp drawing.pdf

LLM provider and API key are configured via the app's Settings screen (saved
to studio.db), not environment variables.

Output is one JSON object per line (NDJSON).  Exit 0 = success, 1 = error.
""",
    )
    parser.add_argument('hub_path',    help='Path to the EngineeringHub directory')
    parser.add_argument('pid',         help='Project ID (must exist in studio.db)')
    parser.add_argument('pdf_path',    help='Path to the PDF or image file')
    # Phase 5: which sources row this file is. The desktop app already knows
    # it (run_extraction takes a source_id) but used to resolve it to a
    # filename and drop the identity at the process boundary, so extracted
    # nodes could not be attributed to the document they came from.
    parser.add_argument('--source-id', type=int, default=None,
                        help='sources.id for this file; scopes node/edge identity to the document')
    parser.add_argument('--llm-only',  action='store_true',
                        help='Skip CV detection; reuse cached symbol/line/text JSON and re-run LLM only')
    return parser
