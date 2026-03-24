#!/usr/bin/env python3
"""
Create comprehensive test data on AAP 2.4 for end-to-end migration testing.
This script creates diverse resource combinations to test all migration scenarios.
"""

import os
import requests
import json
import urllib3
from dotenv import load_dotenv

# Disable SSL warnings for localhost testing
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

# AAP 2.4 Source instance
SOURCE_URL = os.getenv("SOURCE__URL", "https://localhost:8443/api/v2")
SOURCE_TOKEN = os.getenv("SOURCE__TOKEN")

headers = {
    "Authorization": f"Bearer {SOURCE_TOKEN}",
    "Content-Type": "application/json"
}

test_results = {
    "organizations": {"created": [], "failed": []},
    "users": {"created": [], "failed": []},
    "teams": {"created": [], "failed": []},
    "credentials": {"created": [], "failed": []},
    "projects": {"created": [], "failed": []},
    "inventories": {"created": [], "failed": []},
    "hosts": {"created": [], "failed": []},
    "groups": {"created": [], "failed": []},
    "job_templates": {"created": [], "failed": []},
    "workflow_templates": {"created": [], "failed": []},
}

def create_resource(endpoint, data, resource_type):
    """Create a resource via AAP API"""
    try:
        response = requests.post(
            f"{SOURCE_URL}/{endpoint}/",
            headers=headers,
            json=data,
            verify=False,
            timeout=30
        )
        if response.status_code in [200, 201]:
            result = response.json()
            test_results[resource_type]["created"].append({
                "id": result.get("id"),
                "name": result.get("name"),
                "type": result.get("type", resource_type)
            })
            print(f"✅ Created {resource_type}: {result.get('name')} (ID: {result.get('id')})")
            return result
        else:
            test_results[resource_type]["failed"].append({
                "name": data.get("name"),
                "error": response.text
            })
            print(f"❌ Failed to create {resource_type} '{data.get('name')}': {response.status_code} - {response.text[:100]}")
            return None
    except Exception as e:
        test_results[resource_type]["failed"].append({
            "name": data.get("name"),
            "error": str(e)
        })
        print(f"❌ Exception creating {resource_type} '{data.get('name')}': {e}")
        return None

print("=" * 80)
print("CREATING COMPREHENSIVE TEST DATA ON AAP 2.4")
print("=" * 80)

# 1. ORGANIZATIONS
print("\n[1/9] Creating Organizations...")
orgs = [
    {"name": "E2E-Test-Simple-Org", "description": "Simple test organization"},
    {"name": "E2E-Test-Galaxy-Org", "description": "Org with galaxy credential", "max_hosts": 0},
    {"name": "E2E-Test-Limited-Org", "description": "Org with host limit", "max_hosts": 100},
    {"name": "E2E-Test-CustomEE-Org", "description": "Org with custom EE"},
    {"name": "E2E-Test-MultiPurpose-Org", "description": "Multi-purpose organization"},
]

created_orgs = {}
for org in orgs:
    result = create_resource("organizations", org, "organizations")
    if result:
        created_orgs[org["name"]] = result["id"]

# Get Default organization ID
try:
    default_org = requests.get(f"{SOURCE_URL}/organizations/?name=Default", headers=headers, verify=False).json()
    if default_org["count"] > 0:
        created_orgs["Default"] = default_org["results"][0]["id"]
except:
    pass

# 2. USERS
print("\n[2/9] Creating Users...")
users = [
    {"username": "e2e_regular_user", "password": "TestPass123!", "email": "regular@test.com", "first_name": "Regular", "last_name": "User"},
    {"username": "e2e_superuser", "password": "TestPass123!", "email": "super@test.com", "is_superuser": True},
    {"username": "e2e_auditor", "password": "TestPass123!", "email": "auditor@test.com", "is_system_auditor": True},
    {"username": "e2e_inactive_user", "password": "TestPass123!", "email": "inactive@test.com", "is_active": False},
    {"username": "e2e_special_chars", "password": "TestPass123!", "email": "special@test.com", "first_name": "João", "last_name": "O'Brien-Müller"},
    {"username": "e2e_multi_org", "password": "TestPass123!", "email": "multiorg@test.com"},
    {"username": "e2e_external_auth", "password": "TestPass123!", "email": "external@test.com", "auth": ["ldap"]},
    {"username": "e2e_email_only", "password": "TestPass123!", "email": "emailonly@test.com"},
]

