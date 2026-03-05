#!/usr/bin/env python3
"""
Create 50 test credentials in source AAP 2.4 for migration testing.

This creates diverse credentials with:
- Different credential types
- Various secrets (passwords, SSH keys, tokens, API keys)
- Different organizations
- Mixed configurations
"""

import os
import random
import string
import sys

import requests
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def random_password(length=16):
    """Generate random password."""
    chars = string.ascii_letters + string.digits + "!@#$%^&*()"
    return ''.join(random.choice(chars) for _ in range(length))


def random_username():
    """Generate random username."""
    prefixes = ["admin", "user", "svc", "deploy", "ops", "dev", "prod", "test"]
    suffixes = ["account", "user", "service", "bot", random.randint(100, 999)]
    return f"{random.choice(prefixes)}_{random.choice(suffixes)}"


def generate_ssh_key():
    """Generate fake SSH key (for testing only)."""
    return f"""-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA{random_password(43)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(40)}==
-----END RSA PRIVATE KEY-----"""


def get_credential_types(base_url, token):
    """Get available credential types."""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{base_url}/credential_types/",
        headers=headers,
        verify=False
    )
    response.raise_for_status()

    types_map = {}
    for ct in response.json()["results"]:
        types_map[ct["name"]] = ct["id"]

    return types_map


def get_organizations(base_url, token):
    """Get available organizations."""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{base_url}/organizations/",
        headers=headers,
        verify=False
    )
    response.raise_for_status()

    orgs = [org["id"] for org in response.json()["results"]]
    return orgs


