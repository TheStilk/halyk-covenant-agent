"""Console setup so output survives a non-UTF-8 terminal.

On a Russian Windows install stdout defaults to cp1251, and the pipeline dies
with UnicodeEncodeError while *printing its own results* — after all the work is
done. Measured on this repo: a full run crashed on the "→" in the worst-cells
report, losing the summary entirely.

`print()` is currently the only observability this project has, so losing it
loses the run.
"""

from __future__ import annotations

import sys


def setup_console() -> None:
    """Force UTF-8 on stdout/stderr, replacing anything unencodable."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Redirected to something that cannot be reconfigured — the errors
            # handler below is the important half and is already lost, so just
            # carry on rather than taking the run down over console encoding.
            pass