created_users = {}
for user in users:
    result = create_resource("users", user, "users")
    if result:
        created_users[user["username"]] = result["id"]

# 3. TEAMS
print("\n[3/9] Creating Teams...")
if created_orgs:
    first_org_id = list(created_orgs.values())[0]
    teams = [
        {"name": "E2E-Simple-Team", "organization": first_org_id, "description": "Simple team"},
        {"name": "E2E-Multi-User-Team", "organization": first_org_id, "description": "Team with multiple users"},
        {"name": "E2E-Empty-Team", "organization": first_org_id, "description": "Empty team"},
        {"name": "E2E-Permissions-Team", "organization": first_org_id, "description": "Team with various permissions"},
        {"name": "E2E-Role-Team", "organization": first_org_id, "description": "Team with organization roles"},
    ]

    created_teams = {}
    for team in teams:
        result = create_resource("teams", team, "teams")
        if result:
            created_teams[team["name"]] = result["id"]

# 4. CREDENTIALS
print("\n[4/9] Creating Credentials...")
credentials = [
    {
        "name": "E2E-Machine-SSH-Key",
        "credential_type": 1,  # Machine
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "inputs": {
            "username": "ansible",
            "ssh_key_data": "-----BEGIN RSA PRIVATE KEY-----\nFAKE_KEY_FOR_TESTING\n-----END RSA PRIVATE KEY-----"
        }
    },
    {
        "name": "E2E-Machine-Password",
        "credential_type": 1,  # Machine
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "inputs": {
            "username": "testuser",
            "password": "TestPassword123!"
        }
    },
    {
        "name": "E2E-Git-SSH",
        "credential_type": 2,  # Source Control
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "inputs": {
            "username": "git",
            "ssh_key_data": "-----BEGIN RSA PRIVATE KEY-----\nFAKE_GIT_KEY\n-----END RSA PRIVATE KEY-----"
        }
    },
    {
        "name": "E2E-Git-Token",
        "credential_type": 2,  # Source Control
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "inputs": {
            "username": "git_user",
            "password": "ghp_testtoken123456789"
        }
    },
    {
        "name": "E2E-Vault-Cred",
        "credential_type": 3,  # Vault
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "inputs": {
            "vault_password": "VaultPass123!",
            "vault_id": "test_vault"
        }
    },
    {
        "name": "E2E-AWS-Cred",
        "credential_type": 5,  # Amazon Web Services
        "organization": created_orgs.get("E2E-Test-Galaxy-Org"),
        "inputs": {
            "username": "AKIAIOSFODNN7EXAMPLE",
            "password": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        }
    },
]

created_credentials = {}
for cred in credentials:
    result = create_resource("credentials", cred, "credentials")
    if result:
        created_credentials[cred["name"]] = result["id"]

# 5. PROJECTS
print("\n[5/9] Creating Projects...")
projects = [
    {
        "name": "E2E-Manual-Project",
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "scm_type": "",
        "local_path": "_1__demo"
    },
    {
        "name": "E2E-Git-Public-Project",
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "scm_type": "git",
        "scm_url": "https://github.com/ansible/ansible-tower-samples"
    },
    {
        "name": "E2E-Git-Private-Project",
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "scm_type": "git",
        "scm_url": "git@github.com:example/private-repo.git",
        "credential": created_credentials.get("E2E-Git-SSH")
    },
    {
        "name": "E2E-Git-Branch-Project",
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "scm_type": "git",
        "scm_url": "https://github.com/ansible/ansible-tower-samples",
        "scm_branch": "master"
    },
]

created_projects = {}
for project in projects:
    result = create_resource("projects", project, "projects")
    if result:
        created_projects[project["name"]] = result["id"]

# 6. INVENTORIES
print("\n[6/9] Creating Inventories...")
inventories = [
    {
        "name": "E2E-Simple-Inventory",
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "description": "Simple static inventory"
    },
    {
        "name": "E2E-Complex-Inventory",
        "organization": created_orgs.get("E2E-Test-Simple-Org"),
        "description": "Inventory with groups and variables",
        "variables": json.dumps({"env": "test", "region": "us-east-1"})
    },
    {
        "name": "E2E-Dynamic-Inventory",
        "organization": created_orgs.get("E2E-Test-Galaxy-Org"),
        "description": "Inventory for dynamic sources"
    },
]

