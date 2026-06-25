# AAP Bridge

A production-grade Python tool for migrating Ansible Automation Platform (AAP)
installations from one version to another, designed to handle large-scale
migrations (e.g., 80,000+ hosts).

## Key Features

- **Flexible Setup** - Run AAP Bridge directly on the host or use the optional
  containerized CLI workflow
- **Bulk Operations** - Leverages AAP bulk APIs for high-performance migrations
- **State Management** - PostgreSQL-backed state tracking with checkpoint/resume
  capability
- **Idempotency** - Safely resume interrupted migrations without creating
  duplicates
- **Professional Progress Display** - Rich-based live progress with real-time
  metrics
- **Flexible Output Modes** - Normal, quiet, CI/CD, and detailed modes
- **Comprehensive Logging** - Structured logging with separate console and file
  levels
- **Split-File Export/Import** - Automatic file splitting for large datasets

## Quick Links

<div class="grid cards" markdown>

- :material-download: **[Installation](getting-started/installation.md)**

    Get AAP Bridge installed on your system

- :material-rocket-launch: **[Quick Start](getting-started/quickstart.md)**

    Get up and running in 5 minutes

- :material-console: **[CLI Reference](user-guide/cli-reference.md)**

    Complete command reference

- :material-cog: **[Configuration](getting-started/configuration.md)**

    Configure AAP Bridge for your environment

</div>

## Architecture Overview

AAP Bridge follows an ETL (Export, Transform, Load) architecture. The CLI/TUI
can run directly on the host or inside the optional containerized workflow:

```mermaid
graph LR
    A[Source AAP<br/>1.0–2.7] -->|Export| B[AAP Bridge<br/>ETL Engine]
    B -->|Load| C[Target AAP<br/>2.6/2.7]
    B <-->|State<br/>Management| D[(PostgreSQL<br/>State Database)]

    style A fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    style B fill:#fff9c4,stroke:#f57f17,stroke-width:3px
    style C fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px
    style D fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px
```

**Components:**

- **Client Layer** - HTTP clients for source AAP, target AAP, and HashiCorp
  Vault
- **Migration Layer** - ETL pipeline with exporters, transformers, and importers
- **State Management** - Database-backed progress tracking and ID mapping
- **CLI / TUI** - User-friendly command-line interface for host or container use

## Migration Order

Resources are migrated in dependency order:

1. Organizations, Labels, Users, Teams
2. Credential Types, Credentials
3. Execution Environments
4. Inventories, Inventory Sources, Inventory Groups
5. Hosts (bulk operations)
6. Instances, Instance Groups
7. Projects
8. Job Templates, Workflows
9. Schedules

## License

This project is licensed under the GNU General Public License v3.0.

## Support

- **Issues**: [GitHub Issues](https://github.com/redhat-cop/aap-bridge/issues)
- **Security**: See
  [SECURITY.md](https://github.com/redhat-cop/aap-bridge/blob/main/SECURITY.md)
