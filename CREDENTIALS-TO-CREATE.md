# Credentials You Need to Create

**Target AAP:** https://localhost:10443

Currently you have **2/8 credentials**. You need to create **6 more**.

---

## Method 1: Interactive Script (Easiest)

```bash
cd /Users/arbhati/project/git/aap-bridge-fork
./scripts/fix_credentials_interactive.sh
```

The script will prompt you for each credential's secrets and create them automatically.

---

## Method 2: Manual via UI

### ✅ Already Exist (No Action Needed)

1. **Ansible Galaxy** (ID: 2)
   - Type: Ansible Galaxy/Automation Hub API Token
   - URL: https://galaxy.ansible.com/
   - Status: ✅ Complete (no secrets needed)

2. **Demo Credential** (ID: 1)
   - Type: Machine
   - Username: admin
   - Status: ⚠️ Missing password/SSH key

---

### ❌ Need to Create (6 credentials)

#### 3. Automation Hub Validated Repository

**Where:** Resources → Credentials → Add

```
Name: Automation Hub Validated Repository
Credential Type: Ansible Galaxy/Automation Hub API Token
Organization: (leave blank)

Inputs:
  Galaxy Server URL: https://192.168.100.26/api/galaxy/content/validated/
  Token: [GET FROM AUTOMATION HUB - see below]
```

#### 4. Automation Hub Published Repository

```
Name: Automation Hub Published Repository
Credential Type: Ansible Galaxy/Automation Hub API Token
Organization: (leave blank)

Inputs:
  Galaxy Server URL: https://192.168.100.26/api/galaxy/content/published/
  Token: [SAME TOKEN AS ABOVE]
```

#### 5. Automation Hub RH Certified Repository

```
Name: Automation Hub RH Certified Repository
Credential Type: Ansible Galaxy/Automation Hub API Token
Organization: (leave blank)

Inputs:
  Galaxy Server URL: https://192.168.100.26/api/galaxy/content/rh-certified/
  Token: [SAME TOKEN AS ABOVE]
```

#### 6. Automation Hub Community Repository

```
Name: Automation Hub Community Repository
Credential Type: Ansible Galaxy/Automation Hub API Token
Organization: (leave blank)

Inputs:
  Galaxy Server URL: https://192.168.100.26/api/galaxy/content/community/
  Token: [SAME TOKEN AS ABOVE]
```

#### 7. Automation Hub Container Registry

```
Name: Automation Hub Container Registry
Credential Type: Container Registry
Organization: (leave blank)

Inputs:
  Authentication URL: https://192.168.100.26
  Username: admin
  Password: [GET FROM AUTOMATION HUB]
  Verify SSL: ✓ (checked)
```

#### 8. test_A

```
Name: test_A
Credential Type: Machine
Organization: org_A

Inputs:
  Username: arnav
  Password: (leave blank if using SSH key)
  SSH Private Key: [YOUR SSH KEY or leave blank]
  Privilege Escalation Method: sudo (or leave blank)
  Privilege Escalation Username: arnav
  Privilege Escalation Password: (leave blank for prompt)
```

---

## How to Get Automation Hub Token

1. **Open Automation Hub:** https://192.168.100.26
2. **Log in** with your credentials
3. **Find the token section:**
   - Option A: Click **Collections** → **API Token**
   - Option B: Click **User Menu** (top right) → **Token**
4. **Copy the token**
5. **Use it for all 4 Automation Hub credentials** (they share the same token)

---

## How to Get Container Registry Password

**Option 1:** It's the same as your Automation Hub login password

**Option 2:** Check with your admin who set up the Automation Hub

**Option 3:** If you have access to the Automation Hub server:
```bash
ssh to-automation-hub-server
# Check configuration or ask admin
```

---

## Quick Creation Checklist

- [ ] Get Automation Hub token from https://192.168.100.26
- [ ] Get Container Registry password (usually same as Automation Hub login)
- [ ] Create: Automation Hub Validated Repository
- [ ] Create: Automation Hub Published Repository
- [ ] Create: Automation Hub RH Certified Repository
- [ ] Create: Automation Hub Community Repository
- [ ] Create: Automation Hub Container Registry
- [ ] Create: test_A (optional - uses runtime prompts)
- [ ] Update: Demo Credential with password or SSH key
- [ ] Associate galaxy credentials to org_A

---

## After Creating Credentials

### Step 1: Verify All Credentials Exist

```bash
curl -sk -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/credentials/" \
  | jq -r '.results[] | "\(.id): \(.name)"'

# Should show 8+ credentials
```

### Step 2: Associate Galaxy Credentials to org_A

