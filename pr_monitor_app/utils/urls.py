"""URL canonicalization for deterministic deduplication."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAM_EXACT = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
}


def canonicalize_url(url: str) -> str:
    """Canonicalize URLs for deterministic dedup.

    - lowercases scheme and hostname
    - strips fragments
    - removes known tracking parameters
    - sorts query parameters
    - removes default ports

    This is intentionally conservative: it does NOT remove arbitrary query params.
    """
    u = url.strip()
    if not u:
        return u

    parsed = urlparse(u)

    scheme = (parsed.scheme or "https").lower()

    netloc = parsed.netloc
    if not netloc and parsed.path.startswith("//"):
        parsed = urlparse(scheme + ":" + u)
        netloc = parsed.netloc

    host_port = netloc
    if "@" in host_port:
        _, host_port = host_port.split("@", 1)

    host = host_port
    port = ""
    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)

    host = host.lower()

    if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
        port = ""

    new_netloc = host + ((":" + port) if port else "")

    path = parsed.path or "/"
    path = re.sub(r"/{2,}", "/", path)

    q = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        kl = k.lower()
        if kl in TRACKING_PARAM_EXACT:
            continue
        if any(kl.startswith(p) for p in TRACKING_PARAM_PREFIXES):
            continue
        q.append((k, v))
    q.sort(key=lambda kv: (kv[0], kv[1]))
    query = urlencode(q, doseq=True)

    return urlunparse((scheme, new_netloc, path, parsed.params, query, ""))