def create_credential(base_url, token, credential_data):
    """Create a credential in AAP."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        f"{base_url}/credentials/",
        headers=headers,
        json=credential_data,
        verify=False
    )

    if response.status_code == 201:
        return response.json()
    else:
        raise Exception(f"Failed to create credential: {response.status_code} - {response.text}")


def generate_credentials(base_url, token, credential_types, organizations):
    """Generate 50 diverse test credentials."""

    credentials_to_create = []

    # Get credential type IDs
    machine_type = credential_types.get("Machine")
    scm_type = credential_types.get("Source Control")
    aws_type = credential_types.get("Amazon Web Services")
    azure_type = credential_types.get("Microsoft Azure Resource Manager")
    network_type = credential_types.get("Network")
    vault_type = credential_types.get("Vault")
    galaxy_type = credential_types.get("Ansible Galaxy/Automation Hub API Token")
    vmware_type = credential_types.get("VMware vCenter")
    openstack_type = credential_types.get("OpenStack")
    gcp_type = credential_types.get("Google Compute Engine")

    # Add None to orgs for credentials without organization
    orgs_with_none = organizations + [None, None, None]  # More without org

    # 1-15: Machine (SSH) Credentials
    for i in range(1, 16):
        cred = {
            "name": f"SSH Credential {i}",
            "description": f"Test SSH credential #{i} for migration testing",
            "credential_type": machine_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "username": random_username(),
                "password": random_password() if i % 2 == 0 else None,
                "ssh_key_data": generate_ssh_key() if i % 3 == 0 else None,
                "ssh_key_unlock": random_password(12) if i % 5 == 0 else None,
                "become_method": random.choice(["sudo", "su", "pbrun", "pfexec", "runas"]),
                "become_username": "root" if i % 2 == 0 else None,
                "become_password": random_password() if i % 4 == 0 else None,
            }
        }
        # Remove None values
        cred["inputs"] = {k: v for k, v in cred["inputs"].items() if v is not None}
        credentials_to_create.append(cred)

    # 16-25: Source Control Credentials
    for i in range(16, 26):
        scm_urls = [
            "https://github.com",
            "https://gitlab.com",
            "https://bitbucket.org",
            f"https://git.company{i}.com"
        ]
        cred = {
            "name": f"SCM Credential {i}",
            "description": f"Git/SCM credential for {random.choice(['GitHub', 'GitLab', 'Bitbucket'])}",
            "credential_type": scm_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "username": f"git_user_{i}",
                "password": random_password() if i % 2 == 0 else None,
                "ssh_key_data": generate_ssh_key() if i % 3 == 0 else None,
            }
        }
        cred["inputs"] = {k: v for k, v in cred["inputs"].items() if v is not None}
        credentials_to_create.append(cred)

    # 26-32: AWS Credentials
    for i in range(26, 33):
        cred = {
            "name": f"AWS Account {i}",
            "description": f"AWS credential for {'production' if i % 2 == 0 else 'development'}",
            "credential_type": aws_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "username": f"AKIA{random_password(16).upper()}",  # AWS Access Key format
                "password": random_password(40),  # Secret key
            }
        }
        credentials_to_create.append(cred)

    # 33-37: Azure Credentials
    if azure_type:
        for i in range(33, 38):
            cred = {
                "name": f"Azure Subscription {i}",
                "description": f"Azure Resource Manager credential",
                "credential_type": azure_type,
                "organization": random.choice(orgs_with_none),
                "inputs": {
                    "subscription": f"{random.randint(10000000, 99999999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(100000000000, 999999999999)}",
                    "client": f"{random.randint(10000000, 99999999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(100000000000, 999999999999)}",
                    "secret": random_password(32),
                    "tenant": f"{random.randint(10000000, 99999999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(100000000000, 999999999999)}",
                }
            }
            credentials_to_create.append(cred)

    # 38-42: Network Credentials
    if network_type:
        for i in range(38, 43):
            cred = {
                "name": f"Network Device {i}",
                "description": f"Network equipment credential (Cisco/Juniper/etc)",
                "credential_type": network_type,
                "organization": random.choice(orgs_with_none),
                "inputs": {
                    "username": f"netadmin{i}",
                    "password": random_password(20),
                    "authorize": i % 2 == 0,
                    "authorize_password": random_password(20) if i % 2 == 0 else None,
                }
            }
            cred["inputs"] = {k: v for k, v in cred["inputs"].items() if v is not None}
            credentials_to_create.append(cred)

    # 43-46: Vault Credentials
    if vault_type:
        for i in range(43, 47):
            cred = {
                "name": f"Ansible Vault Password {i}",
                "description": f"Vault password for {'production' if i % 2 == 0 else 'development'}",
                "credential_type": vault_type,
                "organization": random.choice(orgs_with_none),
                "inputs": {
                    "vault_password": random_password(24),
                }
            }
            credentials_to_create.append(cred)

    # 47-50: Galaxy/Automation Hub Tokens
    if galaxy_type:
        for i in range(47, 51):
            urls = [
                "https://galaxy.ansible.com/",
                "https://cloud.redhat.com/api/automation-hub/",
                "https://console.redhat.com/api/automation-hub/",
                f"https://hub.company{i}.com/api/galaxy/"
            ]
            cred = {
                "name": f"Galaxy/Hub Token {i}",
                "description": f"Automation Hub API token",
                "credential_type": galaxy_type,
                "organization": random.choice(orgs_with_none),
                "inputs": {
                    "url": random.choice(urls),
                    "token": random_password(64),
                }
            }
            credentials_to_create.append(cred)

    return credentials_to_create


def main():
    # Get environment variables
    source_url = os.getenv("SOURCE__URL", "https://localhost:8443/api/v2")
    source_token = os.getenv("SOURCE__TOKEN")

    if not source_token:
        print("❌ ERROR: SOURCE__TOKEN environment variable not set")
        print("   Run: export SOURCE__TOKEN='your_token'")
        sys.exit(1)

    print("🚀 Creating 50 Test Credentials in Source AAP")
    print("=" * 60)
    print(f"Target: {source_url}")
    print()

    try:
        # Get credential types and organizations
        print("📥 Fetching credential types...")
        credential_types = get_credential_types(source_url, source_token)
        print(f"   Found {len(credential_types)} credential types")

        print("📥 Fetching organizations...")
        organizations = get_organizations(source_url, source_token)
        print(f"   Found {len(organizations)} organizations")
        print()

        # Generate credentials
        print("🔧 Generating 50 diverse credentials...")
        credentials = generate_credentials(
            source_url,
            source_token,
            credential_types,
            organizations
        )
        print(f"   Generated {len(credentials)} credentials")
        print()

        # Create credentials
        print("📤 Creating credentials in source AAP...")
        created = []
        failed = []

        for idx, cred_data in enumerate(credentials, 1):
            try:
                print(f"   [{idx:2d}/50] Creating: {cred_data['name']:<40} ", end="", flush=True)
                result = create_credential(source_url, source_token, cred_data)
                created.append(result)
                print(f"✅ ID: {result['id']}")
            except Exception as e:
                failed.append({"name": cred_data["name"], "error": str(e)})
                print(f"❌ {str(e)[:50]}")

        # Summary
        print()
        print("=" * 60)
        print("📊 Summary:")
        print(f"   ✅ Created: {len(created)}")
        print(f"   ❌ Failed:  {len(failed)}")
        print()

        if created:
            # Group by type
            by_type = {}
            for cred in created:
                ctype = cred.get("credential_type_name", "Unknown")
                by_type[ctype] = by_type.get(ctype, 0) + 1

            print("📋 Credentials by Type:")
            for ctype, count in sorted(by_type.items()):
                print(f"   {ctype:<45} {count:3d}")
            print()

            # Group by organization
            by_org = {"No Organization": 0}
            for cred in created:
                if cred.get("organization"):
                    org_name = f"Org ID {cred['organization']}"
                    by_org[org_name] = by_org.get(org_name, 0) + 1
                else:
                    by_org["No Organization"] += 1

            print("📋 Credentials by Organization:")
            for org, count in sorted(by_org.items()):
                print(f"   {org:<45} {count:3d}")

        if failed:
            print()
            print("❌ Failed Credentials:")
            for fail in failed:
                print(f"   - {fail['name']}: {fail['error'][:80]}")

        print()
        print("✅ Test credential creation completed!")
        print()
        print("🔍 Verify in AAP UI:")
        print(f"   {source_url.replace('/api/v2', '')}/#/credentials")
        print()
        print("🧪 Ready to test migration:")
        print("   python scripts/export_credentials_for_migration.py")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
