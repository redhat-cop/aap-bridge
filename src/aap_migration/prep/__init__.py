"""AAP Migration Prep Module.

This module handles the discovery of endpoints and generation of schemas
from AAP 2.3 (source) and AAP 2.6 (target) instances.

The prep phase produces:
- source_endpoints.json: All discovered endpoints from source AAP
- target_endpoints.json: All discovered endpoints from target AAP
- source_schema.json: Complete schema for source AAP
- target_schema.json: Complete schema for target AAP
- schema_comparison.json: Diff and transformation rules
"""

from aap_migration.prep.endpoint_discovery import discover_endpoints, save_endpoints
from aap_migration.prep.schema_comparison import compare_schemas, save_comparison
from aap_migration.prep.schema_generator import generate_schema, save_schema

__all__ = [
    "discover_endpoints",
    "save_endpoints",
    "generate_schema",
    "save_schema",
    "compare_schemas",
    "save_comparison",
]
