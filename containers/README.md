# Run AAP Bridge in containers

1. clone the repository:

```bash
git clone https://github.com/redhat-cop/aap-bridge.git
cd aap-bridge
```

2. Create required directories:

```bash
mkdir -p containers/pgdata
mkdir -p containers/bridge-data/{exports,xformed,reports,backups,schemas}
```

3. Generate API Token in source and destination AAPs for the users you want to export/import with.

4. Copy and edit the .env file with your AAP credentials and the DB password. Change the DB password to your own. 

```bash
cp .env.example containers/bridge-data/.env
vi containers/bridge-data/.env
```

Then set the following values according to your environment :

```
SOURCE__VERSION="2.x"

TARGET__VERSION="2.6"

SOURCE__URL=https://<source_aap_url>/api/v2
SOURCE__TOKEN="xxxxx"

TARGET__URL=https://<target_aap_url>/api/controller/v2
TARGET__TOKEN="xxxxxx"

MIGRATION_STATE_DB_PATH=postgresql://aap_migration_user:MyOwnPassword@localhost:5432/aap_migration
```

5. Build AAP Bridge image :

```bash
podman build -f containers/Containerfile -t aap-bridge-app .
```

6. Start the DB. Change the DB password to the one set in step 4.

```bash
podman run -d --name aap-bridge-db \
 -e POSTGRES_USER=aap_migration_user \
 -e POSTGRES_PASSWORD=MyOwnPassword \
 -e POSTGRES_DB=aap_migration \
 -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
 -e POSTGRES_INITDB_ARGS="--auth-host=scram-sha-256 --auth-local=scram-sha-256" \
 -v ./containers/pgdata/:/var/lib/postgresql/data:Z \
 -p 5432:5432 \
 docker.io/library/postgres:17
```

7. Create aap-bridge alias

```bash
alias aap-bridge="podman run -it \
 -v ./containers/bridge-data/.env:/app/.env:Z \
 -v ./config/:/app/config:Z \
 -v ./containers/bridge-data/exports/:/app/exports:Z \
 -v ./containers/bridge-data/xformed/:/app/xformed:Z \
 -v ./containers/bridge-data/reports/:/app/reports:Z \
 -v ./containers/bridge-data/backups/:/app/backups:Z \
 -v ./containers/bridge-data/schemas/:/app/schemas:Z \
 --name aap-bridge-app \
 --rm \
 --network host \
 aap-bridge-app"
```

8. Run the app

```bash
aap-bridge --help
```