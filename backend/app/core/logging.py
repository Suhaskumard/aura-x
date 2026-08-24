"""
Logging configuration.

IMPORTANT: never pass secrets (e.g. GITHUB_TOKEN, clone URLs containing
credentials) into log calls. Structured errors raised by the GitHub
integration layer must already have secrets stripped before they reach
this logger.
"""

import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. under a test runner or reloader).
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s :: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)
