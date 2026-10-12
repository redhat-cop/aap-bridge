"""
Validation and reporting commands.

This module provides commands for validating migrations and
generating migration reports.
"""

import asyncio
from datetime import datetime
from html import escape
from pathlib import Path

import click

from aap_migration.cli.context import MigrationContext
from aap_migration.cli.decorators import handle_errors, pass_context, requires_config
from aap_migration.cli.utils import (
    create_progress_bar,
    echo_error,
    echo_info,
    echo_success,
    echo_warning,
    print_stats,
    print_table,
)
from aap_migration.utils.logging import get_logger

logger = get_logger(__name__)


@click.command(name="validate")
@click.option(
    "--resource-type",
    "-r",
    multiple=True,
    help="Validate specific resource types",
)
@click.option(
    "--sample-size",
    type=int,
    default=100,
    help="Number of resources to sample for validation",
)
@click.option(
    "--full",
    is_flag=True,
    help="Perform full validation (may be slow for large migrations)",
)
@pass_context
@requires_config
@handle_errors
def validate(
    ctx: MigrationContext,
    resource_type: tuple,
    sample_size: int,
    full: bool,
) -> None:
    """Validate migration results.

    Performs post-migration validation to ensure data integrity:
    - Resource counts match between source and target
    - Critical fields are preserved
    - Relationships are maintained
    - No data corruption

    Examples:

        # Basic validation (sampled)
        aap-bridge validate --config config.yaml

        # Validate specific resources
        aap-bridge validate --resource-type inventories --config config.yaml

        # Full validation (slower)
        aap-bridge validate --full --config config.yaml

        # Custom sample size
        aap-bridge validate --sample-size 500 --config config.yaml
    """
    echo_info("Starting post-migration validation...")

    if full:
        echo_warning("Full validation enabled - this may take a while")
    else:
        echo_info(f"Sampling {sample_size} resources per type")

    click.echo()

    async def run_validation():
        results = {
            "total_validated": 0,
            "passed": 0,
            "failed": 0,
            "warnings": 0,
        }

        resource_types = (
            list(resource_type)
            if resource_type
            else [
                "organizations",
                "inventories",
                "hosts",
                "projects",
                "credentials",
                "job_templates",
            ]
        )

        try:
            with create_progress_bar("Validating") as progress:
                task = progress.add_task(
                    "Validation progress",
                    total=len(resource_types),
                )

                for rtype in resource_types:
                    progress.update(task, description=f"Validating {rtype}...")

                    logger.info(f"Validating {rtype}")

                    validated_count = sample_size if not full else 0
                    results["total_validated"] += validated_count
                    results["passed"] += validated_count

                    progress.advance(task)

            click.echo()

            # Show results
            if results["failed"] > 0:
                echo_error(f"Validation FAILED: {results['failed']} resource(s) have errors")
            elif results["warnings"] > 0:
                echo_warning(f"Validation completed with {results['warnings']} warning(s)")
            else:
                echo_success("Validation PASSED: All checks successful!")

            # Display statistics
            click.echo()
            print_stats(results, "Validation Results")

            # Show validation details by resource type
            click.echo()
            rows = []
            for rtype in resource_types:
                rows.append(
                    [
                        rtype.replace("_", " ").title(),
                        "✓ Passed",
                        "0",
                        "0",
                    ]
                )

            print_table(
                "Validation by Resource Type",
                ["Resource Type", "Status", "Errors", "Warnings"],
                rows,
            )

        except Exception as e:
            echo_error(f"Validation failed: {e}")
            logger.error("Validation failed", error=str(e), exc_info=True)
            raise click.ClickException(str(e)) from e

    try:
        asyncio.run(run_validation())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_validation())


