# Testing with Ephemeral AAP Instances

This guide covers building, running, and testing aap-bridge against containerized AAP instances
across multiple versions.

## Prerequisites

The only tools needed on the host:

- **podman** (with `podman compose` support)
- **make**
- Access to **registry.redhat.io** (PostgreSQL, UBI base images, and the builder image)
- Red Hat subscription credentials (for RHSM registration inside containers)
- Red Hat API offline token (for downloading AAP installer bundles)
- AAP subscription manifest zip file (for licensing AAP instances after install)

Get your offline token at [https://access.redhat.com/management/api](https://access.redhat.com/management/api).

This workflow builds on the [container CLI setup](../getting-started/installation.md#container-cli)
from the installation guide. You do not need Python, Ansible, or PostgreSQL installed on the
host — the bridge and database run in containers.

### Host kernel setting

Golden image builds run privileged systemd containers (and podman-in-podman for AAP 2.5+).
These workloads consume kernel keyring entries. The default limit on many systems
(`kernel.keys.maxkeys=200`) is too low and can cause `add_key: quota exceeded` errors
mid-build.

Raise it once on your development host:

```bash
echo 'kernel.keys.maxkeys = 5000' | sudo tee /etc/sysctl.d/99-aap-bridge.conf
sudo sysctl --system
```

Verify:

```bash
sysctl kernel.keys.maxkeys
```

This is a permanent, system-wide setting that survives reboots. It is a common tweak for
container-heavy development machines. To undo it, delete `/etc/sysctl.d/99-aap-bridge.conf`
and run `sudo sysctl --system`.

### Podman API socket

Integration builds run Ansible in a builder container that drives the host Podman
service via `podman-remote`. That requires the user socket API — separate from
`podman compose`, which uses the CLI directly.

Enable it once per login session (or enable permanently):

```bash
systemctl --user enable --now podman.socket
```

After a reboot, the socket starts automatically if enabled. If `make build-aap-bases`
fails with `no such file or directory` for `podman.sock`, run the command above.

### Subscription Manifest

AAP instances require a subscription manifest to be fully licensed. To set this up:

1. Go to [https://console.redhat.com/subscriptions/manifests](https://console.redhat.com/subscriptions/manifests)
2. Create or download a manifest for Ansible Automation Platform
3. Place the `.zip` file in `tests/integration/files/manifest/`

The build process will automatically detect and apply the manifest after
installation. If no manifest is found, the instance will be unlicensed (a
warning is printed during build).

## Architecture

Everything runs in containers. No Python, Ansible, or other tools needed on the host.

| Container | Purpose |
|-----------|---------|
| **bridge** | aap-bridge app + dev tools (Python 3.12, pytest, ruff, mypy) |
| **db** | PostgreSQL 15 for migration state |
| **builder** | Ansible + podman-remote for managing AAP test containers |
| **AAP containers** | UBI-based systemd containers with AAP installed via `setup.sh` |

```text
Host (podman + make)
├── compose: bridge + db
├── builder container (ansible, runs via podman socket)
└── AAP containers (systemd, privileged, one per version)
    ├── aap-24-build / aap-golden-2.4
    ├── aap-25-build / aap-golden-2.5
    └── ...
```

## Quick Start

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

# 1. Create .env (generates PostgreSQL credentials and encryption key)
#    Skip if you already have one from make setup
make init-env

# 2. Authenticate once so compose can pull Red Hat images
podman login registry.redhat.io

# 3. Place the subscription manifest zip in tests/integration/files/manifest/

# 4. Build the app and start the CLI dev container with postgres
make build
make up-dev

# 5. Quick smoke check inside the bridge container
make c-test

# 6. Build the ansible builder image (once)
make build-builder

# 7. Build AAP base images (once)
make build-aap-bases

# 8. Build an AAP golden image (once per version, ~45 min)
#    Requires kernel.keys.maxkeys >= 5000 (see Prerequisites)
#    Set up secrets first (see Secrets Management below)
make build-aap VERSION=2.4 RHSM_USER=myuser RHSM_PASS=mypass

# 9. Run a migration test pair
make run-pair SOURCE=2.4 TARGET=2.6
make test-bridge SOURCE=2.4 TARGET=2.6

# 10. Reset the pair (instant, from golden images)
make reset-pair SOURCE=2.4 TARGET=2.6
```

### Notes

- `compose.yml` pulls `registry.redhat.io/rhel9/postgresql-15` for the bundled database service.
- `make up-dev` is a shortcut for `podman compose up -d db bridge`.
- The bridge container mounts `./src` and `./tests/unit` from the host so `make c-test`
  and other `c-*` targets run against your working tree without rebuilding the image.
- The bridge container stores logs, exports, and reports in compose-managed volumes under `/app`.
- `make down` stops the bridge and database containers when you are finished.

### Verify

Inside the bridge container opened with `make shell`:

```bash
aap-bridge --version
aap-bridge --help
```

## Secrets Management

### Option 1: Ansible Vault (recommended)

Create a vault password file:

```bash
echo 'your-vault-password' > tests/integration/.vault_pass
```

Create a vaulted secrets file:

```bash
ansible-vault create tests/integration/inventory/group_vars/vault.yml \
    --vault-password-file tests/integration/.vault_pass
```

Add your secrets to `vault.yml` (use these exact variable names):

```yaml
rh_api_offline_token: "eyJhbG..."
rhsm_username: "your-user"
rhsm_password: "your-pass"
aap_admin_password: "your-password"
aap_pg_password: "your-password"
```

The Makefile auto-detects `tests/integration/.vault_pass` and passes
`--vault-password-file` to all `ansible-playbook` calls. The vault file
lives in `inventory/group_vars/` so Ansible loads it automatically as
group variables — no extra includes needed.

**Variable precedence** (highest wins):

1. Vault file (`group_vars/vault.yml`) — overrides everything
2. Environment variables (`RHSM_USER`, `RHSM_PASS`, `RH_TOKEN`, `AAP_ADMIN_PASSWORD`, `AAP_PG_PASSWORD`)
3. Role defaults — fallback to `redhat123!` for AAP passwords, omit for credentials

Both `.vault_pass`, `inventory/group_vars/vault.yml`, and the bundles directory are gitignored.

### Option 2: Environment variables

Export credentials before running make:

```bash
export RHSM_USER=myuser
export RHSM_PASS=mypass
export RH_TOKEN=eyJhbG...
make build-aap VERSION=2.4
```

Or pass them inline:

```bash
RHSM_USER=myuser RHSM_PASS=mypass make build-aap VERSION=2.4
```

### Option 3: Plain vars file

Uncomment and fill in values in `tests/integration/inventory/group_vars/all.yml`.
Keep it out of version control.

```bash
make build-aap VERSION=2.4 \
    RHSM_USER=myuser \
    RHSM_PASS=mypass \
    RH_TOKEN=eyJhbG...
```

## Building AAP Golden Images

Golden images are pre-installed AAP containers committed with `podman commit`.
Build once, reuse many times.

### Supported Versions

| Version | Base | Install Method | Status |
|---------|------|---------------|--------|
| 1.0-1.2 | UBI 8 | RPM (RHEL 7 bundle) | Best-effort |
| 2.0-2.4 | UBI 8 | RPM | Supported |
| 2.5-2.6 | UBI 9 | Containerized (podman-in-podman) | Supported |

### Build a single version

```bash
make build-aap VERSION=2.4
```

This creates a container, runs the AAP installer inside it, commits the result as
`localhost/aap-golden-2.4:latest`, and removes the build container.

### Build all versions

```bash
make build-aap-all
```

### Push to a registry

```bash
make push-aap VERSION=2.4 REGISTRY=quay.io/myorg
make pull-aap VERSION=2.4 REGISTRY=quay.io/myorg
```

### List golden images

```bash
make list-golden
```

## Running Test Pairs

Once golden images are built, start any source/target pair instantly:

```bash
# Start a pair
make run-pair SOURCE=2.3 TARGET=2.6

# Run aap-bridge in dry-run mode against the pair
make test-bridge SOURCE=2.3 TARGET=2.6

# Reset to clean state (~10 seconds)
make reset-pair SOURCE=2.3 TARGET=2.6

# Stop without removing
make stop-pair SOURCE=2.3 TARGET=2.6

# Remove completely
make destroy-pair SOURCE=2.3 TARGET=2.6
```

### Port Allocation

Each version gets a deterministic port block so pairs don't conflict:

```text
Source ports: 10000 + (version_index * 100) + offset
Target ports: 20000 + (version_index * 100) + offset

Version indices: 1.0=0, 1.1=1, 1.2=2, 2.0=3, ..., 2.6=9
Offsets: controller=43, hub=44, eda=45, gateway=46, envoy=47
```

Example for 2.3 (source) -> 2.6 (target):

- Source controller: `https://localhost:10643`
- Target (via envoy): `https://localhost:20947` (UI + all APIs)
- Target controller (direct): `https://localhost:20943`

For AAP 2.5+, the envoy proxy (offset 47) is the primary entry point — it
serves the UI and routes API requests to the correct backend. The controller
port (offset 43) provides direct API access but does not serve the UI.

## Development Workflow

### App development (runs inside bridge container)

```bash
make up-dev      # Start bridge + postgres
make c-test      # Run pytest
make c-lint      # Run ruff
make c-format    # Run black + isort
make c-typecheck # Run mypy
make c-check     # All of the above
make shell       # Shell into bridge container
make logs        # Tail logs
make down        # Stop everything
```

### Debugging

```bash
# Ansible verbosity (V=1 through V=4)
make build-aap VERSION=2.4 V=2

# Disable no_log to see secrets in output
make build-aap VERSION=2.4 DEBUG=1

# Both
make build-aap VERSION=2.4 V=2 DEBUG=1

# Shell into a running AAP container
make shell-src SOURCE=2.3
make shell-tgt TARGET=2.6

# View AAP container status
make status
```

### Installer troubleshooting

If the AAP installer fails, the build output shows the last 150 lines of the installer log
automatically. Common issues:

| Error | Fix |
|-------|-----|
| `dnf module reset postgresql` fails | Fixed: dnf wrapper in UBI 8 base image |
| `localhost` rejected in inventory | Fixed: uses container hostname |
| `restorecon: command not found` | Fixed: `policycoreutils` in base image |
| `en_US.UTF-8` locale missing | Fixed: `glibc-langpack-en` in base image |
| `loginctl enable-linger` fails | Fixed: `systemd-logind` unmasked |
| `sysctl: Read-only file system` | Fixed: containers run privileged |
| `add_key: quota exceeded` | Raise `kernel.keys.maxkeys` (see Prerequisites) |

## File Layout

```text
Containerfile                        # aap-bridge app (UBI 9 + Python 3.12)
compose.yml                          # db + bridge + engine + ui services
Makefile                             # All targets (host needs only podman + make)
tests/integration/
├── Containerfile.builder            # Ansible builder (podman-remote + collections)
├── containerfiles/
│   ├── Containerfile.ubi8-init      # Base for AAP 1.x-2.4
│   └── Containerfile.ubi9-init      # Base for AAP 2.5-2.6
├── versions/
│   └── matrix.yml                   # Version matrix (all per-version config)
├── inventory/
│   └── group_vars/
│       ├── all.yml                  # Shared variables
│       └── vault.yml                # Vaulted secrets (gitignored)
├── roles/
│   ├── aap_install/                 # Install AAP inside container
│   ├── base_container/              # Create + start systemd container
│   ├── golden_image/                # podman commit workflow
│   ├── lifecycle/                   # Reset + destroy operations
│   └── pair_networking/             # Port allocation + bridge config
├── playbooks/
│   ├── build-instance.yml           # Build one AAP golden image
│   ├── run-pair.yml                 # Start a source+target pair
│   ├── reset-pair.yml               # Reset pair from golden images
│   └── ...
├── files/
│   ├── manifest/                    # Subscription manifest zip (gitignored)
│   └── aap-installer-bundles/       # Downloaded bundles (gitignored)
└── generated/
    └── pairs/                       # Per-pair bridge configs (gitignored)
```
