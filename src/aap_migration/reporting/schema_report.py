"""Schema comparison report generation and display."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aap_migration.schema.models import ChangeType, ComparisonResult, Severity


def display_schema_comparison_summary(
    comparisons: dict[str, ComparisonResult],
    console: Console | None = None,
) -> None:
    """Display summary table of all schema comparisons.

    Args:
        comparisons: Dict of {resource_type: ComparisonResult}
        console: Rich console (created if None)
    """
    if console is None:
        console = Console()

    table = Table(title="🔍 Source → Target Schema Comparison Summary")
    table.add_column("Resource Type", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center", style="yellow")
    table.add_column("Deprecated", justify="right", style="red")
    table.add_column("New Required", justify="right", style="green")
    table.add_column("Type Changes", justify="right", style="blue")
    table.add_column("Severity", justify="center", style="magenta")

    for resource_type, comparison in comparisons.items():
        # Determine status icon
        if not comparison.has_changes:
            status = "✓"
            status_style = "green"
        elif comparison.has_breaking_changes:
            status = "⚠️ "
            status_style = "red"
        else:
            status = "ℹ️ "
            status_style = "yellow"

        # Get severity level
        max_severity = Severity.INFO
        for diff in comparison.field_diffs:
            if diff.severity.value > max_severity.value:
                max_severity = diff.severity

        severity_display = max_severity.name
        severity_color = {
            Severity.INFO: "green",
            Severity.LOW: "green",
            Severity.MEDIUM: "yellow",
            Severity.HIGH: "red",
            Severity.CRITICAL: "bold red",
        }.get(max_severity, "white")

        table.add_row(
            resource_type,
            f"[{status_style}]{status}[/{status_style}]",
            str(len(comparison.deprecated_fields)),
            str(len(comparison.new_required_fields)),
            str(len(comparison.type_changes)),
            f"[{severity_color}]{severity_display}[/{severity_color}]",
        )

    console.print(table)


def display_detailed_comparison(
    comparison: ComparisonResult, console: Console | None = None
) -> None:
    """Display detailed comparison for a single resource type.

    Args:
        comparison: Comparison result for one resource type
        console: Rich console (created if None)
    """
    if console is None:
        console = Console()

    # Header
    title = f"📋 Detailed Schema Comparison: {comparison.resource_type.upper()}"

    if not comparison.has_changes:
        console.print(
            Panel.fit(
                f"[green]✓ No schema changes detected for {comparison.resource_type}[/green]",
                title=title,
                border_style="green",
            )
        )
        return

    # Show breaking changes warning
    if comparison.has_breaking_changes:
        console.print(
            Panel.fit(
                "[bold red]⚠️  BREAKING CHANGES DETECTED[/bold red]\n"
                "Manual intervention may be required for successful migration",
                border_style="red",
            )
        )
        console.print()

    # Field differences table
    if comparison.field_diffs:
        diffs_table = Table(title=f"Field Changes: {comparison.resource_type}")
        diffs_table.add_column("Field", style="cyan")
        diffs_table.add_column("Change Type", style="yellow")
        diffs_table.add_column("Severity", justify="center")
        diffs_table.add_column("Description", style="white", max_width=40)
        diffs_table.add_column("Recommendation", style="green", max_width=35)

        for diff in sorted(comparison.field_diffs, key=lambda d: d.severity.value, reverse=True):
            # Color code severity
            severity_color = {
                Severity.INFO: "green",
                Severity.LOW: "green",
                Severity.MEDIUM: "yellow",
                Severity.HIGH: "red",
                Severity.CRITICAL: "bold red",
            }.get(diff.severity, "white")

            # Icon for change type
            change_icon = {
                ChangeType.FIELD_ADDED: "➕",
                ChangeType.FIELD_REMOVED: "➖",
                ChangeType.TYPE_CHANGED: "🔄",
                ChangeType.REQUIRED_CHANGED: "⚡",
                ChangeType.VALIDATION_CHANGED: "📋",
            }.get(diff.change_type, "•")

            diffs_table.add_row(
                diff.field_name,
                f"{change_icon} {diff.change_type.value}",
                f"[{severity_color}]{diff.severity.name}[/{severity_color}]",
                diff.description,
                diff.recommendation,
            )

        console.print(diffs_table)
        console.print()

    # Schema-level changes
    if comparison.schema_changes:
        changes_table = Table(title=f"Validation Changes: {comparison.resource_type}")
        changes_table.add_column("Change", style="cyan", max_width=30)
        changes_table.add_column("Severity", justify="center")
        changes_table.add_column("Description", style="white", max_width=40)
        changes_table.add_column("Recommendation", style="green", max_width=35)

        for change in sorted(
            comparison.schema_changes, key=lambda c: c.severity.value, reverse=True
        ):
            severity_color = {
                Severity.INFO: "green",
                Severity.LOW: "green",
                Severity.MEDIUM: "yellow",
                Severity.HIGH: "red",
                Severity.CRITICAL: "bold red",
            }.get(change.severity, "white")

            changes_table.add_row(
                change.change_type.value,
                f"[{severity_color}]{change.severity.name}[/{severity_color}]",
                change.description,
                change.recommendation,
            )

        console.print(changes_table)
        console.print()


def generate_schema_report_text(comparisons: dict[str, ComparisonResult]) -> str:
    """Generate text report of schema comparisons.

    Args:
        comparisons: Dict of {resource_type: ComparisonResult}

    Returns:
        Multi-line text report
    """
    lines = [
        "=" * 80,
        "Source → Target Schema Comparison Report",
        "=" * 80,
        "",
    ]

    # Summary
    total_resources = len(comparisons)
    resources_with_changes = sum(1 for c in comparisons.values() if c.has_changes)
    resources_with_breaking = sum(1 for c in comparisons.values() if c.has_breaking_changes)

    lines.extend(
        [
            "SUMMARY:",
            f"  Total resource types analyzed: {total_resources}",
            f"  Resource types with changes: {resources_with_changes}",
            f"  Resource types with breaking changes: {resources_with_breaking}",
            "",
        ]
    )

    # Details for each resource type with changes
    for resource_type, comparison in comparisons.items():
        if not comparison.has_changes:
            continue

        lines.extend(
            [
                "-" * 80,
                f"Resource Type: {resource_type.upper()}",
                "-" * 80,
            ]
        )

        if comparison.has_breaking_changes:
            lines.append("⚠️  WARNING: Breaking changes detected!")
            lines.append("")

        # Field differences
        if comparison.field_diffs:
            lines.append("Field Changes:")
            for diff in comparison.field_diffs:
                lines.append(f"  • {diff.field_name}")
                lines.append(f"    Change: {diff.change_type.value}")
                lines.append(f"    Severity: {diff.severity.name}")
                lines.append(f"    Description: {diff.description}")
                lines.append(f"    Recommendation: {diff.recommendation}")
                lines.append("")

        # Schema changes
        if comparison.schema_changes:
            lines.append("Validation Changes:")
            for change in comparison.schema_changes:
                lines.append(f"  • {change.change_type.value}")
                lines.append(f"    Severity: {change.severity.name}")
                lines.append(f"    Description: {change.description}")
                lines.append(f"    Recommendation: {change.recommendation}")
                lines.append("")

    lines.extend(["=" * 80, ""])

    return "\n".join(lines)


def save_schema_report(comparisons: dict[str, ComparisonResult], output_path: str) -> None:
    """Save schema comparison report to file.

    Args:
        comparisons: Dict of {resource_type: ComparisonResult}
        output_path: Path to output file
    """
    report = generate_schema_report_text(comparisons)

    with open(output_path, "w") as f:
        f.write(report)