**Via UI:**
1. Go to: https://localhost:10443/#/organizations/2/edit
2. Scroll to: **Galaxy Credentials**
3. Click: **Add**
4. Select:
   - Ansible Galaxy
   - Automation Hub Validated Repository
   - Automation Hub Published Repository
   - Automation Hub RH Certified Repository
   - Automation Hub Community Repository
5. Click: **Save**

**Via API:**
```bash
# Get credential IDs
ANSIBLE_GALAXY_ID=$(curl -sk -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/credentials/?name=Ansible+Galaxy" \
  | jq -r '.results[0].id')

HUB_VALIDATED_ID=$(curl -sk -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/credentials/?name=Automation+Hub+Validated+Repository" \
  | jq -r '.results[0].id')

# Associate to org_A (ID: 2)
for cred_id in $ANSIBLE_GALAXY_ID $HUB_VALIDATED_ID; do
  curl -sk -X POST \
    -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
    -H "Content-Type: application/json" \
    "https://localhost:10443/api/controller/v2/organizations/2/galaxy_credentials/" \
    -d "{\"id\": $cred_id}"
done
```

### Step 3: Update State Database (Important!)

```bash
cd /Users/arbhati/project/git/aap-bridge-fork

# Map source credential IDs to new target IDs
sqlite3 migration_state.db <<EOF
-- Assuming new credentials get IDs 3-9, adjust as needed
INSERT OR REPLACE INTO id_mappings (resource_type, source_id, target_id, resource_name)
VALUES
  ('credentials', 1, 1, 'Demo Credential'),
  ('credentials', 2, 2, 'Ansible Galaxy'),
  ('credentials', 3, 3, 'Automation Hub Validated Repository'),
  ('credentials', 4, 4, 'Automation Hub Published Repository'),
  ('credentials', 5, 5, 'Automation Hub RH Certified Repository'),
  ('credentials', 6, 6, 'Automation Hub Community Repository'),
  ('credentials', 7, 7, 'Automation Hub Container Registry'),
  ('credentials', 8, 8, 'test_A');
EOF

# Verify mappings
sqlite3 migration_state.db \
  "SELECT source_id, target_id, resource_name FROM id_mappings WHERE resource_type='credentials';"
```

**Note:** Adjust the target IDs based on what was actually created. Check with:
```bash
curl -sk -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/credentials/" \
  | jq -r '.results[] | "\(.id): \(.name)"'
```

### Step 4: Migrate Projects

Now that credentials have secrets, you can migrate projects:

```bash
source .venv/bin/activate
aap-bridge migrate -r projects --config config/config.yaml
```

### Step 5: Test Project Sync

```bash
# Get project ID
PROJECT_ID=$(curl -sk -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/projects/" \
  | jq -r '.results[0].id')

# Trigger sync
curl -sk -X POST \
  -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/projects/$PROJECT_ID/update/"

# Check status (wait a few seconds)
sleep 5
curl -sk -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/projects/$PROJECT_ID/" \
  | jq '{name, status, scm_revision}'

# Should show: "status": "successful"
```

### Step 6: Migrate Job Templates

```bash
aap-bridge migrate -r job_templates --config config/config.yaml
```

### Step 7: Test End-to-End

```bash
# Get job template ID
TEMPLATE_ID=$(curl -sk -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/job_templates/" \
  | jq -r '.results[0].id')

# Launch job
curl -sk -X POST \
  -H "Authorization: Bearer ea023U8zsSXEBuXXZRpiLidAYMT1aT" \
  "https://localhost:10443/api/controller/v2/job_templates/$TEMPLATE_ID/launch/" \
  -d '{}'
```

---

## Troubleshooting

### "Token is invalid" for Automation Hub

**Solution:** Generate a new token:
1. Go to https://192.168.100.26
2. User → Token → Create New Token
3. Copy and update credentials

### "Container registry authentication failed"

**Solution:** Verify password is correct:
```bash
# Test login
podman login 192.168.100.26 -u admin
# Enter password
```

### "Credential type not found"

**Solution:** Make sure you select the correct type:
- **Automation Hub**: Use "Ansible Galaxy/Automation Hub API Token"
- **Container Registry**: Use "Container Registry"
- **SSH**: Use "Machine"

---

## Time Estimate

| Task | Time |
|------|------|
| Get Automation Hub token | 2 min |
| Create 4 Automation Hub credentials | 10 min |
| Create container registry credential | 2 min |
| Create/update test_A | 2 min |
| Update Demo Credential | 2 min |
| Associate galaxy creds to org_A | 3 min |
| Update state database | 2 min |
| **Total** | **~23 minutes** |

---

**Ready?** Choose your method:

```bash
# Method 1: Interactive script
./scripts/fix_credentials_interactive.sh

# Method 2: Manual via UI
# Open: https://localhost:10443
# Follow the steps above
```
