"""Normalize inventory foreign keys from AWX/AAP API payloads (URLs, nested dicts)."""

from __future__ import annotations

import re
from typing import Any

_INVENTORY_HREF_RE = re.compile(r"/inventories/(\d+)")


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
