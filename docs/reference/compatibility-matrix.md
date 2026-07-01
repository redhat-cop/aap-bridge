# Source-Version Compatibility Matrix

This document defines the supported source-to-target migration paths for the AAP Bridge tool
and documents known version-specific exceptions.

AAP Bridge also supports **AWX** as a migration source. AWX shares the Controller API with
AAP at equivalent release levels; configure `SOURCE__VERSION` using the AAP version that
matches your AWX release. See [AWX Migration](awx-migration.md) for the full version mapping
and configuration guidance.

!!! note "AWX testing"
    Only **AWX 24.6.1** (equivalent to AAP 2.4) has been tested as a migration source.
    Other AWX releases may work when configured with the corresponding AAP source version,
    but they have not been verified.

## Support Status Key

| Status | Description |
|:---|:---|
| **Supported** | Fully tested migration path. Core resource families and dependency chains are verified. |
| **Partial** | Core resources tested, but some version-specific features or complex configurations may require manual steps. |
| **Unsupported** | Migration path not yet tested or verified. Use with caution. |

## Compatibility Matrix

| Source Version | Target Version | Status | Evidence Date | Notes |
|:---|:---|:---|:---|:---|
| AAP 1.0 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 1.1 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 1.2 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 2.0 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 2.1 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 2.2 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 2.3 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 2.4 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 2.5 | AAP 2.6 | **Supported** | 2026-04-25 | Primary migration path. Fully tested. |
| AAP 2.6 | AAP 2.6 | **Supported** | 2026-04-25 | Same-version migration path. Schema fully compatible. |

## AWX as Migration Source

The rows above apply to AWX sources when `SOURCE__VERSION` is set to the equivalent AAP
version. For example, AWX 24.6.1 is configured as `SOURCE__VERSION=2.4`.

| AWX Version | Equivalent AAP Source | Target Version | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| AWX 24.6.1 | AAP 2.4 | AAP 2.6 | **Supported** | Only AWX release directly tested. |
| Other AWX (see [mapping](awx-migration.md)) | Per equivalence table | AAP 2.6 | **Untested** | May work; configure `SOURCE__VERSION` to the matching AAP version. |

## Known Version-Specific Exceptions

### All Source Versions → AAP 2.6

- **Encrypted Credentials**: Encrypted field values (passwords, SSH keys) cannot be extracted
  via the source AAP API. These must be migrated using HashiCorp Vault or re-entered manually
  on the target.

### AAP 2.5+ → AAP 2.6

- **Instance Groups**: Instance groups referenced by RBAC assignments must exist on the target
  with the same name before migration.

## Verifying Your Migration Path

The `aap-bridge prep` command automatically discovers the versions of your source and target
instances and validates them against this matrix.

```bash
aap-bridge prep --config config.yaml
```

If your version pair is not fully supported, the tool will issue a warning and list known
exceptions for that path. You can override an "Unsupported" status using the `--force` flag,
but this is recommended for experimental use only.
