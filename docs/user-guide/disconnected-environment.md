# Disconnected Environment

Run the AAP Bridge Web UI on a host that cannot reach container registries or
GitHub. Build and package images on a **connected** host, transfer them, then
load and start the stack **offline**.

The disconnected host still needs API reachability to **source** and **target**
AAP. "Disconnected" here means no outbound registry or Git access, not isolation
from AAP.

For a connected install, see [Installation](../getting-started/installation.md)
and [Web UI](web-ui.md).

This page focuses on the **Web UI**. The container TUI/CLI path is listed so you
can skip UI images and nginx/port work if you do not need the browser.

| Component | Web UI (`make up`) | TUI/CLI (`make up-dev`) |
| --- | --- | --- |
| `registry.redhat.io/rhel9/postgresql-15` | Yes | Yes |
| `registry.redhat.io/ubi9/ubi-minimal` | Yes | Yes |
| `localhost/aap-bridge-api`, `localhost/aap-bridge-ui` (`make build-all`) | Yes | No |
| `localhost/aap-bridge`, `localhost/aap-bridge-dev` (`make build`) | No | Yes |
| nginx / UI port remap | Yes | No |

The TUI/CLI path is less setup: build the CLI images, pull PostgreSQL and UBI,
then `make up-dev` / `make shell`. The rest of this page is the Web UI air-gap
flow.

## Prerequisites

| Host | Needs |
| --- | --- |
| **Connected (build)** | Podman, Make, `podman login` to `registry.redhat.io` |
| **Disconnected (run)** | Podman with compose support (`podman compose` / `podman-compose`), Make |

!!! warning "Images alone are not enough"
    Transfer a tarball of the repository **without** `.env` (see below).
    `compose.yml`, `Makefile`, `config/`, and `deploy/nginx.conf` are part of
    the runtime.

## Connected host: build and package

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge

make init-env
podman login registry.redhat.io

# Web UI images
make build-all

# Also required by compose (not baked into the Bridge images)
podman pull registry.redhat.io/rhel9/postgresql-15
podman pull registry.redhat.io/ubi9/ubi-minimal:latest
```

`make build-all` produces `localhost/aap-bridge-api:latest` and
`localhost/aap-bridge-ui:latest`. If you also want the container CLI on the
disconnected host, run `make build` as well (`localhost/aap-bridge:latest` and
`localhost/aap-bridge-dev:latest`).

### Save images and the repository

```bash
mkdir -p ~/aap-bridge-offline && cd ~/aap-bridge-offline

podman save -o aap-bridge-api.tar localhost/aap-bridge-api:latest
podman save -o aap-bridge-ui.tar  localhost/aap-bridge-ui:latest
podman save -o postgresql-15.tar  registry.redhat.io/rhel9/postgresql-15
podman save -o ubi-minimal.tar    registry.redhat.io/ubi9/ubi-minimal:latest

# TUI/CLI only (skip if you are shipping the Web UI path)
# podman save -o aap-bridge.tar     localhost/aap-bridge:latest
# podman save -o aap-bridge-dev.tar localhost/aap-bridge-dev:latest

# Do not pack .env: make init-env writes AAP_BRIDGE_TOKEN_ENCRYPTION_KEY,
# PostgreSQL passwords, and (if edited) AAP tokens. Reuse on the disconnected
# host would share that encryption key with a connected machine.
tar czf aap-bridge-repo.tar.gz \
  --exclude='.env' \
  --exclude='.venv' \
  --exclude='exports' \
  --exclude='xformed' \
  --exclude='logs' \
  --exclude='reports' \
  -C /path/to/aap-bridge .
sha256sum *.tar *.tar.gz > SHA256SUMS
```

!!! danger "Never copy `.env` across the air gap"
    `make init-env` generates `AAP_BRIDGE_TOKEN_ENCRYPTION_KEY` used to encrypt
    Web UI connection tokens in the state database. Shipping that file from a
    connected host also ships AAP tokens and database passwords if they were
    filled in. Always run `make init-env` on the disconnected host so it gets
    its own key. A new key cannot decrypt tokens stored with a different key,
    which is another reason not to copy `.env` or PostgreSQL `pgdata`.

Transfer the directory with whatever your air-gap process allows. Verify
checksums on the disconnected host before loading images.

## Disconnected host: load and start

```bash
cd /path/to/aap-bridge-offline
sha256sum -c SHA256SUMS

podman load -i postgresql-15.tar
podman load -i ubi-minimal.tar
podman load -i aap-bridge-api.tar
podman load -i aap-bridge-ui.tar

mkdir -p ~/aap-bridge && tar xzf aap-bridge-repo.tar.gz -C ~/aap-bridge
cd ~/aap-bridge

make init-env   # always: new encryption key and DB passwords for this host
# Edit SOURCE__/TARGET__ (or use Web UI Connections) and config/config.yaml
make up         # db + engine + ui (--no-build)
```

`make up` starts prebuilt images with `--no-build`. It does not pull or rebuild.

Default listen ports (host network):

| Service | Port |
| --- | --- |
| **ui** (nginx) | 8080 |
| **engine** (API) | 8000 |
| **db** | 15432 |

The `ui` and `engine` services use `network_mode: host`, so those ports bind on
the **disconnected host**, not only inside a container network.

Open the UI from a browser that can reach that host:

```text
http://<disconnected-host-ip>:8080
```

`http://localhost:8080` on a laptop is the laptop, not the Bridge server, unless
you are on the server or you have an SSH tunnel.

