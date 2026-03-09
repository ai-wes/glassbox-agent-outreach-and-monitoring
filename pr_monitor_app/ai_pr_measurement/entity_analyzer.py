"""
Entity authority analysis.

Checks:
  1. Google Knowledge Graph Search API — entity presence
  2. Wikipedia API — article existence and extract
  3. Wikidata API — entity presence
  4. Structured data extraction from the brand's official website (JSON-LD)

All calls are to real, public APIs.  If an API key is missing
or a call fails, the check is marked SKIPPED/FAILED.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import requests

from .config import BrandConfig, Secrets
from .models import EntityCheck, ModuleResult, Status
from .text_analysis import hash_response

logger = logging.getLogger(__name__)

TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# Google Knowledge Graph Search API
# ---------------------------------------------------------------------------

def _check_knowledge_graph(
    entity_name: str, api_key: str
) -> EntityCheck:
    url = "https://kgsearch.googleapis.com/v1/entities:search"
    params = {
        "query": entity_name,
        "key": api_key,
        "limit": 5,
        "indent": True,
        "languages": "en",
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        elements = data.get("itemListElement", [])
        found = False
        details: dict[str, Any] = {"candidates": []}
        for elem in elements:
            result = elem.get("result", {})
            name = result.get("name", "")
            score = elem.get("resultScore", 0)
            desc = result.get("description", "")
            detail_url = result.get("detailedDescription", {}).get("url", "")
            candidate = {
                "name": name,
                "score": score,
                "description": desc,
                "url": detail_url,
                "types": result.get("@type", []),
            }
            details["candidates"].append(candidate)
            # Consider "found" if name matches closely and score is material
            if entity_name.lower() in name.lower() or name.lower() in entity_name.lower():
                if score > 10:
                    found = True

        return EntityCheck(
            check_type="knowledge_graph",
            entity_name=entity_name,
            found=found,
            details=details,
            source_api="google_kg",
            raw_response_ref=hash_response(json.dumps(data, default=str)),
            status=Status.SUCCESS,
        )
    except Exception as exc:
        return EntityCheck(
            check_type="knowledge_graph",
            entity_name=entity_name,
            found=False,
            source_api="google_kg",
            status=Status.FAILED,
            reason=str(exc),
        )


# ---------------------------------------------------------------------------
# Wikipedia API
# ---------------------------------------------------------------------------

def _check_wikipedia(entity_name: str) -> EntityCheck:
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": entity_name,
        "format": "json",
        "prop": "info|extracts",
        "exintro": True,
        "explaintext": True,
        "exsentences": 3,
        "redirects": 1,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        found = False
        details: dict[str, Any] = {}
        for page_id, page in pages.items():
            if page_id == "-1":
                continue  # Page does not exist
            found = True
            details = {
                "page_id": int(page_id),
                "title": page.get("title", ""),
                "extract": page.get("extract", ""),
                "length": page.get("length", 0),
                "url": f"https://en.wikipedia.org/wiki/{page.get('title', '').replace(' ', '_')}",
            }
            break

        return EntityCheck(
            check_type="wikipedia",
            entity_name=entity_name,
            found=found,
            details=details,
            source_api="wikipedia_api",
            raw_response_ref=hash_response(json.dumps(data, default=str)),
            status=Status.SUCCESS,
        )
    except Exception as exc:
        return EntityCheck(
            check_type="wikipedia",
            entity_name=entity_name,
            found=False,
            source_api="wikipedia_api",
            status=Status.FAILED,
            reason=str(exc),
        )


# ---------------------------------------------------------------------------
# Wikidata API
# ---------------------------------------------------------------------------

def _check_wikidata(entity_name: str) -> EntityCheck:
    url = "https://www.wikidata.org/w/api.php"
    params = {
        "action": "wbsearchentities",
        "search": entity_name,
        "language": "en",
        "format": "json",
        "limit": 5,
    }
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("search", [])
        found = False
        details: dict[str, Any] = {"entities": []}
        for res in results:
            eid = res.get("id", "")
            label = res.get("label", "")
            desc = res.get("description", "")
            details["entities"].append({
                "id": eid,
                "label": label,
                "description": desc,
                "url": res.get("concepturi", ""),
            })
            if entity_name.lower() in label.lower() or label.lower() in entity_name.lower():
                found = True

        return EntityCheck(
            check_type="wikidata",
            entity_name=entity_name,
            found=found,
            details=details,
            source_api="wikidata_api",
            raw_response_ref=hash_response(json.dumps(data, default=str)),
            status=Status.SUCCESS,
        )
    except Exception as exc:
        return EntityCheck(
            check_type="wikidata",
            entity_name=entity_name,
            found=False,
            source_api="wikidata_api",
            status=Status.FAILED,
            reason=str(exc),
        )


# ---------------------------------------------------------------------------
# Structured data extraction from brand website
# ---------------------------------------------------------------------------

def _check_structured_data(website_url: str, entity_name: str) -> EntityCheck:
    """Fetch the brand's website and extract JSON-LD / microdata / RDFa."""
    try:
        import extruct
        from w3lib.html import get_base_url
    except ImportError:
        return EntityCheck(
            check_type="structured_data",
            entity_name=entity_name,
            found=False,
            source_api="extruct",
            status=Status.FAILED,
            reason="extruct or w3lib not installed",
        )

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AIPRMeasurement/1.0)"
        }
        resp = requests.get(website_url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
        base_url = get_base_url(html, resp.url)
        extracted = extruct.extract(
            html,
            base_url=base_url,
            syntaxes=["json-ld", "microdata", "rdfa", "opengraph"],
            uniform=True,
        )

        # Analyze what we found
        json_ld = extracted.get("json-ld", [])
        microdata = extracted.get("microdata", [])
        rdfa = extracted.get("rdfa", [])
        opengraph = extracted.get("opengraph", [])

        has_org_schema = False
        has_person_schema = False
        schema_types_found: list[str] = []

        for item in json_ld + microdata + rdfa:
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                types = item_type
            else:
                types = [item_type]
            for t in types:
                t_str = str(t)
                schema_types_found.append(t_str)
                if t_str.lower() in ("organization", "corporation", "localbusiness"):
                    has_org_schema = True
                if t_str.lower() == "person":
                    has_person_schema = True

        details = {
            "url_fetched": resp.url,
            "json_ld_count": len(json_ld),
            "microdata_count": len(microdata),
            "rdfa_count": len(rdfa),
            "opengraph_count": len(opengraph),
            "has_organization_schema": has_org_schema,
            "has_person_schema": has_person_schema,
            "schema_types_found": list(set(schema_types_found)),
            "json_ld_items": json_ld[:5],  # Store first 5 for auditing
        }

        found = has_org_schema or len(json_ld) > 0

        return EntityCheck(
            check_type="structured_data",
            entity_name=entity_name,
            found=found,
            details=details,
            source_api="extruct",
            raw_response_ref=hash_response(html[:5000]),
            status=Status.SUCCESS,
        )
    except Exception as exc:
        return EntityCheck(
            check_type="structured_data",
            entity_name=entity_name,
            found=False,
            source_api="extruct",
            status=Status.FAILED,
            reason=str(exc),
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def analyze_entity_authority(
    brand: BrandConfig, secrets: Secrets
) -> tuple[list[EntityCheck], ModuleResult]:
    """Run all entity authority checks."""
    checks: list[EntityCheck] = []
    errors = 0

    # 1. Knowledge Graph
    if secrets.google_kg_api_key:
        for name in brand.all_names:
            ec = _check_knowledge_graph(name, secrets.google_kg_api_key)
            checks.append(ec)
            if ec.status == Status.FAILED:
                errors += 1
    else:
        checks.append(EntityCheck(
            check_type="knowledge_graph",
            entity_name=brand.brand_name,
            source_api="google_kg",
            status=Status.SKIPPED,
            reason="GOOGLE_KG_API_KEY not configured",
        ))

    # 2. Wikipedia
    for name in brand.all_names:
        ec = _check_wikipedia(name)
        checks.append(ec)
        if ec.status == Status.FAILED:
            errors += 1

    # 3. Wikidata
    for name in brand.all_names:
        ec = _check_wikidata(name)
        checks.append(ec)
        if ec.status == Status.FAILED:
            errors += 1

    # 4. Structured data from official website
    if brand.official_website:
        ec = _check_structured_data(brand.official_website, brand.brand_name)
        checks.append(ec)
        if ec.status == Status.FAILED:
            errors += 1
    else:
        checks.append(EntityCheck(
            check_type="structured_data",
            entity_name=brand.brand_name,
            source_api="extruct",
            status=Status.SKIPPED,
            reason="official_website not set in brand config",
        ))

    # Also check executive names on Wikipedia/Wikidata
    for exec_name in brand.executive_names:
        ec = _check_wikipedia(exec_name)
        checks.append(ec)
        if ec.status == Status.FAILED:
            errors += 1
        ec2 = _check_wikidata(exec_name)
        checks.append(ec2)
        if ec2.status == Status.FAILED:
            errors += 1

    success_count = sum(1 for c in checks if c.status == Status.SUCCESS)
    overall = Status.SUCCESS if success_count > 0 else Status.SKIPPED

    return checks, ModuleResult(
        module="entity_analyzer",
        status=overall,
        reason=f"{errors} check(s) failed" if errors > 0 else None,
        records_produced=len(checks),
    )
