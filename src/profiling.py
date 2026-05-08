"""
Pyroscope continuous profiling integration.

Set PYROSCOPE_SERVER_URL to point at your Pyroscope instance.
Set PYROSCOPE_ENABLED=false to disable (e.g. in unit tests).
"""

import os
import logging
from contextlib import contextmanager
from typing import Dict, Generator

logger = logging.getLogger(__name__)

PYROSCOPE_SERVER_URL = os.getenv("PYROSCOPE_SERVER_URL", "http://pyroscope:4040")
PYROSCOPE_ENABLED = os.getenv("PYROSCOPE_ENABLED", "true").lower() == "true"

_configured = False


def configure_profiler(app_name: str = "graph-creator", extra_tags: Dict[str, str] | None = None) -> None:
    global _configured
    if not PYROSCOPE_ENABLED:
        logger.info("Pyroscope profiling disabled (PYROSCOPE_ENABLED=false)")
        return

    import pyroscope

    tags = {"service": app_name}
    if extra_tags:
        tags.update(extra_tags)

    pyroscope.configure(
        app_name=app_name,
        server_address=PYROSCOPE_SERVER_URL,
        tags=tags,
    )
    _configured = True
    logger.info("Pyroscope profiling started → %s", PYROSCOPE_SERVER_URL)


@contextmanager
def profile_tag(tags: Dict[str, str]) -> Generator[None, None, None]:
    """Label a block of work in the Pyroscope flame graph."""
    if not _configured:
        yield
        return

    import pyroscope

    with pyroscope.tag_wrapper(tags):
        yield
