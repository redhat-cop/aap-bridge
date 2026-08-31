"""Schema comparison logic for AAP 2.3 vs AAP 2.6 APIs."""

from typing import Any, TypedDict

from aap_migration.client.aap_source_client import AAPSourceClient
from aap_migration.client.aap_target_client import AAPTargetClient
from aap_migration.resources import get_endpoint
from aap_migration.schema.models import (
    ChangeType,
    ComparisonResult,
    FieldDiff,
    FieldRename,
    SchemaChange,
    Severity,
)
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


class _ValidationRule(TypedDict):
    description: str
    severity: Severity
    recommendation: str


class SchemaComparator:
    """Compare AAP 2.3 and AAP 2.6 API schemas."""

    # Special validation rules we know about from AAP documentation
    KNOWN_VALIDATION_RULES: dict[str, dict[str, _ValidationRule]] = {
        "credentials": {
            "ownership_validation": {
                "description": "AAP 2.6 requires at least ONE of: organization, user, team",
                "severity": Severity.HIGH,
                "recommendation": "Ensure organization field is preserved and dependency is resolved",
            }
        },
        "job_templates": {
            "execution_environment_required": {
                "description": "AAP 2.6 requires execution_environment (custom_virtualenv deprecated)",
                "severity": Severity.HIGH,
                "recommendation": "Map custom_virtualenv to execution_environment",
            }
        },
    }

    def _extract_field_schema_23(self, options_response: dict[str, Any]) -> dict[str, Any]:
        """Extract field definitions from AAP 2.3 OPTIONS response.

        AAP 2.3 has nested structure where field definitions are under
        actions.POST (for creation fields) or actions.GET (for read fields).

        We prefer POST fields as they represent what can be created/updated.

        Args:
            options_response: Raw OPTIONS response from AAP 2.3 API

        Returns:
            Dict of {field_name: field_definition}
        """
        actions = options_response.get("actions", {})
        schema = actions.get("POST", {}) if isinstance(actions, dict) else {}

        if not isinstance(schema, dict) or not schema:
            # Fallback to GET (read fields) if POST not available
            schema = actions.get("GET", {}) if isinstance(actions, dict) else {}

        if not isinstance(schema, dict) or not schema:
            logger.warning(
                "no_actions_in_23_schema",
                response_keys=list(options_response.keys()),
            )
            return {}

        return schema

    def _extract_field_schema_26(self, options_response: dict[str, Any]) -> dict[str, Any]:
        """Extract field definitions from AAP 2.6 OPTIONS response.

        AAP 2.6 returns flat structure where the entire response IS the
        field definitions (no nested actions key).

        Args:
            options_response: Raw OPTIONS response from AAP 2.6 API

        Returns:
            Dict of {field_name: field_definition}
        """
        # AAP 2.6 might still have actions key in some edge cases
        # Check for it first
        if "actions" in options_response:
            logger.debug(
                "found_actions_in_26_schema",
                message="AAP 2.6 has actions key (unexpected), using POST extraction",
            )
            actions = options_response.get("actions", {})
            post = actions.get("POST", {}) if isinstance(actions, dict) else {}
            return post if isinstance(post, dict) else {}

        # New flat format - entire response is field definitions
        # Each key should be a field name with dict value containing type, required, etc.
        return options_response

    async def fetch_schema(
        self, client: AAPSourceClient | AAPTargetClient, resource_type: str
    ) -> dict[str, Any]:
        """Fetch schema from AAP API using OPTIONS method.

        Handles different schema structures between AAP 2.3 and 2.6:
        - AAP 2.3: Nested structure (actions.POST contains fields)
        - AAP 2.6: Flat structure (root level IS the fields)

        Args:
            client: AAP client instance (source or target)
            resource_type: Resource type (e.g., 'credentials', 'inventories')

        Returns:
            Dict of {field_name: field_definition}

        Raises:
            Exception: If schema fetch fails
        """
        # Use get_endpoint to map resource_type to correct API endpoint
        # (e.g., "inventory_groups" -> "groups/")
        endpoint = get_endpoint(resource_type)

        try:
            # Fetch OPTIONS response
            response = await client.request(
                method="OPTIONS",
                endpoint=endpoint,
            )

            # Detect AAP version by client type and extract schema accordingly
            if isinstance(client, AAPSourceClient):
                # AAP 2.3 - use nested extraction
                schema = self._extract_field_schema_23(response)
                version = "2.3"
            else:
                # AAP 2.6 - use flat extraction
                schema = self._extract_field_schema_26(response)
                version = "2.6"

            if not schema:
                logger.warning(
                    "empty_schema_extracted",
                    resource_type=resource_type,
                    version=version,
                    response_keys=list(response.keys()),
                )

            logger.debug(
                "schema_fetched",
                resource_type=resource_type,
                version=version,
                fields_count=len(schema.keys()),
            )

            return schema

        except Exception as e:
            logger.error(
                "schema_fetch_failed",
                resource_type=resource_type,
                error=str(e),
            )
            raise

    def _filter_readonly_fields(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Filter out read-only fields that shouldn't be compared.

        These fields appear in GET responses but cannot be set during creation (POST).
        We exclude them from comparison as they're not part of the writable schema.

        Args:
            schema: Raw schema dict with all fields

        Returns:
            Filtered schema with only writable fields
        """
        # Read-only fields that appear in API responses but can't be set
        readonly_fields = {
            # System-generated IDs and metadata
            "id",
            "type",
            "url",
            "related",
            "summary_fields",
            # Timestamps
            "created",
            "modified",
            "last_job_run",
            "last_update",
            # Computed status fields
            "status",
            "has_active_failures",
            "last_update_failed",
            # Computed counts
            "total_hosts",
            "hosts_with_active_failures",
            "total_groups",
            "groups_with_active_failures",
            "total_inventories",
            # Other computed fields
            "has_inventory_sources",
            "total_inventory_sources",
            "inventory_sources_with_failures",
        }

        # Filter out read-only fields
        filtered = {
            field: definition
            for field, definition in schema.items()
            if field not in readonly_fields
        }

        logger.debug(
            "filtered_readonly_fields",
            original_count=len(schema),
            filtered_count=len(filtered),
            removed_count=len(schema) - len(filtered),
        )

        return filtered

    def compare_schemas(
        self,
        resource_type: str,
        source_schema: dict[str, Any],
        target_schema: dict[str, Any],
    ) -> ComparisonResult:
        """Compare source and target schemas.

        Args:
            resource_type: Resource type being compared
            source_schema: AAP 2.3 schema (from OPTIONS)
            target_schema: AAP 2.6 schema (from OPTIONS)

        Returns:
            ComparisonResult with detailed differences
        """
        result = ComparisonResult(
            resource_type=resource_type,
            source_schema=source_schema,
            target_schema=target_schema,
        )

        # Filter out read-only fields before comparison
        source_schema_filtered = self._filter_readonly_fields(source_schema)
        target_schema_filtered = self._filter_readonly_fields(target_schema)

        # Get field definitions from FILTERED schemas
        source_fields = source_schema_filtered.keys()
        target_fields = target_schema_filtered.keys()

        # Find added, removed, and common fields
        added_fields = set(target_fields) - set(source_fields)
        removed_fields = set(source_fields) - set(target_fields)
        common_fields = set(source_fields) & set(target_fields)

        # Analyze removed fields (deprecated in AAP 2.6)
        for field in removed_fields:
            result.field_diffs.append(
                FieldDiff(
                    field_name=field,
                    change_type=ChangeType.FIELD_REMOVED,
                    severity=Severity.LOW,  # Usually auto-removable
                    source_value=source_schema_filtered.get(field),
                    target_value=None,
                    description=f"Field '{field}' deprecated in AAP 2.6",
                    recommendation="Field will be automatically removed during transformation",
                )
            )

        # Analyze added fields (new in AAP 2.6)
        for field in added_fields:
            field_def = target_schema_filtered.get(field, {})

            # DEFENSIVE: Handle cases where field def is a string/scalar instead of dict
            # Some AAP APIs return simple type strings like "string", "integer"
            if isinstance(field_def, str):
                field_def = {"type": field_def}
            elif not isinstance(field_def, dict):
                field_def = {"type": str(field_def)}

            is_required = field_def.get("required", False)

            severity = Severity.HIGH if is_required else Severity.LOW

            result.field_diffs.append(
                FieldDiff(
                    field_name=field,
                    change_type=ChangeType.FIELD_ADDED,
                    severity=severity,
                    source_value=None,
                    target_value=field_def,
                    description=f"New field '{field}' in AAP 2.6"
                    + (" (required)" if is_required else ""),
                    recommendation=(
                        f"Must provide value for '{field}'"
                        if is_required
                        else f"Optional field '{field}' can be omitted"
                    ),
                )
            )

        # Analyze common fields for changes
        for field in common_fields:
            source_def = source_schema_filtered.get(field, {})
            target_def = target_schema_filtered.get(field, {})

            # DEFENSIVE: Handle cases where field def is a string/scalar instead of dict
            # Some AAP APIs return simple type strings like "string", "integer"
            if isinstance(source_def, str):
                source_def = {"type": source_def}
            elif not isinstance(source_def, dict):
                source_def = {"type": str(source_def)}

            if isinstance(target_def, str):
                target_def = {"type": target_def}
            elif not isinstance(target_def, dict):
                target_def = {"type": str(target_def)}

            # Check for type changes
            source_type = source_def.get("type")
            target_type = target_def.get("type")

            if source_type and target_type and source_type != target_type:
                result.field_diffs.append(
                    FieldDiff(
                        field_name=field,
                        change_type=ChangeType.TYPE_CHANGED,
                        severity=Severity.MEDIUM,
                        source_value=source_type,
                        target_value=target_type,
                        description=f"Field '{field}' type changed: {source_type} → {target_type}",
                        recommendation=f"Type conversion may be needed for '{field}'",
                    )
                )

            # Check for required changes
            source_required = source_def.get("required", False)
            target_required = target_def.get("required", False)

            if source_required != target_required:
                severity = Severity.HIGH if target_required else Severity.INFO

                result.field_diffs.append(
                    FieldDiff(
                        field_name=field,
                        change_type=ChangeType.REQUIRED_CHANGED,
                        severity=severity,
                        source_value=source_required,
                        target_value=target_required,
                        description=f"Field '{field}' required status changed: "
                        f"{source_required} → {target_required}",
                        recommendation=(
                            f"Must provide value for '{field}' in AAP 2.6"
                            if target_required
                            else f"Field '{field}' is now optional"
                        ),
                    )
                )

        # Add known validation rules for this resource type
        if resource_type in self.KNOWN_VALIDATION_RULES:
            for _rule_name, rule_info in self.KNOWN_VALIDATION_RULES[resource_type].items():
                result.schema_changes.append(
                    SchemaChange(
                        resource_type=resource_type,
                        change_type=ChangeType.VALIDATION_CHANGED,
                        severity=rule_info["severity"],
                        description=rule_info["description"],
                        recommendation=rule_info["recommendation"],
                    )
                )

        # Detect field renames (using filtered schemas)
        result.field_renames = self.detect_field_renames(
            source_schema_filtered, target_schema_filtered, removed_fields, added_fields
        )

        logger.info(
            "schema_comparison_complete",
            resource_type=resource_type,
            field_diffs_count=len(result.field_diffs),
            schema_changes_count=len(result.schema_changes),
            field_renames_count=len(result.field_renames),
            has_breaking_changes=result.has_breaking_changes,
        )

        return result

    def detect_field_renames(
        self,
        source_schema: dict[str, Any],
        target_schema: dict[str, Any],
        removed_fields: set[str],
        added_fields: set[str],
    ) -> dict[str, "FieldRename"]:
        """Detect likely field renames using similarity heuristics.

        Args:
            source_schema: AAP 2.3 schema
            target_schema: AAP 2.6 schema
            removed_fields: Fields in source but not in target
            added_fields: Fields in target but not in source

        Returns:
            Dict of {old_field_name: FieldRename}
        """
        from aap_migration.schema.models import FieldRename

        renames = {}

        for old_field in removed_fields:
            old_def = source_schema.get(old_field, {})

            # DEFENSIVE: Normalize field definition to dict
            if isinstance(old_def, str):
                old_def = {"type": old_def}
            elif not isinstance(old_def, dict):
                old_def = {"type": str(old_def)}

            # Find best match in new fields
            best_match = None
            best_score = 0.0

            for new_field in added_fields:
                new_def = target_schema.get(new_field, {})

                # DEFENSIVE: Normalize field definition to dict
                if isinstance(new_def, str):
                    new_def = {"type": new_def}
                elif not isinstance(new_def, dict):
                    new_def = {"type": str(new_def)}

                score = self._calculate_rename_score(old_field, old_def, new_field, new_def)

                if score > best_score and score >= 0.6:  # 60% confidence threshold
                    best_score = score
                    best_match = new_field

            if best_match:
                # Determine confidence level
                if best_score >= 0.8:
                    confidence = "high"
                elif best_score >= 0.7:
                    confidence = "medium"
                else:
                    confidence = "low"

                # Determine if auto-fixable (high/medium confidence only)
                auto_fixable = confidence in ["high", "medium"]

                renames[old_field] = FieldRename(
                    old_name=old_field,
                    new_name=best_match,
                    confidence=confidence,
                    reason=self._get_rename_reason(
                        old_field, old_def, best_match, new_def, best_score
                    ),
                    auto_fixable=auto_fixable,
                    manual_action=(
                        ""
                        if auto_fixable
                        else f"Manually verify '{old_field}' → '{best_match}' mapping"
                    ),
                )

                logger.info(
                    "field_rename_detected",
                    old_field=old_field,
                    new_field=best_match,
                    confidence=confidence,
                    score=round(best_score, 2),
                )

        return renames

    def _calculate_rename_score(
        self,
        old_name: str,
        old_def: dict[str, Any],
        new_name: str,
        new_def: dict[str, Any],
    ) -> float:
        """Calculate similarity score for potential field rename.

        Args:
            old_name: Old field name
            old_def: Old field definition
            new_name: New field name
            new_def: New field definition

        Returns:
            Similarity score between 0.0 and 1.0
        """
        from difflib import SequenceMatcher

        # Name similarity (0-1) - most important factor
        name_sim = SequenceMatcher(None, old_name, new_name).ratio()

        # Type match (0 or 1)
        old_type = old_def.get("type", "")
        new_type = new_def.get("type", "")
        type_match = 1.0 if old_type == new_type else 0.0

        # Weighted average: name similarity is more important
        score = (name_sim * 0.7) + (type_match * 0.3)

        return score

    def _get_rename_reason(
        self,
        old_name: str,
        old_def: dict[str, Any],
        new_name: str,
        new_def: dict[str, Any],
        score: float,
    ) -> str:
        """Generate human-readable reason for rename detection.

        Args:
            old_name: Old field name
            old_def: Old field definition
            new_name: New field name
            new_def: New field definition
            score: Similarity score

        Returns:
            Reason string
        """
        reasons = []

        # Name similarity
        from difflib import SequenceMatcher

        name_sim = SequenceMatcher(None, old_name, new_name).ratio()
        if name_sim > 0.7:
            reasons.append("similar_name")

        # Type match
        if old_def.get("type") == new_def.get("type"):
            reasons.append("same_type")

        # Required status
        if old_def.get("required") == new_def.get("required"):
            reasons.append("same_required_status")

        if not reasons:
            return f"similarity_score_{int(score * 100)}%"

        return "_and_".join(reasons)

    def generate_transformation_rules(self, comparison: ComparisonResult) -> dict[str, Any]:
        """Generate transformation rules from schema comparison.

        Args:
            comparison: Schema comparison result

        Returns:
            Dict with transformation rules:
            - fields_to_remove: List of deprecated fields
            - fields_to_add: Dict of {field: default_value}
            - type_conversions: Dict of {field: (old_type, new_type)}
        """
        return {
            "resource_type": comparison.resource_type,
            "fields_to_remove": comparison.deprecated_fields,
            "fields_to_add": comparison.new_required_fields,
            "type_conversions": comparison.type_changes,
            "has_breaking_changes": comparison.has_breaking_changes,
        }
