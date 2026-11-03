# Experimental organization synchronization

This experimental command provides on-demand, one-way add/update sync for a named organization.
It is intended for lab evaluation of credential-free static resources. The existing migration
compatibility matrix is unchanged; live validation of this sync command remains pending.

## Plan and apply

Use the existing source and target configuration and API tokens. Configure host-only URLs and
`SOURCE__VERSION` / `TARGET__VERSION`; upstream clients derive the API paths from those versions.
Shared organizations use Gateway on AAP 2.5+, while content remains on Controller. Sync resolves
Controller organization IDs by exact name rather than reusing Gateway IDs as foreign keys.
If a newly created organization is not visible on Controller within 30 seconds, apply stops;
wait for platform synchronization and rerun. Existing target changes are not rolled back.

```bash
aap-bridge --config config.yaml sync --organization demo-organization
aap-bridge --config config.yaml sync --organization demo-organization --apply
```

The default command only plans changes. Applying requires both `--apply` and `dry_run: false`
in the configuration. Reports include resource names, actions, and changed field names,
without field values.

Supported resources are organizations, ordinary static inventories, static hosts, Git projects,
and job templates. The implementation manages the field allowlists in `org_sync.py` and remaps
target IDs using scoped natural keys. Git project fields include `scm_refspec`, matching upstream's
current migration support. It preserves target-only resources and fields outside those allowlists.
It does not delete resources, launch jobs, synchronize groups or inventory sources, migrate
RBAC/workflows/schedules/surveys/execution environments, or install a recurring schedule.
Renames create new target resources. Source and target access must cover the complete selected
organization; token visibility is not a complete inventory audit.

## Known limitations

This path excludes credentials. AAP Bridge already lists 2.4 → 2.7 in its migration matrix;
this command adds experimental repeatable reconciliation, with separate validation requirements.
A project with matching Git URL/branch but a different checkout revision may be
reported unchanged; sync does not request a fresh Git update before synchronizing templates.
Live integration and representative scale validation remain required.

## Targeted tests

```bash
python -m unittest discover -s tests/unit -p 'test_org_sync*.py' -v
```