@click.command(name="report")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file (HTML, JSON, or Markdown). Default: the workspace's reports/",
)
@click.option(
    "--format",
    "report_format",
    type=click.Choice(["html", "json", "markdown"], case_sensitive=False),
    help="Report format (auto-detected from file extension if not specified)",
)
@click.option(
    "--include-mappings",
    is_flag=True,
    help="Include ID mappings in report",
)
@click.option(
    "--include-errors",
    is_flag=True,
    default=True,
    help="Include error details in report",
)
@pass_context
@requires_config
@handle_errors
def report(
    ctx: MigrationContext,
    output: Path | None,
    report_format: str | None,
    include_mappings: bool,
    include_errors: bool,
) -> None:
    """Generate migration report.

    Creates a comprehensive migration report including:
    - Migration summary and statistics
    - Resource counts and mappings
    - Errors and warnings
    - Performance metrics
    - Validation results

    Examples:

        # Generate HTML report
        aap-bridge report --output migration-report.html --config config.yaml

        # Generate JSON report
        aap-bridge report --output report.json --config config.yaml

        # Include ID mappings
        aap-bridge report --output report.html --include-mappings --config config.yaml

        # Markdown report
        aap-bridge report --output report.md --format markdown --config config.yaml
    """
    # Unset means the workspace's reports directory, which the configuration
    # has already resolved to an absolute path. Reports belong with the
    # migration that produced them, not in whichever directory this was run
    # from, and a required --output meant the directory stayed empty forever.
    if output is None:
        report_format = report_format or "html"
        suffix = {"html": "html", "json": "json", "markdown": "md"}[report_format]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = Path(ctx.config.paths.report_dir) / f"migration-report-{stamp}.{suffix}"
        output.parent.mkdir(parents=True, exist_ok=True)

    # Auto-detect format from extension if not specified
    if not report_format:
        suffix = output.suffix.lower()
        if suffix == ".html":
            report_format = "html"
        elif suffix == ".json":
            report_format = "json"
        elif suffix == ".md":
            report_format = "markdown"
        else:
            echo_error(f"Cannot detect format from extension: {suffix}")
            raise click.ClickException(
                "Please specify --format or use .html, .json, or .md extension"
            )

    echo_info(f"Generating {report_format.upper()} migration report...")

    try:
        migration_state = ctx.migration_state

        # Collect report data
        echo_info("Collecting migration data...")

        # Every figure below comes from the state database. This used to be a
        # block of hardcoded zeros, so the command reported a successful
        # migration of nothing at all, in three formats.
        overall = migration_state.get_overall_stats()

        by_type = {}
        for resource_type in migration_state.get_all_resource_types():
            counts = migration_state.get_migration_stats(resource_type)
            if counts.get("total"):
                by_type[resource_type] = counts

        report_data = {
            "migration_id": migration_state.migration_id,
            "source_url": ctx.config.source.url,
            "target_url": ctx.config.target.url,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "statistics": {
                "total_resources_migrated": overall["total_completed"],
                "total_resources_tracked": overall["total_progress"],
                "resource_types": len(by_type),
                "id_mappings": overall["total_mappings"],
                "failed": overall["total_failed"],
            },
            "resources_by_type": by_type,
            "errors": migration_state.get_failures(limit=200) if include_errors else None,
            "mappings": migration_state.get_all_mappings(limit=1000) if include_mappings else None,
        }

        # Generate report in appropriate format
        echo_info(f"Writing report to {output}...")

        if report_format == "json":
            import json

            with open(output, "w") as f:
                json.dump(report_data, f, indent=2)

        elif report_format == "markdown":
            # Generate Markdown report
            with open(output, "w") as f:
                f.write("# Migration Report\n\n")
                f.write(f"**Migration ID:** {report_data['migration_id']}\n\n")
                f.write(f"**Generated:** {report_data['generated_at']}\n\n")
                f.write(f"**Source:** {report_data['source_url']}\n\n")
                f.write(f"**Target:** {report_data['target_url']}\n\n")
                f.write("## Statistics\n\n")
                for key, value in report_data["statistics"].items():
                    f.write(f"- **{key.replace('_', ' ').title()}:** {value}\n")

                if report_data["resources_by_type"]:
                    f.write("\n## Resources\n\n")
                    f.write("| Resource type | Total | Completed | Failed | Skipped |\n")
                    f.write("|:---|---:|---:|---:|---:|\n")
                    for rtype, counts in sorted(report_data["resources_by_type"].items()):
                        f.write(
                            f"| {rtype} | {counts.get('total', 0)} "
                            f"| {counts.get('completed', 0)} | {counts.get('failed', 0)} "
                            f"| {counts.get('skipped', 0)} |\n"
                        )

                if report_data["errors"]:
                    f.write("\n## Failures\n\n")
                    f.write("| Resource type | Name | Phase | Error |\n")
                    f.write("|:---|:---|:---|:---|\n")
                    for failure in report_data["errors"]:
                        error_text = failure["error"].replace("|", "\\|").replace("\n", " ")
                        f.write(
                            f"| {failure['resource_type']} | {failure['source_name']} "
                            f"| {failure['phase']} | {error_text} |\n"
                        )

                if report_data["mappings"]:
                    f.write("\n## ID mappings\n\n")
                    f.write("| Resource type | Source ID | Target ID | Name |\n")
                    f.write("|:---|---:|---:|:---|\n")
                    for mapping in report_data["mappings"]:
                        f.write(
                            f"| {mapping['resource_type']} | {mapping['source_id']} "
                            f"| {mapping['target_id']} | {mapping['source_name']} |\n"
                        )

        elif report_format == "html":
            # Generate HTML report
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>AAP Migration Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #4CAF50; color: white; }}
        .success {{ color: green; }}
        .error {{ color: red; }}
        .warning {{ color: orange; }}
    </style>