created_inventories = {}
for inventory in inventories:
    result = create_resource("inventories", inventory, "inventories")
    if result:
        created_inventories[inventory["name"]] = result["id"]

# 7. HOSTS & GROUPS
print("\n[7/9] Creating Hosts and Groups...")
if created_inventories.get("E2E-Simple-Inventory"):
    inv_id = created_inventories["E2E-Simple-Inventory"]

    # Create groups
    groups = [
        {"name": "webservers", "inventory": inv_id, "variables": json.dumps({"http_port": 80})},
        {"name": "databases", "inventory": inv_id, "variables": json.dumps({"db_port": 5432})},
        {"name": "production", "inventory": inv_id},
    ]

    created_groups = {}
    for group in groups:
        result = create_resource("groups", group, "groups")
        if result:
            created_groups[group["name"]] = result["id"]

    # Create hosts
    hosts = [
        {"name": "web1.test.local", "inventory": inv_id, "variables": json.dumps({"ansible_host": "192.168.1.10"})},
        {"name": "web2.test.local", "inventory": inv_id, "variables": json.dumps({"ansible_host": "192.168.1.11"})},
        {"name": "db1.test.local", "inventory": inv_id, "variables": json.dumps({"ansible_host": "192.168.1.20"})},
        {"name": "db2.test.local", "inventory": inv_id, "variables": json.dumps({"ansible_host": "192.168.1.21"})},
        {"name": "app1.test.local", "inventory": inv_id},
    ]

    created_hosts = {}
    for host in hosts:
        result = create_resource("hosts", host, "hosts")
        if result:
            created_hosts[host["name"]] = result["id"]

# 8. JOB TEMPLATES
print("\n[8/9] Creating Job Templates...")
if created_projects and created_inventories and created_credentials:
    job_templates = [
        {
            "name": "E2E-Basic-Job-Template",
            "job_type": "run",
            "inventory": created_inventories.get("E2E-Simple-Inventory"),
            "project": created_projects.get("E2E-Git-Public-Project"),
            "playbook": "hello_world.yml",
            "credential": created_credentials.get("E2E-Machine-Password")
        },
        {
            "name": "E2E-Multi-Cred-Job",
            "job_type": "run",
            "inventory": created_inventories.get("E2E-Simple-Inventory"),
            "project": created_projects.get("E2E-Git-Public-Project"),
            "playbook": "hello_world.yml",
        },
        {
            "name": "E2E-Check-Job-Template",
            "job_type": "check",
            "inventory": created_inventories.get("E2E-Simple-Inventory"),
            "project": created_projects.get("E2E-Git-Public-Project"),
            "playbook": "hello_world.yml",
        },
    ]

    created_job_templates = {}
    for jt in job_templates:
        result = create_resource("job_templates", jt, "job_templates")
        if result:
            created_job_templates[jt["name"]] = result["id"]

# 9. WORKFLOW TEMPLATES
print("\n[9/9] Creating Workflow Templates...")
if created_orgs:
    workflows = [
        {
            "name": "E2E-Simple-Workflow",
            "organization": created_orgs.get("E2E-Test-Simple-Org"),
            "description": "Simple workflow template"
        },
        {
            "name": "E2E-Complex-Workflow",
            "organization": created_orgs.get("E2E-Test-Simple-Org"),
            "description": "Complex workflow with conditions"
        },
    ]

    for workflow in workflows:
        result = create_resource("workflow_job_templates", workflow, "workflow_templates")

print("\n" + "=" * 80)
print("TEST DATA CREATION COMPLETE")
print("=" * 80)

# Print summary
print("\n📊 SUMMARY:")
for resource_type, results in test_results.items():
    created_count = len(results["created"])
    failed_count = len(results["failed"])
    print(f"  {resource_type.upper()}: {created_count} created, {failed_count} failed")

# Save detailed results
with open("test_data_creation_results.json", "w") as f:
    json.dump(test_results, f, indent=2)

print("\n💾 Detailed results saved to: test_data_creation_results.json")
print("\n✅ Test data creation script completed!")
