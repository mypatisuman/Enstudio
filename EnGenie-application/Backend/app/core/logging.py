"""
Centralized logging configuration for the Engenie backend.
"""
import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured format."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.setLevel(log_level)
    # Avoid duplicate handlers on repeated calls
    if not root.handlers:
        root.addHandler(handler)

    # Quieten noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "azure", "google"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # pypdf logs unsupported-CMap notices (e.g. Korean /UniKS-UTF16-H) at ERROR
    # once per page — dozens of lines per PDF with no actionable content; the
    # extraction fallbacks already handle degraded text.
    logging.getLogger("pypdf._cmap").setLevel(logging.CRITICAL)
