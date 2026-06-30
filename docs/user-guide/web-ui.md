# Web UI

AAP Bridge includes a browser-based interface built with React and PatternFly 5.
It provides the same phased migration workflow as the TUI through a graphical
interface with real-time log streaming.

## Starting the Web UI

### Container Deployment (Recommended)

```bash
# Create .env, then build and start all 3 containers
make init-env
make build-all
make up

# Access at http://localhost:8080
```

This starts:

| Container | Port | Description |
| --- | --- | --- |
| **db** | 15432 | PostgreSQL 15 state database |
| **engine** | 8000 (internal) | FastAPI API server + migration engine |
| **ui** | 8080 | nginx serving React UI + API proxy |

### Local Development

For frontend development with hot-reload:

```bash
# Terminal 1: Start the API server
make init-env   # Or reuse an existing .env from make setup
pip install -e '.[api]'
aap-bridge serve --reload

# Terminal 2: Start the Vite dev server
make web-install
make web-dev

# Access at http://localhost:5173
```

## Pages

### Connections

Manage AAP instance connections. Each connection stores:

- **Name** - Friendly label
- **Role** - Source (migrate from) or Destination (migrate to)
- **AAP Version** - Required; selects API routing for this instance. This
  replaces ``SOURCE__VERSION`` / ``TARGET__VERSION`` for Web UI workflows; the
  CLI and TUI still read those variables from ``.env``.
- **URL** - Gateway root URL (e.g., `https://aap.example.com`)
- **Token** - API authentication token
- **Verify SSL** - Whether to verify TLS certificates

New or updated saved connection tokens are encrypted before they are written to the
state database. Existing plaintext tokens created before this setting was enabled
remain readable until that connection is edited and saved again.

Use the **Test** button to verify connectivity. This checks:

1. Ping (unauthenticated `/ping/` endpoint)
2. Auth (authenticated `/me/` endpoint, using the configured AAP version for API routing)

Test does not detect or change the configured version.

### Migrate

Select a source and destination connection, then run the same phased workflow as
the TUI:

1. **Preview Migration** - Compare source and destination resource counts using
   the same filters as export (create vs. skip)
2. **Cleanup** - Two options (hover the info icon beside each button for details):
   - **Full cleanup** (requires source and destination) — clears migration state,
     deletes migrated resources on the selected destination, and removes local
     `exports/` and `xformed/` files
   - **Clear migration state only** — clears migration state and local
     `exports/` and `xformed/` files for all configured pairs without touching
     any AAP instance
3. **1. Prep Phase** - Discover endpoints and collect schemas (optional force
   re-collection)
4. **2–4. Export / Transform / Import Phase 1** - Run individually or use the
   pipeline to run Export → Transform → Import Phase 1 in one step
5. **5. Import Phase 2** - Patch projects and import automation resources

Each phase runs as an async job with live log streaming below the controls.

### Jobs

Historical listing of all async operations with:

- Display sequence number (`#`), job type, status (color-coded), start time, duration
- Auto-refreshes every 3 seconds
- Click a job row to open the log viewer

## API Endpoints

The API server exposes these endpoints:

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/connections` | Create connection |
| GET | `/api/connections` | List connections |
| GET | `/api/versions` | List supported source/target AAP versions |
| PUT | `/api/connections/{id}` | Update connection |
| DELETE | `/api/connections/{id}` | Delete connection |
| POST | `/api/connections/{id}/test` | Test connectivity |
| POST | `/api/migrate/preview` | Start migration preview |
| GET | `/api/migrate/preview/{job_id}` | Get preview results |
| POST | `/api/migrate/prep` | Run prep (discover endpoints and schemas) |
| POST | `/api/migrate/cleanup` | Full cleanup (destination resources, state, local files) |
| POST | `/api/migrate/clear-state` | Clear migration state and local files (not target AAP) |
| POST | `/api/migrate/export` | Run export |
| POST | `/api/migrate/transform` | Run transform |
| POST | `/api/migrate/import` | Run import (phase 1 or 2) |
| POST | `/api/migrate/run` | Execute full migration (legacy endpoint) |
| GET | `/api/exclusions` | Get exclusion lists |
| GET | `/api/jobs` | List jobs |
| GET | `/api/jobs/{id}` | Get job details |
| POST | `/api/jobs/{id}/cancel` | Cancel running job |
| WS | `/ws/jobs/{id}/logs` | Stream job logs |

Interactive API documentation is available at `/docs` (Swagger UI) and
`/redoc` when the API server is running.
