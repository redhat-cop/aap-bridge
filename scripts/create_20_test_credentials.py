#!/usr/bin/env python3
"""
Create 20 new test credentials in source AAP 2.4 for final validation testing.
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
    prefixes = ["test", "demo", "final", "validate", "verify", "prod", "staging"]
    suffixes = ["user", "account", "service", random.randint(100, 999)]
    return f"{random.choice(prefixes)}_{random.choice(suffixes)}"


def generate_ssh_key():
    """Generate fake SSH key (for testing only)."""
    return f"""-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA{random_password(43)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
{random_password(64)}
-----END RSA PRIVATE KEY-----"""


def get_credential_types(base_url, token):
    """Get available credential types."""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(
        f"{base_url}/credential_types/?page_size=100",
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
        f"{base_url}/organizations/?page_size=100",
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


def generate_20_credentials(base_url, token, credential_types, organizations):
    """Generate 20 diverse test credentials."""

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
    github_token_type = credential_types.get("GitHub Personal Access Token")
    gitlab_token_type = credential_types.get("GitLab Personal Access Token")

    # Add None to orgs for credentials without organization
    orgs_with_none = organizations + [None, None]

    # Credentials 1-5: Machine (SSH) Credentials
    for i in range(1, 6):
        cred = {
            "name": f"Final Test SSH {i}",
            "description": f"Final validation SSH credential #{i}",
            "credential_type": machine_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "username": random_username(),
                "password": random_password() if i % 2 == 0 else None,
                "ssh_key_data": generate_ssh_key() if i % 3 == 0 else None,
                "become_method": random.choice(["sudo", "su", "pbrun"]),
            }
        }
        cred["inputs"] = {k: v for k, v in cred["inputs"].items() if v is not None}
        credentials_to_create.append(cred)

    # Credentials 6-9: Source Control
    for i in range(6, 10):
        cred = {
            "name": f"Final Test SCM {i}",
            "description": f"Final validation SCM credential #{i}",
            "credential_type": scm_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "username": f"scm_user_{i}",
                "password": random_password() if i % 2 == 0 else None,
                "ssh_key_data": generate_ssh_key() if i % 3 == 0 else None,
            }
        }
        cred["inputs"] = {k: v for k, v in cred["inputs"].items() if v is not None}
        credentials_to_create.append(cred)

    # Credentials 10-12: AWS
    for i in range(10, 13):
        cred = {
            "name": f"Final Test AWS {i}",
            "description": f"Final validation AWS credential #{i}",
            "credential_type": aws_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "username": f"AKIA{random_password(16).upper()}",
                "password": random_password(40),
            }
        }
        credentials_to_create.append(cred)

    # Credentials 13-15: Azure
    if azure_type:
        for i in range(13, 16):
            cred = {
                "name": f"Final Test Azure {i}",
                "description": f"Final validation Azure credential #{i}",
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

    # Credentials 16-17: Galaxy/Automation Hub
    if galaxy_type:
        for i in range(16, 18):
            cred = {
                "name": f"Final Test Galaxy {i}",
                "description": f"Final validation Galaxy credential #{i}",
                "credential_type": galaxy_type,
                "organization": random.choice(orgs_with_none),
                "inputs": {
                    "url": random.choice([
                        "https://galaxy.ansible.com/",
                        "https://console.redhat.com/api/automation-hub/",
                        f"https://hub.company{i}.com/api/galaxy/"
                    ]),
                    "token": random_password(64),
                }
            }
            credentials_to_create.append(cred)

    # Credentials 18-20: GitHub/GitLab Tokens
    if github_token_type:
        cred = {
            "name": "Final Test GitHub Token 18",
            "description": "Final validation GitHub token",
            "credential_type": github_token_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "token": f"ghp_{random_password(40)}",
            }
        }
        credentials_to_create.append(cred)

    if gitlab_token_type:
        cred = {
            "name": "Final Test GitLab Token 19",
            "description": "Final validation GitLab token",
            "credential_type": gitlab_token_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "token": random_password(20),
            }
        }
        credentials_to_create.append(cred)

    # Credential 20: Vault
    if vault_type:
        cred = {
            "name": "Final Test Vault Password 20",
            "description": "Final validation Vault password",
            "credential_type": vault_type,
            "organization": random.choice(orgs_with_none),
            "inputs": {
                "vault_password": random_password(24),
            }
        }
        credentials_to_create.append(cred)

    return credentials_to_create


def main():
    # Load environment
    source_url = os.getenv("SOURCE__URL", "https://localhost:8443/api/v2")
    source_token = os.getenv("SOURCE__TOKEN")

    if not source_token:
        print("❌ ERROR: SOURCE__TOKEN environment variable not set")
        print("   Run: export SOURCE__TOKEN='your_token'")
        sys.exit(1)

    print("🚀 Creating 20 Test Credentials for Final Validation")
    print("=" * 70)
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
        print("🔧 Generating 20 diverse credentials...")
        credentials = generate_20_credentials(
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
                print(f"   [{idx:2d}/20] Creating: {cred_data['name']:<45} ", end="", flush=True)
                result = create_credential(source_url, source_token, cred_data)
                created.append(result)
                print(f"✅ ID: {result['id']}")
            except Exception as e:
                failed.append({"name": cred_data["name"], "error": str(e)})
                print(f"❌ {str(e)[:50]}")

        # Summary
        print()
        print("=" * 70)
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

        if failed:
            print()
            print("❌ Failed Credentials:")
            for fail in failed:
                print(f"   - {fail['name']}: {fail['error'][:80]}")

        print()
        print("✅ Test credential creation completed!")
        print()
        print(f"📊 Total credentials in source AAP now: {len(created)} new + existing")
        print()
        print("🧪 Ready to test migration:")
        print("   1. python scripts/export_credentials_for_migration.py")
        print("   2. python scripts/fill_test_secrets.py")
        print("   3. python scripts/generate_direct_api_playbook_v2.py")
        print("   4. ansible-playbook credential_migration/migrate_credentials_fixed.yml")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
