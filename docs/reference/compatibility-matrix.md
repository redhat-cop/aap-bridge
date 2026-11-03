# Source-Version Compatibility Matrix

This document defines the supported source-to-target migration paths for the AAP Bridge tool
and documents known version-specific exceptions.

Migration supports **same-or-forward** target versions only. Each source version may migrate
to AAP 2.6 and/or 2.7 as listed in the matrix below — not every source may use every target.
For example, an AAP **2.7 source must target AAP 2.7**; downgrade paths such as 2.7 → 2.6
are not supported.

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
| **Supported** | Declared migration path. Core resource families are expected to work; see Notes for test coverage. |
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
| AAP 1.0 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 1.1 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 1.2 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 2.0 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 2.1 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 2.2 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 2.3 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 2.4 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 2.5 | AAP 2.7 | **Supported** | 2026-06-24 | Supported; integration coverage pending. |
| AAP 2.6 | AAP 2.7 | **Supported** | 2026-06-24 | Primary upgrade path. Supported; integration coverage pending. |
| AAP 2.7 | AAP 2.7 | **Supported** | 2026-06-24 | Same-version migration path. Supported; integration coverage pending. |

## AWX as Migration Source

The rows above apply to AWX sources when `SOURCE__VERSION` is set to the equivalent AAP
version. For example, AWX 24.6.1 is configured as `SOURCE__VERSION=2.4`.

| AWX Version | Equivalent AAP Source | Target Version | Status | Notes |
| :--- | :--- | :--- | :--- | :--- |
| AWX 24.6.1 | AAP 2.4 | AAP 2.6 | **Supported** | Only AWX release directly tested. |
| Other AWX (see [mapping](awx-migration.md)) | Per equivalence table | AAP 2.6 | **Untested** | May work; configure `SOURCE__VERSION` to the matching AAP version. |

## Known Version-Specific Exceptions

### All Source Versions → AAP 2.6 and 2.7

- **Encrypted Credentials**: Encrypted field values (passwords, SSH keys) cannot be extracted
  via the source AAP API. These must be migrated using HashiCorp Vault or re-entered manually
  on the target.

### AAP 2.5+ → AAP 2.6+

- **Instance Groups**: Instance groups referenced by RBAC assignments or assigned as
  capacity to organizations, inventories, or job templates must exist on the target
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

### Discovery of an Untested Pair

For discovery of a version pair absent from this matrix, use:

```bash
aap-bridge --config config.yaml prep --allow-untested-path
```

This permits endpoint and schema discovery only. It does not add the pair to the
compatibility matrix, enable imports, or establish migration compatibility.
Existing schema files still require overwrite confirmation. Menu option 1 offers
this discovery override after explaining that the path is untested. The default
noninteractive prep command continues to reject unknown paths. The existing
`--force` override remains available and also bypasses schema overwrite confirmation.

AAP 2.4 → 2.7 is already listed in the matrix and does not require this override.
