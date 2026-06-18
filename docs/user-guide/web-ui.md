# Web UI

AAP Bridge includes a browser-based interface built with React and PatternFly 5.
It provides the same capabilities as the CLI through a graphical interface with
real-time log streaming.

## Starting the Web UI

### Container Deployment (Recommended)

```bash
# Build and start all 3 containers
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
pip install -e '.[api]'
export MIGRATION_STATE_DB_PATH=postgresql://user:pass@localhost:5432/aap_migration
export AAP_BRIDGE_TOKEN_ENCRYPTION_KEY="$(python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)"
aap-bridge serve --reload

# Terminal 2: Start the Vite dev server
make web-install
make web-dev

# Access at http://localhost:5173
```

## Pages

### Connections

Manage AWX and AAP instance connections. Each connection stores:

- **Name** - Friendly label
- **Type** - AWX or AAP
- **Role** - Source (migrate from) or Destination (migrate to)
- **URL** - Full instance URL (e.g., `https://aap.example.com`)
- **Token** - API authentication token
- **Verify SSL** - Whether to verify TLS certificates

New or updated saved connection tokens are encrypted before they are written to the
state database. Existing plaintext tokens created before this setting was enabled
remain readable until that connection is edited and saved again.

Use the **Test** button to verify connectivity. This checks:

1. Ping (unauthenticated `/ping/` endpoint)
2. Auth (authenticated `/me/` endpoint)
3. Version detection

### Operations

Select a connection and run operations against it:

- **Browse** - Open the Object Browser filtered to this connection
- **Export** - Start an export job that writes JSON artifacts under `./exports/...`
- **Cleanup** - Delete non-default objects (destructive)

Each operation runs as an async job with live log streaming.

### Migrate

Three-step migration wizard:

1. **Select** - Choose source and destination connections
2. **Preview** - Runs an async preview job that exports source resources and
   detects conflicts on the destination. Shows counts of resources to create vs.
   skip before you start the migration.
3. **Run** - Executes the migration with real-time log streaming and a cancel
   button.

### Object Browser

Browse any resource type (organizations, credentials, job templates, etc.) on
any connected AAP/AWX instance. Supports search filtering and shows up to 8
columns per resource type.

### Jobs

Historical listing of all async operations with:

- Job type, status (color-coded), start time, duration
- Auto-refreshes every 3 seconds
- Click "View Logs" to open the log viewer for any job

## API Endpoints

The API server exposes these endpoints:

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/connections` | Create connection |
| GET | `/api/connections` | List connections |
| PUT | `/api/connections/{id}` | Update connection |
| DELETE | `/api/connections/{id}` | Delete connection |
| POST | `/api/connections/{id}/test` | Test connectivity |
| GET | `/api/connections/{id}/resources` | List resource types |
| GET | `/api/connections/{id}/resources/{type}` | List resources |
| POST | `/api/connections/{id}/cleanup` | Run cleanup |
| POST | `/api/connections/{id}/export` | Run export |
| POST | `/api/migrate/preview` | Start migration preview |
| GET | `/api/migrate/preview/{job_id}` | Get preview results |
| POST | `/api/migrate/run` | Execute migration |
| GET | `/api/exclusions` | Get exclusion lists |
| GET | `/api/jobs` | List jobs |
| GET | `/api/jobs/{id}` | Get job details |
| POST | `/api/jobs/{id}/cancel` | Cancel running job |
| WS | `/ws/jobs/{id}/logs` | Stream job logs |

Interactive API documentation is available at `/docs` (Swagger UI) and
`/redoc` when the API server is running.
