"""Credential management and comparison commands.

This module provides commands for comparing and managing credentials
between source and target AAP instances.
"""

import asyncio
from pathlib import Path

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import (
    handle_errors,
    pass_context,
    requires_config,
)
from aap_migration.cli.utils import (
    echo_error,
    echo_info,
    echo_success,
    echo_warning,
    print_table,
)
from aap_migration.migration.coordinator import MigrationCoordinator
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


@click.group(name="credentials")
def credentials():
    """Credential comparison and migration commands."""
    pass


@credentials.command(name="compare")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="./reports/credential-comparison.md",
    help="Output path for comparison report",
)
@pass_context
@requires_config
@handle_errors
def compare_credentials(ctx: MigrationContext, output: str):
    """Compare credentials between source and target instances.

    This command:
    1. Fetches all credentials from source and target
    2. Identifies missing credentials in target
    3. Generates a detailed comparison report
    4. Displays summary in console

    The report includes:
    - Total credential counts
    - List of missing credentials
    - Credential details (type, organization, etc.)
    """
    echo_info("Starting credential comparison...")

    async def _compare():
        # Initialize coordinator
        coordinator = MigrationCoordinator(
            config=ctx.config,
            source_client=ctx.source_client,
            target_client=ctx.target_client,
            state=ctx.migration_state,
            enable_progress=True,
        )

        # Run comparison
        result = await coordinator.compare_and_verify_credentials(report_path=output)

        # Display results
        echo_success("\nCredential Comparison Complete!")
        echo_info(f"\nSource Credentials: {result['total_source']}")
        echo_info(f"Target Credentials: {result['total_target']}")
        echo_info(f"Matching: {result['matching_count']}")
        echo_info(f"Managed (Skipped): {result['managed_skipped']}")

        if result["missing_count"] > 0:
            echo_warning(f"\nMissing in Target: {result['missing_count']}")
            echo_warning(f"\nDetailed report saved to: {output}")

            # Display missing credentials table
            if result["missing_credentials"]:
                echo_info("\nMissing Credentials:")
                headers = ["Source ID", "Name", "Type", "Organization"]
                rows = [
                    [
                        cred["source_id"],
                        cred["name"][:40],
                        cred["type"][:30],
                        cred["organization"] or "Global",
                    ]
                    for cred in result["missing_credentials"][:20]  # Limit to first 20
                ]

                if len(result["missing_credentials"]) > 20:
                    rows.append(["...", "...", "...", "..."])
                    echo_warning(
                        f"\nShowing first 20 of {result['missing_count']} missing credentials."
                    )

                print_table("Missing Credentials", headers, rows)
        else:
            echo_success("\nAll source credentials exist in target!")

        return result

    result = asyncio.run(_compare())

    if result["missing_count"] > 0:
        echo_warning(
            f"\nNext step: Run 'aap-bridge migrate credentials' to create missing credentials"
        )


@credentials.command(name="migrate")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Perform a dry run without making changes",
)
@click.option(
    "--report-dir",
    type=click.Path(),
    default="./reports",
    help="Directory for reports",
)
@pass_context
@requires_config
@handle_errors
def migrate_credentials(ctx: MigrationContext, dry_run: bool, report_dir: str):
    """Migrate only credentials from source to target.

    This command:
    1. Compares credentials to find missing ones
    2. Migrates organizations (dependency)
    3. Migrates credential types (dependency)
    4. Migrates credentials
    5. Generates migration report

    Note: Secret values cannot be migrated via API (returns $encrypted$).
    You may need to manually update credentials with actual secrets after migration.
    """
    if dry_run:
        echo_warning("DRY RUN MODE - No changes will be made")

    echo_info("Starting credential-only migration...")
    echo_info("Phase 1: Comparing credentials...")

    async def _migrate():
        # Initialize coordinator
        coordinator = MigrationCoordinator(
            config=ctx.config,
            source_client=ctx.source_client,
            target_client=ctx.target_client,
            state=ctx.migration_state,
            enable_progress=True,
        )

        # Override dry_run if specified
        if dry_run:
            coordinator.config.dry_run = True

        # First, compare credentials
        comparison = await coordinator.compare_and_verify_credentials(
            report_path=f"{report_dir}/credential-comparison.md"
        )

        echo_info(f"\nFound {comparison['missing_count']} missing credentials")

        if comparison["missing_count"] == 0:
            echo_success("All credentials already exist in target!")
            return {"status": "no_action_needed", "missing_count": 0}

        # Migrate only credential-related phases
        echo_info("\nPhase 2: Migrating credentials...")
        echo_warning(
            "Note: This will migrate organizations and credential types as dependencies"
        )

        result = await coordinator.migrate_all(
            only_phases=["organizations", "credentials"],
            generate_report=True,
            report_dir=report_dir,
        )

        return result

    result = asyncio.run(_migrate())

    if result.get("status") == "no_action_needed":
        return

    # Display summary
    echo_success("\nCredential Migration Complete!")
    echo_info(f"\nResources Exported: {result.get('total_resources_exported', 0)}")
    echo_info(f"Resources Imported: {result.get('total_resources_imported', 0)}")
    echo_info(f"Resources Failed: {result.get('total_resources_failed', 0)}")
    echo_info(f"Resources Skipped: {result.get('total_resources_skipped', 0)}")

    if result.get("total_resources_failed", 0) > 0:
        echo_error(f"\nFailed resources: {result['total_resources_failed']}")
        echo_warning("Check migration report for details")

    if "report_files" in result:
        echo_info(f"\nReports generated:")
        for report_file in result["report_files"]:
            echo_info(f"  - {report_file}")


@credentials.command(name="report")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default="./reports/credential-status.md",
    help="Output path for status report",
)
@pass_context
@requires_config
@handle_errors
def credential_report(ctx: MigrationContext, output: str):
    """Generate a detailed credential status report.

    This command generates a comprehensive report showing:
    - Current state of credentials in both instances
    - Comparison and differences
    - Migration recommendations
    """
    echo_info("Generating credential status report...")

    async def _report():
        coordinator = MigrationCoordinator(
            config=ctx.config,
            source_client=ctx.source_client,
            target_client=ctx.target_client,
            state=ctx.migration_state,
            enable_progress=True,
        )

        # Get comparison
        result = await coordinator.compare_and_verify_credentials(report_path=output)

        echo_success(f"\nCredential report generated: {output}")

        # Display summary
        echo_info(f"\nSource Credentials: {result['total_source']}")
        echo_info(f"Target Credentials: {result['total_target']}")

        if result["missing_count"] > 0:
            echo_warning(f"Missing in Target: {result['missing_count']}")
        else:
            echo_success("All credentials present in target")

        return result

    asyncio.run(_report())
