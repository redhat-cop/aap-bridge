# Proposal: Automated Migration for Applications and Settings

## Current State
- **Applications:** Marked as `MANUAL_MIGRATION_ENDPOINTS` - no exporter/importer
- **Settings:** Marked as `MANUAL_MIGRATION_ENDPOINTS` - no exporter/importer
- **User Experience:** Manual curl commands, no tracking, error-prone

## Proposed Solution

### 1. Applications Migration (OAuth Apps)

#### Export
```python
class ApplicationExporter(ResourceExporter):
    """Export OAuth applications with security safeguards."""

    async def export_applications(self, applications):
        for app in applications:
            # Redact secrets but track that they exist
            if 'client_secret' in app:
                app['_has_client_secret'] = True
                app['client_secret'] = "***REDACTED_REQUIRES_MANUAL_UPDATE***"

            # Track security-sensitive fields
            app['_migration_notes'] = {
                'client_secret_action': 'regenerate_recommended',
                'redirect_uris_action': 'review_for_environment'
            }
```

#### Import
```python
class ApplicationImporter(ResourceImporter):
    """Import OAuth applications with secret management."""

    async def import_applications(self, applications):
        # Option 1: User provides secrets via config/CLI
        # Option 2: Auto-generate new secrets
        # Option 3: Skip and report (current manual behavior)

        for app in applications:
            if app.get('_has_client_secret'):
                # Check if user provided new secret
                new_secret = self.get_secret_from_config(app['name'])
                if not new_secret:
                    # Generate new secret and report
                    app['client_secret'] = generate_new_secret()
                    self.report_secret_generated(app['name'], app['client_secret'])
```

#### Benefits
- ✅ Preserves app metadata (names, grant types, redirect URIs)
- ✅ Maintains organization relationships
- ✅ Auto-generates new secrets (security best practice)
- ✅ Provides clear report of which apps need external system updates
- ✅ Supports manual secret injection via config if needed

---

### 2. Settings Migration

#### Export with Categorization
```python
class SettingsExporter(ResourceExporter):
    """Export settings with security categorization."""

    SENSITIVE_PATTERNS = [
        'PASSWORD', 'SECRET', 'KEY', 'TOKEN', 'PRIVATE'
    ]

    ENVIRONMENT_SPECIFIC_PATTERNS = [
        'URL', 'URI', 'HOST', 'PATH', 'DOMAIN'
    ]

    async def export_settings(self):
        all_settings = await self.client.get("settings/all/")

        categorized = {
            'safe_to_copy': {},      # Non-sensitive, non-environment-specific
            'review_required': {},   # Environment-specific URLs/paths
            'sensitive': {},         # Passwords, secrets, keys
            'metadata': {
                'export_timestamp': datetime.now(),
                'source_url': self.client.base_url
            }
        }

        for key, value in all_settings.items():
            if any(p in key for p in SENSITIVE_PATTERNS):
                categorized['sensitive'][key] = "***REDACTED***"
                categorized['sensitive'][f'_{key}_exists'] = True
            elif any(p in key for p in ENVIRONMENT_SPECIFIC_PATTERNS):
                categorized['review_required'][key] = value
            else:
                categorized['safe_to_copy'][key] = value

        return categorized
```

#### Import with Review
```python
class SettingsImporter(ResourceImporter):
    """Import settings with review workflow."""

    async def import_settings(self, settings_data):
        # Auto-import safe settings
        safe = settings_data.get('safe_to_copy', {})
        if safe:
            await self.client.patch("settings/all/", json_data=safe)
            self.report(f"Imported {len(safe)} safe settings")

        # Generate review report for environment-specific
        review = settings_data.get('review_required', {})
        if review:
            self.generate_review_report(review)

        # Generate template for sensitive settings
        sensitive = settings_data.get('sensitive', {})
        if sensitive:
            self.generate_sensitive_template(sensitive)
```

#### Migration Workflow
```bash
# 1. Export (categorizes automatically)
aap-bridge export --resource-type settings
# Creates: exports/settings/settings_categorized.json

# 2. Review environment-specific settings
cat xformed/settings/REVIEW-REQUIRED.md
# Shows: URLs, paths, hosts that need review

# 3. Provide sensitive values (optional)
cat > config/settings-secrets.yaml << EOF
AUTH_LDAP_BIND_PASSWORD: "new-password"
SOCIAL_AUTH_GITHUB_SECRET: "new-secret"
EOF

# 4. Import with review
aap-bridge import --resource-type settings
# Auto-imports safe settings
# Shows report of what needs manual review
# Imports sensitive settings from config (if provided)
```

