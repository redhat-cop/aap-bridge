"""Tests for inventory foreign-key normalization."""

import pytest

from aap_migration.utils.inventory_fk import (
    ensure_inventory_id_on_inventory_source,
    parse_inventory_id_from_api_value,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (42, 42),
        ("/api/v2/inventories/7/", 7),
        ("/api/controller/v2/inventories/99/", 99),
        ({"id": 3}, 3),
        ({"url": "https://x/api/v2/inventories/12/"}, 12),
    ],
)
def test_parse_inventory_id_from_api_value(value, expected):
    assert parse_inventory_id_from_api_value(value) == expected


def test_ensure_fills_from_related():
    data = {
        "related": {"inventory": "/api/v2/inventories/5/"},
    }
    ensure_inventory_id_on_inventory_source(data)
    assert data["inventory"] == 5


def test_ensure_fills_from_related_dict():
    data = {"related": {"inventory": {"id": 44, "name": "Inv"}}}
    ensure_inventory_id_on_inventory_source(data)
    assert data["inventory"] == 44


def test_ensure_prefers_top_level_int():
    data = {"inventory": 9}
    ensure_inventory_id_on_inventory_source(data)
    assert data["inventory"] == 9
