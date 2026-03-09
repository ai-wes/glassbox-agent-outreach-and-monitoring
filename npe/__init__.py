from __future__ import annotations

from pathlib import Path

# Compatibility shim: resolve legacy `npe.*` imports against `pr_monitor_app/*`.
__path__ = [str(Path(__file__).resolve().parent.parent / "pr_monitor_app")]