```bash
# From an operator workstation
ssh -L 8080:127.0.0.1:8080 user@disconnected-host
# then browse http://localhost:8080
```

If the host IP still fails after the UI is healthy locally, open the firewall
port (example for firewalld):

```bash
sudo firewall-cmd --add-port=8080/tcp --permanent
sudo firewall-cmd --reload
```

## Change UI and engine ports without rebuilding

Defaults are baked into the images:

| Setting | Where |
| --- | --- |
| UI listen port | `deploy/nginx.conf` (`listen 8080;`), copied into the UI image |
| UI API proxy | `deploy/nginx.conf` (`proxy_pass http://localhost:8000` for `/api/` and `/ws/`) |
| Engine listen port | `Containerfile` entrypoint (`aap-bridge serve --port 8000`) |
| `EXPOSE` in Containerfiles | Metadata only; it does not bind a port |

Compose `ports:` mappings do **not** move nginx or the engine when
`network_mode: host` is set. Changing only `EXPOSE` also does nothing.

The disconnected-friendly path is to edit the **host** `deploy/nginx.conf`,
mount it into the UI container, and override the engine command. You do not
need to rebuild images.

The examples below remap UI **8080 → 9090** and engine **8000 → 9000**. Use any
free ports.

### 1. Edit `deploy/nginx.conf` on the host

```nginx
listen 9090;

# in both location /api/ and location /ws/:
proxy_pass http://localhost:9000;
```

### 2. Make the file readable in the container

The UI image runs nginx as a non-root user (`USER 1001` in `Containerfile.ui`).
That UID is image-specific — inspect yours instead of copying `1001` blindly:

```bash
podman inspect localhost/aap-bridge-ui:latest --format '{{.Config.User}}'
chmod 644 deploy/nginx.conf
```

On SELinux-enforcing hosts, also check ownership, mode, and labels on bind
mounts (`ls -lZ deploy/nginx.conf`). Stock `compose.yml` sets
`security_opt: label=disable` on **engine** but not on **ui**. Add the same
option under `ui` when you mount `nginx.conf`.

### 3. Mount nginx and override the engine port in `compose.yml`

Do not commit these local edits unless you intend to change the project
defaults. Copy the snippets into your running tree:

```yaml
  ui:
    network_mode: host
    security_opt:
      - label=disable
    volumes:
      - ./deploy/nginx.conf:/etc/nginx/nginx.conf:ro

  engine:
    network_mode: host
    command: ["aap-bridge", "serve", "--host", "0.0.0.0", "--port", "9000"]
```

### 4. Recreate and verify

```bash
podman compose up -d --no-build db engine ui
# or: make up

ss -tlnp | egrep '9000|9090|8000|8080'
podman logs --tail=40 aap-bridge_ui_1
curl -I http://127.0.0.1:9090/
```

A healthy Bridge UI answers **200** with an nginx server header. A **301** to
`:8443` is some other service on that port, not AAP Bridge.

| Log / error | Meaning |
| --- | --- |
| `errno 98` / address already in use | Port still occupied; pick another or stop the other process |
| `Permission denied (13)` | Mounted `nginx.conf` (or related paths) not readable; fix mode/SELinux as above |

Browse `http://<disconnected-host-ip>:9090` (or tunnel to 9090).

## Optional: rebuild on a connected host

If you can rebuild, bake the new ports into the images instead of mounting
config:

1. Change `listen` and `proxy_pass` in `deploy/nginx.conf`.
2. Change the engine entrypoint `--port` in `Containerfile`.
3. Run `make build-all`, `podman save`, transfer, `podman load`, and recreate
   containers with `--no-build`.

Confirm the **image** contents before debugging compose:

```bash
podman run --rm --entrypoint cat localhost/aap-bridge-ui:latest /etc/nginx/nginx.conf \
  | grep -E 'listen|proxy_pass'
```

Prefer the runtime mount on a true air-gap host. A full `podman build` needs
base images, RPM repos, and often PyPI/npm, which are usually unavailable
offline.

## Checklist

### Connected

- [ ] `make build-all` and pull PostgreSQL + UBI (plus `make build` only for TUI/CLI)
- [ ] `podman save` every image compose needs
- [ ] Ship repo tarball **excluding `.env`** + `SHA256SUMS`
- [ ] Image tags match what `compose.yml` expects

### Disconnected

- [ ] Checksums verify
- [ ] `podman load` all images
- [ ] Unpack repo; run `make init-env` here (do not copy the connected `.env`)
- [ ] Configure source/target and `config/config.yaml`
- [ ] `podman compose` is available
- [ ] `make up`; open `http://<host-ip>:8080`

### Port remap (if 8080/8000 are in use)

- [ ] Edit host `deploy/nginx.conf` (`listen` + `proxy_pass`)
- [ ] `chmod 644 deploy/nginx.conf`
- [ ] Mount nginx on `ui` with `security_opt: label=disable`
- [ ] Override engine `command` `--port`
- [ ] Recreate with `--no-build`; confirm with `curl` on the new UI port
