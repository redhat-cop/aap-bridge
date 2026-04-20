"""Regression checks for phase2 import ordering."""

from aap_migration.cli.commands.migrate import PHASE2_RESOURCE_TYPES


def test_smart_inventories_run_after_inventory_sources() -> None:
    src_idx = PHASE2_RESOURCE_TYPES.index("inventory_sources")
    smart_idx = PHASE2_RESOURCE_TYPES.index("smart_inventories")
    constructed_idx = PHASE2_RESOURCE_TYPES.index("constructed_inventories")
    assert src_idx < smart_idx < constructed_idx
