"""Normalize inventory foreign keys from AWX/AAP API payloads (URLs, nested dicts)."""

from __future__ import annotations

import re
from typing import Any

_INVENTORY_HREF_RE = re.compile(r"/inventories/(\d+)")
_CREDENTIAL_HREF_RE = re.compile(r"/credentials/(\d+)")


def normalize_input_inventories_to_source_ids(value: Any) -> list[int]:
    """Coerce ``input_inventories`` from export/API to a list of inventory PKs.

    Accepts a list of integers, dicts with ``id``, or inventory URL strings.
    Order is preserved; duplicates are dropped.
    """
    if not value or not isinstance(value, list | tuple):
        return []
    seen: set[int] = set()
    out: list[int] = []
    for item in value:
        pid = parse_inventory_id_from_api_value(item)
        if pid is not None and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def parse_inventory_id_from_api_value(value: Any) -> int | None:
    """Return a source inventory PK from an API value (id, URL string, or summary dict)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = _INVENTORY_HREF_RE.search(value)
        return int(m.group(1)) if m else None
    if isinstance(value, dict):
        if "id" in value and value["id"] is not None:
            try:
                return int(value["id"])
            except (TypeError, ValueError):
                pass
        url = value.get("url")
        if isinstance(url, str):
            m = _INVENTORY_HREF_RE.search(url)
            return int(m.group(1)) if m else None
    return None


def parse_credential_id_from_api_value(value: Any) -> int | None:
    """Return a source credential PK from an API value (id, URL string, or summary dict)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        m = _CREDENTIAL_HREF_RE.search(value)
        return int(m.group(1)) if m else None
    if isinstance(value, dict):
        if "id" in value and value["id"] is not None:
            try:
                return int(value["id"])
            except (TypeError, ValueError):
                pass
        url = value.get("url")
        if isinstance(url, str):
            m = _CREDENTIAL_HREF_RE.search(url)
            return int(m.group(1)) if m else None
    return None


def ensure_inventory_id_on_inventory_source(data: dict[str, Any]) -> None:
    """Set ``data['inventory']`` to a source PK when the API used URLs or nested shapes."""
    pid = parse_inventory_id_from_api_value(data.get("inventory"))
    if pid is not None:
        data["inventory"] = pid
        return

    summary = data.get("summary_fields") or {}
    pid = parse_inventory_id_from_api_value(summary.get("inventory"))
    if pid is not None:
        data["inventory"] = pid
        return

    related = data.get("related") or {}
    inv_rel = related.get("inventory")
    pid = parse_inventory_id_from_api_value(inv_rel)
    if pid is not None:
        data["inventory"] = pid


def ensure_credential_id_on_inventory_source(data: dict[str, Any]) -> None:
    """Set ``data['credential']`` to a source PK when the API used URLs or nested shapes."""
    pid = parse_credential_id_from_api_value(data.get("credential"))
    if pid is not None:
        data["credential"] = pid
        return

    summary = data.get("summary_fields") or {}
    pid = parse_credential_id_from_api_value(summary.get("credential"))
    if pid is not None:
        data["credential"] = pid
        return

    related = data.get("related") or {}
    cred_rel = related.get("credential")
    pid = parse_credential_id_from_api_value(cred_rel)
    if pid is not None:
        data["credential"] = pid
