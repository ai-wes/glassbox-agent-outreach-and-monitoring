from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import orjson

from app.core.config import settings
from app.utils.crypto import sha256_hex
from app.utils.files import sha256_file

logger = logging.getLogger(__name__)
_EID_RE = re.compile(r"^EID-[A-Z0-9]+-(\d{6})$")


@dataclass
class ToolCallRecord:
    ts: str
    tool: str
    input: dict
    output: dict | None
    error: str | None
    risk_tier: int
    external_effect: bool
    evidence_ids: list[str]


class EvidencePack:
    """
    Evidence pack on filesystem.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.root = Path(settings.artifacts_dir).resolve() / f"run_{run_id}"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "inputs").mkdir(exist_ok=True)
        (self.root / "outputs").mkdir(exist_ok=True)
        (self.root / "artifacts").mkdir(exist_ok=True)

        self._tool_calls_path = self.root / "tool_calls.jsonl"
        self._manifest_path = self.root / "run_manifest.json"
        self._index_path = self.root / "evidence_index.json"
        self._created_at = datetime.utcnow()

        if not self._manifest_path.exists():
            self.write_manifest({"run_id": run_id, "created_at": self._created_at.isoformat() + "Z"})
        if not self._index_path.exists():
            self._index_path.write_text(
                json.dumps({"run_id": run_id, "created_at": self._created_at.isoformat() + "Z", "artifacts": []}, indent=2, sort_keys=True),
                encoding="utf-8",
            )

        self._eid_seq = self._infer_existing_eid_seq()

    @property
    def uri(self) -> str:
        return str(self.root)

    def _infer_existing_eid_seq(self) -> int:
        mx = 0
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            for a in data.get("artifacts", []) or []:
                m = _EID_RE.match(str(a.get("evidence_id", "")))
                if m:
                    mx = max(mx, int(m.group(1)))
        except Exception:
            logger.exception("Failed scanning evidence_index.json")

        if self._tool_calls_path.exists():
            try:
                for line in self._tool_calls_path.read_bytes().splitlines():
                    if not line.strip():
                        continue
                    obj = orjson.loads(line)
                    for eid in obj.get("evidence_ids", []) or []:
                        m = _EID_RE.match(str(eid))
                        if m:
                            mx = max(mx, int(m.group(1)))
            except Exception:
                logger.exception("Failed scanning tool_calls.jsonl")
        return mx

    def next_evidence_id(self, kind: str) -> str:
        self._eid_seq += 1
        return f"EID-{kind.upper()}-{self._eid_seq:06d}"

    def write_json(self, rel_path: str, payload: Any) -> Path:
        path = (self.root / rel_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS))
        return path

    def write_text(self, rel_path: str, text: str) -> Path:
        path = (self.root / rel_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def append_tool_call(self, record: ToolCallRecord) -> None:
        with self._tool_calls_path.open("ab") as f:
            f.write(orjson.dumps(asdict(record)) + b"\n")

    def write_manifest(self, updates: dict) -> None:
        manifest = {}
        if self._manifest_path.exists():
            try:
                manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
        manifest.update(updates)
        manifest["updated_at"] = datetime.utcnow().isoformat() + "Z"
        self._manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    def add_artifact(self, *, evidence_id: str, type: str, path: Path, sha256: str, metadata: dict | None = None) -> None:
        metadata = metadata or {}
        rel = str(path.resolve().relative_to(self.root))
        entry = {
            "evidence_id": evidence_id,
            "type": type,
            "relpath": rel,
            "sha256": sha256,
            "metadata": metadata,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception:
            data = {"run_id": self.run_id, "created_at": self._created_at.isoformat() + "Z", "artifacts": []}
        artifacts = list(data.get("artifacts", []) or [])
        if any(a.get("evidence_id") == evidence_id and a.get("relpath") == rel for a in artifacts):
            return
        artifacts.append(entry)
        data["artifacts"] = artifacts
        data["updated_at"] = datetime.utcnow().isoformat() + "Z"
        self._index_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def store_artifact_bytes(self, filename: str, data: bytes) -> tuple[Path, str]:
        safe = filename.replace("/", "_")
        path = (self.root / "artifacts" / safe).resolve()
        path.write_bytes(data)
        return path, sha256_hex(data)

    def store_artifact_file(self, filename: str, src: Path) -> tuple[Path, str]:
        safe = filename.replace("/", "_")
        dst = (self.root / "artifacts" / safe).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        return dst, sha256_file(dst)
