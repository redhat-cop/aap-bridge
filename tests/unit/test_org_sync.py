"""Behavior tests with two organizations and differently allocated target IDs."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from aap_migration.org_sync import SyncError, list_all, reconcile, synchronize

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/org_sync"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class MemoryClient:
    def __init__(self, snapshots=(), writable=True):
        self.tables = {
            key: []
            for key in ("organizations", "inventories", "hosts", "projects", "job_templates")
        }
        self.writes = []
        self.writable = writable
        self.next_id = 1000
        for snapshot in snapshots:
            self.tables["organizations"].append(deepcopy(snapshot["organizations"]))
            for kind in self.tables:
                if kind != "organizations":
                    self.tables[kind].extend(deepcopy(snapshot[kind]))
        for template in self.tables["job_templates"]:
            project = next(
                row for row in self.tables["projects"] if row["id"] == template["project"]
            )
            template["organization"] = project["organization"]
        for project in self.tables["projects"]:
            project["status"] = "successful"

    async def get(self, endpoint, params=None):
        bits = endpoint.strip("/").split("/")
        if len(bits) == 3:
            if bits[0] == "job_templates" and bits[2] == "credentials":
                rows = []
            elif bits[0] == "inventories" and bits[2] == "hosts":
                rows = [row for row in self.tables["hosts"] if row["inventory"] == int(bits[1])]
            else:
                raise AssertionError(endpoint)
        else:
            rows = self.tables[bits[0]]
            if len(bits) == 2:
                return deepcopy(next(row for row in rows if row["id"] == int(bits[1])))
        for key, value in (params or {}).items():
            if key not in ("page", "page_size"):
                rows = [row for row in rows if row.get(key) == value]
        return {"results": deepcopy(rows), "count": len(rows), "next": None}

    async def post(self, endpoint, json_data):
        if not self.writable:
            raise AssertionError("Source must never be mutated by sync")
        kind = endpoint.strip("/")
        row = {**deepcopy(json_data), "id": self.next_id}
        self.next_id += 1
        if kind == "projects":
            row["status"] = "successful"
        if kind == "job_templates":
            row["organization"] = next(
                item["organization"]
                for item in self.tables["projects"]
                if item["id"] == row["project"]
            )
        self.tables[kind].append(row)
        self.writes.append(("POST", endpoint, deepcopy(json_data)))
        return deepcopy(row)

    async def patch(self, endpoint, json_data):
        if not self.writable:
            raise AssertionError("Source must never be mutated by sync")
        kind, object_id = endpoint.strip("/").split("/")
        row = next(row for row in self.tables[kind] if row["id"] == int(object_id))
        row.update(deepcopy(json_data))
        self.writes.append(("PATCH", endpoint, deepcopy(json_data)))
        return deepcopy(row)


class TestOrgSync(unittest.IsolatedAsyncioTestCase):
    async def test_plan_is_read_only_and_scoped(self):
        source = MemoryClient([fixture("revision-1"), fixture("control")], writable=False)
        target = MemoryClient([fixture("control")])
        before = deepcopy(target.tables)
        report = await synchronize(source, target, "aap-bridge")
        self.assertEqual(report["summary"], {"create": 6})
        self.assertEqual(target.tables, before)
        self.assertEqual(target.writes, [])

    async def test_initial_sync_updates_and_second_run_noop_preserve_control(self):
        target = MemoryClient([fixture("control")])
        control_before = deepcopy(target.tables)
        first = await synchronize(
            MemoryClient([fixture("revision-1")], writable=False), target, "aap-bridge", apply=True
        )
        self.assertEqual(first["summary"], {"create": 6})
        # Target PKs differ from source PKs; host/template links must use target PKs.
        inventory = next(row for row in target.tables["inventories"] if row["id"] != 90)
        host = next(row for row in target.tables["hosts"] if row["id"] != 901)
        self.assertEqual(host["inventory"], inventory["id"])
        self.assertNotEqual(host["inventory"], 10)
        target.writes.clear()
        noop = await synchronize(
            MemoryClient([fixture("revision-1")], writable=False), target, "aap-bridge", apply=True
        )
        self.assertEqual(noop["summary"], {"unchanged": 6})
        self.assertEqual(target.writes, [])
        second = await synchronize(
            MemoryClient([fixture("revision-2")], writable=False), target, "aap-bridge", apply=True
        )
        self.assertEqual(second["summary"], {"unchanged": 3, "update": 3, "create": 2})
        target.writes.clear()
        final = await synchronize(
            MemoryClient([fixture("revision-2")], writable=False), target, "aap-bridge", apply=True
        )
        self.assertEqual(final["summary"], {"unchanged": 8})
        self.assertEqual(target.writes, [])
        for kind, rows in control_before.items():
            for row in rows:
                actual = next(item for item in target.tables[kind] if item["id"] == row["id"])
                self.assertEqual(actual, row)

    async def test_cross_org_dependency_aborts_before_writes(self):
        data = fixture("revision-1")
        data["job_templates"][0]["inventory"] = 90
        target = MemoryClient([fixture("control")])
        with self.assertRaisesRegex(SyncError, "outside the selected organization"):
            await reconcile(data, target, "aap-bridge", apply=True)
        self.assertEqual(target.writes, [])

    async def test_api_filter_leak_is_rejected(self):
        class LeakyClient(MemoryClient):
            async def get(self, endpoint, params=None):
                if endpoint == "inventories/":
                    return {"results": deepcopy(self.tables["inventories"]), "next": None}
                return await super().get(endpoint, params)

        source = LeakyClient([fixture("revision-1"), fixture("control")], writable=False)
        target = MemoryClient()
        with self.assertRaisesRegex(SyncError, "outside the requested organization"):
            await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(target.writes, [])

    async def test_duplicate_names_and_unsupported_resources_abort_before_writes(self):
        for case in ("duplicate", "dynamic", "credential", "survey"):
            with self.subTest(case=case):
                data = fixture("revision-1")
                if case == "duplicate":
                    data["inventories"].append({**data["inventories"][0], "id": 11})
                elif case == "dynamic":
                    data["inventories"][0]["has_inventory_sources"] = True
                elif case == "credential":
                    data["projects"][0]["credential"] = 5
                else:
                    data["job_templates"][0]["survey_enabled"] = True
                target = MemoryClient()
                with self.assertRaises(SyncError):
                    await reconcile(data, target, "aap-bridge", apply=True)
                self.assertEqual(target.writes, [])

    async def test_equivalent_yaml_variables_do_not_create_drift(self):
        source = MemoryClient([fixture("revision-1")], writable=False)
        target = MemoryClient()
        await synchronize(source, target, "aap-bridge", apply=True)
        target.tables["inventories"][0][
            "variables"
        ] = 'demo_revision: 1\napp_version: "1.0"\nansible_connection: local\n'
        target.writes.clear()
        report = await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(report["summary"], {"unchanged": 6})
        self.assertEqual(target.writes, [])

    async def test_target_only_resources_are_retained(self):
        source = MemoryClient([fixture("revision-1")], writable=False)
        target = MemoryClient()
        await synchronize(source, target, "aap-bridge", apply=True)
        extra = {
            "id": 9000,
            "name": "target-only",
            "inventory": target.tables["inventories"][0]["id"],
            "variables": "{}",
            "enabled": True,
        }
        target.tables["hosts"].append(extra)
        target.writes.clear()
        await synchronize(source, target, "aap-bridge", apply=True)
        self.assertIn(extra, target.tables["hosts"])
        self.assertEqual(target.writes, [])

    async def test_pagination_keeps_scope_parameters(self):
        calls = []

        class PaginatedClient:
            async def get(self, endpoint, params):
                calls.append(params)
                return {
                    "results": [{"id": params["page"]}],
                    "next": "more" if params["page"] == 1 else None,
                }

        rows = await list_all(PaginatedClient(), "inventories/", organization=12)
        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertTrue(all(call["organization"] == 12 for call in calls))

    async def test_git_refspec_is_created_and_updated(self):
        data = fixture("revision-1")
        data["projects"][0]["scm_refspec"] = "+refs/heads/*:refs/remotes/origin/*"
        source = MemoryClient([data], writable=False)
        target = MemoryClient()
        await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(
            target.tables["projects"][0]["scm_refspec"], data["projects"][0]["scm_refspec"]
        )
        source.tables["projects"][0]["scm_refspec"] = "+refs/pull/*:refs/remotes/origin/pr/*"
        target.writes.clear()
        await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(len(target.writes), 1)
        self.assertEqual(
            target.writes[0][2], {"scm_refspec": "+refs/pull/*:refs/remotes/origin/pr/*"}
        )


if __name__ == "__main__":
    unittest.main()
