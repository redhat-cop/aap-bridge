# Troubleshooting

Common issues and solutions for AAP Bridge.

## Connection Issues

### Cannot connect to source AAP

**Symptoms:**

```text
Error: Connection refused to https://source-aap.example.com
```

**Solutions:**

1. Verify the URL is correct in `.env`
2. Check network connectivity: `curl -I https://source-aap.example.com/api/`
3. Verify the API token is valid and has read scope
4. Check firewall rules

### Cannot connect to target AAP (Platform Gateway)

**Symptoms:**

```text
Error: 404 Not Found at /api/v2/organizations/
```

**Solution:**

Use the host URL only in `.env` — API paths are auto-discovered:

```bash
TARGET__URL=https://target-aap.example.com
```

On AAP 2.5+, organizations and other shared resources are routed to
`/api/gateway/v1/` automatically. Legacy `/api/v2/` paths in `TARGET__URL` are
stripped but no longer required.

### Authentication errors

**Symptoms:**

```text
Error: 401 Unauthorized

```

**Solutions:**

1. Regenerate API token in AAP UI
2. Verify token scope matches the instance role:
   - **Source**: read-only scope is sufficient; the user must be able to
     read all resources being migrated
   - **Target**: read/write scope with admin-level privileges is required for
     import, cleanup, and validation
3. Check token hasn't expired

## Database Issues

### Cannot connect to PostgreSQL

**Symptoms:**

```text
Error: connection refused to localhost:5432
```

**Solutions:**

1. Verify PostgreSQL is running: `systemctl status postgresql`
2. Check connection string format:

   ```text
   postgresql://user:password@host:port/database
   ```

3. Verify user permissions:

   ```sql
   GRANT ALL ON DATABASE aap_migration TO your_user;

   ```

### State database corruption

**Symptoms:**

```text
Error: IntegrityError or inconsistent state
```

**Solution:**

Reset the state database:

```bash
aap-bridge state clear --confirm

```

!!! warning
    This will require re-running the full migration.

## Export Issues

### Export runs out of memory

**Symptoms:**

```text
Error: MemoryError or process killed
```

**Solutions:**

1. Reduce batch sizes in `config/config.yaml`:

   ```yaml
   performance:
     batch_sizes:
       hosts: 100  # Reduce from 200

   ```

1. Enable file splitting:

   ```bash
   aap-bridge export --records-per-file 500

   ```

### Export takes too long

**Solutions:**

1. Export specific resource types:

   ```bash
   aap-bridge export organizations inventories

   ```

2. Increase concurrency (if AAP can handle it):

   ```yaml
   performance:
     max_concurrent: 20

   ```

## Import Issues

### "SKIPPED - no importer" warning

**Symptoms:**

```text
Instances: 1 resources (⚠️ SKIPPED - no importer)
```

**Cause:** Missing entry in `export_import.py` method_map.

**Solution:** This is a code issue. Check
 `docs/developer-guide/adding-resource-types.md` for how to add new resource
 types.

### Resource already exists

**Symptoms:**

```text
Warning: Conflict - organization 'MyOrg' already exists
```

**Behavior:** AAP Bridge handles this automatically by:

1. Comparing existing resource with import data
2. Updating if different, skipping if identical
3. Recording the ID mapping

This is **not an error** - it's idempotent behavior.

### Unresolved dependency

**Symptoms:**

```text
Warning: Unresolved dependency - organization ID 5 not found
```

**Causes:**

1. Dependency wasn't exported
2. Dependency export failed
3. Resources exported out of order

**Solutions:**

1. Check if the dependency exists in exports
2. Re-run export for the missing type
3. Check state database for mapping

### Bulk import errors

**Symptoms:**

```text
Error: Bulk host create failed: 400 Bad Request
```

**Solutions:**

1. Check for invalid host data (duplicate names, invalid characters)
2. Reduce batch size:

   ```yaml
   performance:
     batch_sizes:
       hosts: 100

   ```

1. Check target AAP logs for details

## Validation Issues

### Count mismatch

**Symptoms:**

```text
Validation failed: Source has 1000 hosts, target has 998
```

**Causes:**

1. Some resources failed to import
2. Some resources were skipped (duplicates)
3. Import still in progress

**Solutions:**

1. Check import logs for errors
2. Review skipped resources in state database
3. Re-run import (idempotent - safe to repeat)

## Performance Issues

### Migration is slow

**Solutions:**

1. Increase concurrency:

   ```yaml
   performance:
     max_concurrent: 15

   ```

1. Use bulk APIs (enabled by default for hosts)

2. Check AAP instance capacity - it may be the bottleneck

### Rate limiting errors

**Symptoms:**

```text
Error: 429 Too Many Requests
```

**Solutions:**

1. Reduce rate limit:

   ```yaml
   performance:
     rate_limit:
       requests_per_second: 20

   ```

1. Reduce concurrency:

   ```yaml
   performance:
     max_concurrent: 5

   ```

## Logging and Debugging

### Enable debug logging

```bash
aap-bridge --log-level DEBUG migrate full

```

### Check log files

```bash
tail -f logs/aap-bridge.log

```

### Enable payload logging

In `config/config.yaml`:

```yaml
logging:
  log_payloads: true
  file_level: DEBUG

```

!!! warning
    Payload logging may contain sensitive data. Use only for debugging.

## Getting Help

If you can't resolve an issue:

1. Check the [GitHub Issues](https://github.com/redhat-cop/aap-bridge/issues)
2. Search existing issues for similar problems
3. Open a new issue with:
   - AAP Bridge version
   - Source/Target AAP versions
   - Error messages (scrubbed of secrets)
   - Relevant log excerpts
