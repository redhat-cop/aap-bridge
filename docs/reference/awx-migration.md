# AWX Migration

AAP Bridge can migrate from upstream [AWX](https://github.com/ansible/awx)
installations to Ansible Automation Platform (AAP). AWX uses the same Controller
API as AAP at equivalent release levels, so no separate AWX-specific code path
is required — point the source configuration at your AWX instance and set
`SOURCE__VERSION` to the matching AAP version from the table below.

## Testing Status

!!! warning "Limited AWX testing"
    Only **AWX 24.6.1** has been tested as a migration source. Other AWX
    releases in the version mapping below may work when configured with the
    corresponding AAP source version, but they have not been verified.

## AAP and AWX Version Equivalence

When migrating from AWX, set `SOURCE__VERSION` to the **equivalent AAP
version**, not the AWX version number. For example, AWX 24.6.1 maps to AAP
2.4, so use `SOURCE__VERSION=2.4`.

| AAP Version | General Availability (GA) Date | Equivalent AWX Releases |
| :--- | :--- | :--- |
| **AAP 1.0** | November 14, 2019 | AWX 7.0.0, 8.0.0, 9.0.1 |
| **AAP 1.1** | June 23, 2020 | AWX 10.0.0, 11.0.0, 12.0.0, 13.0.0 |
| **AAP 1.2** | November 18, 2020 | AWX 14.0.0, 15.0.0, 16.0.0, 17.1.0 |
| **AAP 2.0** | July 15, 2021 | AWX 18.0.0 |
| **AAP 2.1** | December 2, 2021 | AWX 19.0.0, 19.5.1 |
| **AAP 2.2** | May 26, 2022 | AWX 20.0.0, 21.0.0, 21.7.0 |
| **AAP 2.3** | November 29, 2022 | AWX 21.8.0, 21.11.0, 22.0.0 – 22.4.0 |
| **AAP 2.4** | June 27, 2023 | AWX 23.0.0, 24.0.0, **24.6.1** |
| **AAP 2.5** | September 30, 2024 | *N/A* |
| **AAP 2.6** | October 1, 2025 | *N/A* |
| **AAP 2.7** | June 2, 2026 | *N/A* |

AWX releases beyond the AAP 2.4 equivalence line have no published AAP
counterpart and are not supported as migration sources.

## Configuration

Configure the source block in `.env` (or `config/config.yaml`) as you would for
an AAP instance, using your AWX URL and the equivalent AAP version:

```bash
# AWX instance acting as migration source (read-only token)
SOURCE__URL=https://awx.example.com
SOURCE__VERSION=2.4
SOURCE__TOKEN=your_awx_read_token

# Target AAP instance (read/write token)
TARGET__URL=https://target-aap.example.com
TARGET__VERSION=2.6
TARGET__TOKEN=your_target_write_token
```

Use `/api/v2/tokens/` to create a read-only token on AWX (same as AAP 2.4 and
earlier). See [Configuration](../getting-started/configuration.md) for full
details on API routing and token permissions.

## Compatibility

Supported source-to-target paths follow the same rules as AAP-to-AAP
migrations. See the [Source-Version Compatibility Matrix](compatibility-matrix.md)
for path status and known exceptions.