#### Benefits
- ✅ Automates ~70% of settings (safe, non-sensitive ones)
- ✅ Clear separation of safe vs. review vs. sensitive
- ✅ Prevents accidental copying of wrong URLs/passwords
- ✅ Generates diff report for manual review
- ✅ Still requires human approval for sensitive changes

---

## Implementation Plan

### Phase 1: Add to Resource Registry (Low Risk)
```python
# In resources.py
RESOURCE_REGISTRY = {
    # ... existing ...
    "applications": ResourceTypeInfo(
        name="applications",
        endpoint="applications/",
        description="OAuth Applications",
        migration_order=175,  # Late (after organizations)
        cleanup_order=5,
        has_exporter=True,   # NEW
        has_importer=True,   # NEW
        has_transformer=True, # Redact secrets
    ),
    "settings": ResourceTypeInfo(
        name="settings",
        endpoint="settings/all/",
        description="Global Settings",
        migration_order=180,  # Very late
        cleanup_order=1,      # Never cleanup
        has_exporter=True,    # NEW
        has_importer=True,    # NEW (with review)
        has_transformer=True, # Categorize
    ),
}
```

### Phase 2: Implement Exporters
- `ApplicationExporter` with secret redaction
- `SettingsExporter` with categorization

### Phase 3: Implement Transformers
- `ApplicationTransformer` - resolve org deps, mark secrets
- `SettingsTransformer` - categorize into safe/review/sensitive

### Phase 4: Implement Importers
- `ApplicationImporter` - create with new/provided secrets, generate report
- `SettingsImporter` - import safe, generate review report for others

### Phase 5: Documentation
- Update MIGRATION-GUIDE.md with settings/apps workflow
- Add security best practices section
- Provide examples of secret injection via config

---

## Security Safeguards

### Applications
- ✅ Client secrets are NEVER copied as-is
- ✅ New secrets are auto-generated by default
- ✅ Clear report of which external systems need updates
- ✅ Optional: users can inject specific secrets via secure config

### Settings
- ✅ Passwords/secrets are redacted in export
- ✅ Environment-specific settings flagged for review
- ✅ Safe settings auto-imported (no manual work)
- ✅ Human approval required for sensitive changes
- ✅ Diff report generated for review

---

## User Experience Improvement

### Before (Manual)
```bash
# User has to:
1. Manually curl /api/v2/applications/ and parse JSON
2. Manually curl /api/v2/settings/all/ (500+ settings)
3. Identify which settings are safe to copy
4. Manually POST each application with new secrets
5. Manually PATCH each setting category
6. Hope they didn't miss anything
```

### After (Automated with Review)
```bash
# User workflow:
1. aap-bridge export --resource-type applications --resource-type settings
   → Exports with categorization and security redaction

2. Review generated reports:
   - APPLICATIONS-REPORT.md (which apps need secret rotation)
   - SETTINGS-REVIEW-REQUIRED.md (environment-specific settings)
   - SETTINGS-SENSITIVE-TEMPLATE.yaml (for manual secret input)

3. (Optional) Provide secrets:
   echo "AUTH_LDAP_PASSWORD: new-password" > config/settings-secrets.yaml

4. aap-bridge import --resource-type applications --resource-type settings
   → Auto-imports safe settings
   → Creates apps with new secrets
   → Shows report of what needs manual review

5. Review MIGRATION-COMPLETE-REPORT.md for next steps
```

---

## Decision

**Recommendation: IMPLEMENT THIS**

**Rationale:**
1. **Security is maintained:**
   - Secrets are never blindly copied
   - Clear separation of safe vs. sensitive
   - Human review still required where it matters

2. **UX is dramatically improved:**
   - Automates 70-80% of the work
   - Clear reports of what needs attention
   - Reduces human error

3. **Best practices enforced:**
   - Forces secret regeneration (good security)
   - Flags environment-specific settings
   - Provides audit trail

4. **Backwards compatible:**
   - Users can still do manual migration
   - Just provides better tooling

**Risk Level: LOW**
- Secrets are redacted
- Review workflow prevents blind copying
- Clear documentation and reports

---

## Next Steps

Should I implement this? It would:
1. Move applications and settings out of `MANUAL_MIGRATION_ENDPOINTS`
2. Add them to `RESOURCE_REGISTRY` with proper metadata
3. Implement exporters with security redaction
4. Implement importers with review workflow
5. Generate comprehensive reports for user review

**Estimated effort:** 4-6 hours
**User benefit:** Saves hours of manual work, reduces errors, improves security
