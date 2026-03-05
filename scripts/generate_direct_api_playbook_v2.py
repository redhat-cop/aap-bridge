#!/usr/bin/env python3
"""
Generate a migration playbook that uses direct API calls with actual credential type IDs.
This fixes the Jinja2 evaluation issue in nested JSON.
"""

import json
import os
import sys
import yaml
from pathlib import Path
import requests
from urllib3.exceptions import InsecureRequestWarning

# Suppress SSL warnings
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)


def get_target_credential_types(target_url, target_token):
    """Get credential type mappings from target AAP."""
    print("📥 Fetching credential types from target AAP...")

    headers = {"Authorization": f"Bearer {target_token}"}
    response = requests.get(
        f"{target_url}/credential_types/?page_size=100",
        headers=headers,
        verify=False
    )
    response.raise_for_status()

    type_map = {}
    for ct in response.json()["results"]:
        type_map[ct["name"]] = ct["id"]

    print(f"   Found {len(type_map)} credential types")
    return type_map


def get_target_organizations(target_url, target_token):
    """Get organization mappings from target AAP."""
    print("📥 Fetching organizations from target AAP...")

    headers = {"Authorization": f"Bearer {target_token}"}
    response = requests.get(
        f"{target_url}/organizations/?page_size=100",
        headers=headers,
        verify=False
    )
    response.raise_for_status()

    org_map = {}
    for org in response.json()["results"]:
        org_map[org["name"]] = org["id"]

    print(f"   Found {len(org_map)} organizations")
    return org_map


def convert_to_direct_api_playbook(filled_playbook_path, metadata_path, output_path, target_url, target_token):
    """Convert awx.awx.credential tasks to direct API uri tasks with actual IDs."""

    print(f"📝 Reading filled playbook: {filled_playbook_path}")
    with open(filled_playbook_path, 'r') as f:
        playbook_data = yaml.safe_load(f)

    print(f"📝 Reading credential metadata: {metadata_path}")
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)

    # Get live mappings from target AAP
    credential_type_map = get_target_credential_types(target_url, target_token)
    organization_map = get_target_organizations(target_url, target_token)

    # Build source credential type ID to name mapping
    source_type_map = {int(k): v for k, v in metadata["credential_types"].items()}

    play = playbook_data[0]
    original_tasks = play['tasks']

    print(f"🔄 Converting {len(original_tasks)} tasks to direct API calls...")

    # Update vars - no Jinja2 needed, we'll use actual values
    play['vars'] = {
        'target_controller_url': target_url,
        'target_controller_token': "{{ lookup('env', 'TARGET__TOKEN') }}"
    }

    new_tasks = []
    created_count = 0
    failed_count = 0

    # Convert each credential task
    for idx, task in enumerate(original_tasks, 1):
        awx_params = task.get('awx.awx.credential', {})

        cred_name = awx_params.get('name', 'Unknown')
        cred_desc = awx_params.get('description', '')
        cred_type_name = awx_params.get('credential_type', 'Machine')
        org_name = awx_params.get('organization')
        inputs = awx_params.get('inputs', {})

        # Resolve credential type to actual numeric ID
        target_cred_type_id = credential_type_map.get(cred_type_name)
        if not target_cred_type_id:
            print(f"   ⚠️  Warning: Credential type '{cred_type_name}' not found in target, using default (1)")
            target_cred_type_id = 1

        # Build API payload with ACTUAL numeric values, not Jinja2
        payload = {
            'name': cred_name,
            'description': cred_desc,
            'credential_type': target_cred_type_id,  # Actual numeric ID!
        }

        # Resolve organization to actual numeric ID
        if org_name:
            target_org_id = organization_map.get(org_name)
            if target_org_id:
                payload['organization'] = target_org_id  # Actual numeric ID!
            else:
                print(f"   ⚠️  Warning: Organization '{org_name}' not found in target for credential '{cred_name}'")
                # AAP 2.6 requires organization, user, or team
                payload['organization'] = 1  # Default organization

        # If no organization was specified, AAP 2.6 requires one
        if 'organization' not in payload:
            payload['organization'] = 1  # Default organization

        if inputs:
            payload['inputs'] = inputs

        # Create task with direct API call
        new_task = {
            'name': f"Create credential: {cred_name}",
            'uri': {
                'url': '{{ target_controller_url }}/credentials/',
                'method': 'POST',
                'headers': {
                    'Authorization': 'Bearer {{ target_controller_token }}',
                    'Content-Type': 'application/json'
                },
                'body': payload,
                'body_format': 'json',
                'validate_certs': False,
                'status_code': [201, 400]
            },
            'register': f'credential_{idx}_result',
            'ignore_errors': True
        }

        new_tasks.append(new_task)

        # Add conditional debug based on status
        new_tasks.append({
            'name': f"✅ Created: {cred_name}",
            'debug': {
                'msg': "Credential created successfully (ID: {{ credential_" + str(idx) + "_result.json.id }})"
            },
            'when': f"credential_{idx}_result.status == 201"
        })

        new_tasks.append({
            'name': f"⚠️  Skipped: {cred_name}",
            'debug': {
                'msg': "{{ credential_" + str(idx) + "_result.json }}"
            },
            'when': f"credential_{idx}_result.status == 400"
        })

    play['tasks'] = new_tasks

    # Save new playbook
    print(f"💾 Saving improved direct API playbook to: {output_path}")
    with open(output_path, 'w') as f:
        f.write("---\n")
        f.write("# CREDENTIAL MIGRATION PLAYBOOK - Direct API Version (Fixed)\n")
        f.write("# Uses direct REST API calls with actual numeric IDs\n")
        f.write("# No Jinja2 evaluation issues - all IDs resolved at generation time\n\n")
        yaml.dump([play], f, default_flow_style=False, sort_keys=False, width=120)

    print(f"✅ Generated playbook with {len(new_tasks)} tasks")
    print(f"   ({len(original_tasks)} credential tasks x 3 tasks each)")

    return output_path


