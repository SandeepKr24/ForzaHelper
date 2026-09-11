"""Deployment entrypoint.

Vercel's Python framework preset looks for a top-level `app` in one of a fixed
set of filenames at the project root; this is that file. It adds src/ to the
path rather than relying on the package being installed, so the same entrypoint
works locally and in the build.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from forzahelper.api import app  # noqa: E402

__all__ = ["app"]
