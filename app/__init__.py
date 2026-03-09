from __future__ import annotations

from pathlib import Path

# Compatibility shim: resolve `app.*` imports against `outreach_app/*`.
__path__ = [str(Path(__file__).resolve().parent.parent / "outreach_app")]