def main():
    filled_playbook = Path('credential_migration/migrate_credentials_filled.yml')
    metadata_file = Path('credential_migration/credentials_metadata.json')
    output_playbook = Path('credential_migration/migrate_credentials_fixed.yml')

    if not filled_playbook.exists():
        print(f"❌ ERROR: Filled playbook not found: {filled_playbook}")
        return 1

    if not metadata_file.exists():
        print(f"❌ ERROR: Metadata file not found: {metadata_file}")
        return 1

    # Get target credentials from environment
    target_url = os.getenv("TARGET__URL", "https://localhost:10443/api/controller/v2")
    target_token = os.getenv("TARGET__TOKEN")

    if not target_token:
        print("❌ ERROR: TARGET__TOKEN environment variable not set")
        print("   Run: export TARGET__TOKEN='your_token'")
        return 1

    print("🔄 Converting awx.awx playbook to improved direct API playbook")
    print("=" * 70)
    print(f"Target AAP: {target_url}")
    print()

    try:
        output_path = convert_to_direct_api_playbook(
            filled_playbook,
            metadata_file,
            output_playbook,
            target_url,
            target_token
        )

        print()
        print("=" * 70)
        print("✅ Improved direct API playbook generated successfully!")
        print()
        print("🔑 Key improvements:")
        print("   ✅ Uses actual numeric credential_type IDs (not Jinja2)")
        print("   ✅ Uses actual numeric organization IDs (not Jinja2)")
        print("   ✅ Always includes organization (AAP 2.6 requirement)")
        print("   ✅ Better error handling and debugging")
        print()
        print("🚀 Run migration:")
        print(f"   export TARGET__TOKEN='<your_token>'")
        print(f"   ansible-playbook {output_path}")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main() or 0)