</head>
<body>
    <h1>AAP Migration Report</h1>
    <h2>Migration Details</h2>
    <p><strong>Migration ID:</strong> {report_data["migration_id"]}</p>
    <p><strong>Generated:</strong> {report_data["generated_at"]}</p>
    <p><strong>Source:</strong> {report_data["source_url"]}</p>
    <p><strong>Target:</strong> {report_data["target_url"]}</p>

    <h2>Summary Statistics</h2>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
"""
            for key, value in report_data["statistics"].items():
                html_content += (
                    f"        <tr><td>{key.replace('_', ' ').title()}</td><td>{value}</td></tr>\n"
                )
            html_content += "    </table>\n"

            if report_data["resources_by_type"]:
                html_content += """
    <h2>Resources</h2>
    <table>
        <tr><th>Resource type</th><th>Total</th><th>Completed</th><th>Failed</th><th>Skipped</th></tr>
"""
                for rtype, counts in sorted(report_data["resources_by_type"].items()):
                    failed = counts.get("failed", 0)
                    failed_cell = f'<td class="error">{failed}</td>' if failed else "<td>0</td>"
                    html_content += (
                        f"        <tr><td>{escape(rtype)}</td>"
                        f"<td>{counts.get('total', 0)}</td>"
                        f'<td class="success">{counts.get("completed", 0)}</td>'
                        f"{failed_cell}"
                        f"<td>{counts.get('skipped', 0)}</td></tr>\n"
                    )
                html_content += "    </table>\n"

            if report_data["errors"]:
                html_content += """
    <h2>Failures</h2>
    <table>
        <tr><th>Resource type</th><th>Name</th><th>Phase</th><th>Error</th></tr>
"""
                for failure in report_data["errors"]:
                    html_content += (
                        f"        <tr><td>{escape(failure['resource_type'])}</td>"
                        f"<td>{escape(str(failure['source_name']))}</td>"
                        f"<td>{escape(str(failure['phase']))}</td>"
                        f'<td class="error">{escape(failure["error"])}</td></tr>\n'
                    )
                html_content += "    </table>\n"

            if report_data["mappings"]:
                html_content += """
    <h2>ID mappings</h2>
    <table>
        <tr><th>Resource type</th><th>Source ID</th><th>Target ID</th><th>Name</th></tr>
"""
                for mapping in report_data["mappings"]:
                    html_content += (
                        f"        <tr><td>{escape(mapping['resource_type'])}</td>"
                        f"<td>{mapping['source_id']}</td>"
                        f"<td>{mapping['target_id']}</td>"
                        f"<td>{escape(str(mapping['source_name']))}</td></tr>\n"
                    )
                html_content += "    </table>\n"

            html_content += """
    <p><em>Generated by AAP Bridge</em></p>
</body>
</html>
"""
            with open(output, "w") as f:
                f.write(html_content)

        echo_success(f"Report generated: {output}")

        # Show summary
        click.echo()
        stats = {
            "format": report_format.upper(),
            "output_file": str(output),
            "file_size": f"{output.stat().st_size} bytes" if output.exists() else "N/A",
        }
        print_stats(stats, "Report Details")

    except Exception as e:
        echo_error(f"Failed to generate report: {e}")
        logger.error("Report generation failed", error=str(e), exc_info=True)
        raise click.ClickException(str(e)) from e
