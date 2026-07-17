#!/usr/bin/env python3
"""Populate an AAP/AWX instance with realistic test data."""

from __future__ import annotations

import argparse
import base64
import json
import random
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

SIZES = {
    "small": {"orgs": (4, 6), "per_org": (8, 12), "cred_types": (8, 12), "notif": (2, 4)},
    "med": {"orgs": (15, 25), "per_org": (8, 12), "cred_types": (20, 30), "notif": (3, 5)},
    "large": {"orgs": (40, 60), "per_org": (15, 25), "cred_types": (40, 60), "notif": (5, 10)},
    "xl": {"orgs": (80, 120), "per_org": (80, 120), "cred_types": (80, 120), "notif": (10, 20)},
    "xxl": {"orgs": (90, 110), "per_org": (450, 550), "cred_types": (80, 120), "notif": (15, 25)},
}


@dataclass
class State:
    org_ids: list[int] = field(default_factory=list)
    user_ids: list[int] = field(default_factory=list)
    team_ids: list[int] = field(default_factory=list)
    cred_type_ids: list[int] = field(default_factory=list)
    cred_ids: list[int] = field(default_factory=list)
    project_ids: list[int] = field(default_factory=list)
    inv_ids: list[int] = field(default_factory=list)
    host_ids: list[int] = field(default_factory=list)
    group_ids: list[int] = field(default_factory=list)
    jt_ids: list[int] = field(default_factory=list)
    wfjt_ids: list[int] = field(default_factory=list)
    demo_project_id: int | None = None
    created: int = 0
    failed: int = 0
    org_inv_map: dict[int, list[int]] = field(default_factory=dict)
    org_proj_map: dict[int, list[int]] = field(default_factory=dict)


class AAPClient:
    def __init__(
        self,
        host: str,
        token: str | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.base = host.rstrip("/") + "/api/v2"
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        if token:
            self._auth_header = f"Bearer {token}"
        elif username is not None and password is not None:
            creds = base64.b64encode(f"{username}:{password}".encode()).decode()
            self._auth_header = f"Basic {creds}"
        else:
            raise ValueError("Either token or username/password is required")

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {"Authorization": self._auth_header}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def post(self, endpoint: str, data: dict) -> dict | None:
        url = f"{self.base}/{endpoint}/"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers=self._headers(json_body=True),
        )
        try:
            with urllib.request.urlopen(req, context=self.ctx) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError:
            return None

    def get(self, endpoint: str, params: str = "") -> dict | None:
        url = f"{self.base}/{endpoint}/"
        if params:
            url += f"?{params}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, context=self.ctx) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError:
            return None


def rand(lo: int, hi: int) -> int:
    return random.randint(lo, hi)


def progress(label: str, i: int, total: int, extra: str = "") -> None:
    bar_len = 30
    filled = int(bar_len * i / max(total, 1))
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = int(100 * i / max(total, 1))
    suffix = f" {extra}" if extra else ""
    print(f"\r  {label:30s} {bar} {pct:3d}% ({i}/{total}){suffix}", end="", flush=True)
    if i >= total:
        print()


def populate(client: AAPClient, size_name: str) -> None:
    cfg = SIZES[size_name]
    st = State()

    num_orgs = rand(*cfg["orgs"])
    per_org = cfg["per_org"]
    num_cred_types = rand(*cfg["cred_types"])
    notif_range = cfg["notif"]

    # --- Find Demo Project ---
    resp = client.get("projects", "status=successful&page_size=1")
    if resp and resp.get("results"):
        st.demo_project_id = resp["results"][0]["id"]
        print(f"Using Demo Project id={st.demo_project_id}")
    else:
        print("WARNING: No synced project found. Job templates will be skipped.")

    # --- Organizations ---
    total = num_orgs
    print(f"\n=== Organizations ({total}) ===")
    for i in range(total):
        progress("Organizations", i, total)
        r = client.post(
            "organizations", {"name": f"TestOrg-{i + 1}", "description": f"Test org {i + 1}"}
        )
        if r:
            st.org_ids.append(r["id"])
            st.created += 1
        else:
            st.failed += 1
    progress("Organizations", total, total, f"done ({len(st.org_ids)} created)")

    if not st.org_ids:
        print("ERROR: No orgs created, cannot continue.")
        return

    # --- Users (global, distributed across orgs) ---
    num_users = num_orgs * rand(*per_org)
    print(f"\n=== Users ({num_users}) ===")
    for i in range(num_users):
        if i % 10 == 0:
            progress("Users", i, num_users)
        r = client.post(
            "users",
            {
                "username": f"testuser-{i + 1}",
                "password": "TestPass123!",
                "first_name": random.choice(
                    ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace", "Hank"]
                ),
                "last_name": f"User-{i + 1}",
                "email": f"testuser-{i + 1}@test.example.com",
            },
        )
        if r:
            st.user_ids.append(r["id"])
            st.created += 1
        else:
            st.failed += 1
    progress("Users", num_users, num_users, f"done ({len(st.user_ids)} created)")

    # --- Teams (per org) ---
    num_teams_per = rand(*per_org)
    total_teams = num_orgs * num_teams_per
    print(f"\n=== Teams ({total_teams}, ~{num_teams_per}/org) ===")
    count = 0
    for org_idx, org_id in enumerate(st.org_ids):
        n = rand(max(1, num_teams_per - 2), num_teams_per + 2)
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Teams", count, total_teams)
            r = client.post(
                "teams",
                {
                    "name": f"TestTeam-{org_idx + 1}-{j + 1}",
                    "organization": org_id,
                    "description": f"Team {j + 1} in org {org_idx + 1}",
                },
            )
            if r:
                st.team_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Teams", count, count, f"done ({len(st.team_ids)} created)")

    # --- Credential Types (global) ---
    print(f"\n=== Credential Types ({num_cred_types}) ===")
    for i in range(num_cred_types):
        progress("Credential Types", i, num_cred_types)
        r = client.post(
            "credential_types",
            {
                "name": f"TestCredType-{i + 1}",
                "kind": "cloud",
                "description": f"Custom cred type {i + 1}",
                "inputs": {"fields": [{"id": "token", "type": "string", "label": "API Token"}]},
                "injectors": {},
            },
        )
        if r:
            st.cred_type_ids.append(r["id"])
            st.created += 1
        else:
            st.failed += 1
    progress(
        "Credential Types",
        num_cred_types,
        num_cred_types,
        f"done ({len(st.cred_type_ids)} created)",
    )

    # --- Credentials (per org, ~20% cross-org) ---
    num_creds_per = rand(*per_org)
    total_creds = num_orgs * num_creds_per
    print(f"\n=== Credentials ({total_creds}, ~{num_creds_per}/org) ===")
    count = 0
    for org_idx, org_id in enumerate(st.org_ids):
        n = rand(max(1, num_creds_per - 2), num_creds_per + 2)
        for j in range(n):
            count += 1
            if count % 25 == 0:
                progress("Credentials", count, total_creds)
            ct_id = random.choice(st.cred_type_ids) if st.cred_type_ids else 1
            # ~20% cross-org
            target_org = random.choice(st.org_ids) if random.random() < 0.2 else org_id
            r = client.post(
                "credentials",
                {
                    "name": f"TestCred-{org_idx + 1}-{j + 1}",
                    "credential_type": ct_id,
                    "organization": target_org,
                    "description": f"Cred {j + 1} in org {org_idx + 1}",
                    "inputs": {"token": f"dummy-token-{org_idx + 1}-{j + 1}"},
                },
            )
            if r:
                st.cred_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Credentials", count, count, f"done ({len(st.cred_ids)} created)")

    # --- Projects (per org, scm_type=git but won't sync) ---
    num_proj_per = rand(*per_org)
    total_proj = num_orgs * num_proj_per
    print(f"\n=== Projects ({total_proj}, ~{num_proj_per}/org) ===")
    count = 0
    for org_idx, org_id in enumerate(st.org_ids):
        st.org_proj_map[org_id] = []
        n = rand(max(1, num_proj_per - 2), num_proj_per + 2)
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Projects", count, total_proj)
            r = client.post(
                "projects",
                {
                    "name": f"TestProj-{org_idx + 1}-{j + 1}",
                    "organization": org_id,
                    "scm_type": "git",
                    "scm_url": "https://github.com/ansible/ansible-tower-samples.git",
                    "description": f"Project {j + 1} in org {org_idx + 1}",
                },
            )
            if r:
                st.project_ids.append(r["id"])
                st.org_proj_map[org_id].append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Projects", count, count, f"done ({len(st.project_ids)} created)")

    # --- Inventories (per org, some shared) ---
    num_inv_per = rand(*per_org)
    total_inv = num_orgs * num_inv_per
    print(f"\n=== Inventories ({total_inv}, ~{num_inv_per}/org) ===")
    count = 0
    for org_idx, org_id in enumerate(st.org_ids):
        st.org_inv_map[org_id] = []
        n = rand(max(1, num_inv_per - 2), num_inv_per + 2)
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Inventories", count, total_inv)
            r = client.post(
                "inventories",
                {
                    "name": f"TestInv-{org_idx + 1}-{j + 1}",
                    "organization": org_id,
                    "description": f"Inventory {j + 1} in org {org_idx + 1}",
                },
            )
            if r:
                st.inv_ids.append(r["id"])
                st.org_inv_map[org_id].append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Inventories", count, count, f"done ({len(st.inv_ids)} created)")

    # --- Hosts (per inventory) ---
    num_hosts_per = rand(*per_org)
    # Only populate hosts in a subset of inventories to keep it manageable
    inv_sample = st.inv_ids[: min(len(st.inv_ids), num_orgs * 2)]
    total_hosts = len(inv_sample) * num_hosts_per
    print(
        f"\n=== Hosts ({total_hosts}, ~{num_hosts_per}/inv across {len(inv_sample)} inventories) ==="
    )
    count = 0
    for inv_id in inv_sample:
        n = rand(max(1, num_hosts_per - 2), num_hosts_per + 2)
        for j in range(n):
            count += 1
            if count % 25 == 0:
                progress("Hosts", count, total_hosts)
            r = client.post(
                "hosts",
                {
                    "name": f"host-{inv_id}-{j + 1}.test.example.com",
                    "inventory": inv_id,
                    "description": f"Host {j + 1} in inv {inv_id}",
                    "variables": json.dumps(
                        {
                            "ansible_host": f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
                        }
                    ),
                },
            )
            if r:
                st.host_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Hosts", count, count, f"done ({len(st.host_ids)} created)")

    # --- Groups (per inventory) ---
    num_groups_per = rand(*per_org)
    total_groups = len(inv_sample) * num_groups_per
    print(f"\n=== Groups ({total_groups}, ~{num_groups_per}/inv) ===")
    count = 0
    for inv_id in inv_sample:
        n = rand(max(1, num_groups_per - 2), num_groups_per + 2)
        for j in range(n):
            count += 1
            if count % 25 == 0:
                progress("Groups", count, total_groups)
            r = client.post(
                "groups",
                {
                    "name": f"TestGroup-{inv_id}-{j + 1}",
                    "inventory": inv_id,
                    "description": f"Group {j + 1} in inv {inv_id}",
                },
            )
            if r:
                st.group_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Groups", count, count, f"done ({len(st.group_ids)} created)")

    # --- Job Templates (per org, uses Demo Project) ---
    if st.demo_project_id and st.inv_ids:
        num_jt_per = rand(*per_org)
        total_jt = num_orgs * num_jt_per
        print(f"\n=== Job Templates ({total_jt}, ~{num_jt_per}/org) ===")
        count = 0
        for org_idx, org_id in enumerate(st.org_ids):
            n = rand(max(1, num_jt_per - 2), num_jt_per + 2)
            org_invs = st.org_inv_map.get(org_id, [])
            for j in range(n):
                count += 1
                if count % 10 == 0:
                    progress("Job Templates", count, total_jt)
                # Pick inventory: 80% from same org, 20% from any org
                if org_invs and random.random() < 0.8:
                    inv_id = random.choice(org_invs)
                else:
                    inv_id = random.choice(st.inv_ids)
                r = client.post(
                    "job_templates",
                    {
                        "name": f"TestJT-{org_idx + 1}-{j + 1}",
                        "inventory": inv_id,
                        "project": st.demo_project_id,
                        "playbook": "hello_world.yml",
                        "description": f"Job template {j + 1} in org {org_idx + 1}",
                    },
                )
                if r:
                    st.jt_ids.append(r["id"])
                    st.created += 1
                else:
                    st.failed += 1
        progress("Job Templates", count, count, f"done ({len(st.jt_ids)} created)")
    else:
        print("\n=== Job Templates: SKIPPED (no synced project or inventories) ===")

    # --- Workflow Job Templates (per org) ---
    num_wf_per = max(1, rand(*per_org) // 2)
    total_wf = num_orgs * num_wf_per
    print(f"\n=== Workflow Job Templates ({total_wf}, ~{num_wf_per}/org) ===")
    count = 0
    for org_idx, org_id in enumerate(st.org_ids):
        n = rand(max(1, num_wf_per - 1), num_wf_per + 1)
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Workflow JTs", count, total_wf)
            r = client.post(
                "workflow_job_templates",
                {
                    "name": f"TestWF-{org_idx + 1}-{j + 1}",
                    "organization": org_id,
                    "description": f"Workflow {j + 1} in org {org_idx + 1}",
                },
            )
            if r:
                st.wfjt_ids.append(r["id"])
                st.created += 1
            else:
                st.failed += 1
    progress("Workflow JTs", count, count, f"done ({len(st.wfjt_ids)} created)")

    # --- Notification Templates (per org) ---
    num_notif = rand(*notif_range)
    total_notif = num_orgs * num_notif
    print(f"\n=== Notification Templates ({total_notif}, ~{num_notif}/org) ===")
    count = 0
    notif_created = 0
    for org_idx, org_id in enumerate(st.org_ids):
        n = rand(max(1, num_notif - 1), num_notif + 1)
        for j in range(n):
            count += 1
            if count % 10 == 0:
                progress("Notification Tmpls", count, total_notif)
            if j % 2 == 0:
                notif_data = {
                    "name": f"TestNotif-{org_idx + 1}-{j + 1}",
                    "organization": org_id,
                    "notification_type": "webhook",
                    "notification_configuration": {
                        "url": f"https://hooks.example.com/notify/{org_idx + 1}/{j + 1}",
                        "http_method": "POST",
                        "headers": {"Content-Type": "application/json"},
                    },
                    "description": f"Webhook notification {j + 1} in org {org_idx + 1}",
                }
            else:
                notif_data = {
                    "name": f"TestNotif-{org_idx + 1}-{j + 1}",
                    "organization": org_id,
                    "notification_type": "email",
                    "notification_configuration": {
                        "host": "smtp.example.com",
                        "port": 25,
                        "username": "",
                        "password": "",
                        "use_tls": False,
                        "use_ssl": False,
                        "recipients": [f"test-{org_idx + 1}@example.com"],
                        "sender": f"aap-{org_idx + 1}@example.com",
                    },
                    "description": f"Email notification {j + 1} in org {org_idx + 1}",
                }
            r = client.post("notification_templates", notif_data)
            if r:
                notif_created += 1
                st.created += 1
            else:
                st.failed += 1
    progress("Notification Tmpls", count, count, f"done ({notif_created} created)")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print(f"  Size:          {size_name}")
    print(f"  Organizations: {len(st.org_ids)}")
    print(f"  Users:         {len(st.user_ids)}")
    print(f"  Teams:         {len(st.team_ids)}")
    print(f"  Cred Types:    {len(st.cred_type_ids)}")
    print(f"  Credentials:   {len(st.cred_ids)}")
    print(f"  Projects:      {len(st.project_ids)}")
    print(f"  Inventories:   {len(st.inv_ids)}")
    print(f"  Hosts:         {len(st.host_ids)}")
    print(f"  Groups:        {len(st.group_ids)}")
    print(f"  Job Templates: {len(st.jt_ids)}")
    print(f"  Workflow JTs:  {len(st.wfjt_ids)}")
    print(f"  Notifications: {notif_created}")
    print("  ────────────────────────────")
    print(f"  Total created: {st.created}")
    print(f"  Total failed:  {st.failed}")
    print(f"{'=' * 60}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate AAP/AWX with test data")
    parser.add_argument("--host", required=True, help="AAP URL (e.g. https://localhost:10743)")
    parser.add_argument("--token", help="API Bearer token")
    parser.add_argument("--username", help="Admin username for basic auth (pair setup)")
    parser.add_argument("--password", help="Admin password for basic auth (pair setup)")
    parser.add_argument(
        "--size", choices=list(SIZES.keys()), default="small", help="Data size tier"
    )
    args = parser.parse_args()

    if args.token:
        client = AAPClient(args.host, args.token)
    elif args.username and args.password:
        client = AAPClient(args.host, username=args.username, password=args.password)
    else:
        parser.error("Provide --token or both --username and --password")

    print(f"Populating {args.host} with '{args.size}' test data set")
    resp = client.get("ping")
    if resp is None:
        print(f"ERROR: Cannot reach {args.host}/api/v2/ping/")
        sys.exit(1)
    print(f"Connected. Version: {resp.get('version', 'unknown')}")

    populate(client, args.size)


if __name__ == "__main__":
    main()
