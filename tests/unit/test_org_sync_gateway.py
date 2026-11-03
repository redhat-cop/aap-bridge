"""Exercise real API routing with deliberately different Gateway/Controller IDs."""

import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from test_org_sync import MemoryClient, fixture

from aap_migration.client.base_client import BaseAPIClient
from aap_migration.org_sync import SyncError, synchronize


class API:
    def __init__(self, snapshots=(), writable=True, gateway=True):
        self.controller = MemoryClient(snapshots, writable=writable)
        self.gateway = gateway
        self.organizations = [
            {**deepcopy(row), "id": 9000 + row["id"]}
            for row in self.controller.tables["organizations"]
        ]
        self.requests = []
        self.hide_controller_org = False

    async def handle(self, request):
        self.requests.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.startswith("/api/gateway/v1/"):
            endpoint = request.url.path.removeprefix("/api/gateway/v1/")
            assert endpoint.startswith("organizations/")
            if request.method == "GET":
                rows = [
                    row for row in self.organizations if row["name"] == request.url.params["name"]
                ]
                return httpx.Response(200, json={"results": rows, "next": None})
            payload = json.loads(request.content)
            if request.method == "POST":
                controller_row = await self.controller.post("organizations/", payload)
                row = {**controller_row, "id": controller_row["id"] + 9000}
                self.organizations.append(row)
                return httpx.Response(201, json=row)
            assert request.method == "PATCH"
            shared_id = int(endpoint.strip("/").split("/")[1])
            row = next(row for row in self.organizations if row["id"] == shared_id)
            controller_row = next(
                item
                for item in self.controller.tables["organizations"]
                if item["name"] == row["name"]
            )
            await self.controller.patch(f"organizations/{controller_row['id']}/", payload)
            row.update(payload)
            return httpx.Response(200, json=row)

        prefix = "/api/controller/v2/" if self.gateway else "/api/v2/"
        assert request.url.path.startswith(prefix), request.url.path
        endpoint = request.url.path.removeprefix(prefix)
        if request.method == "GET":
            if endpoint == "organizations/" and self.hide_controller_org:
                return httpx.Response(200, json={"results": [], "next": None})
            params = {
                key: int(value) if key in ("organization", "page", "page_size") else value
                for key, value in request.url.params.items()
            }
            row = await self.controller.get(endpoint, params)
        elif request.method == "POST":
            assert not endpoint.startswith("organizations/") or not self.gateway
            row = await self.controller.post(endpoint, json.loads(request.content))
        else:
            assert request.method == "PATCH"
            assert not endpoint.startswith("organizations/") or not self.gateway
            row = await self.controller.patch(endpoint, json.loads(request.content))
        return httpx.Response(200, json=row)


class TestGatewaySync(unittest.IsolatedAsyncioTestCase):
    async def client(self, api):
        client = BaseAPIClient(
            host_url="https://aap.example.test",
            token="synthetic-test-token",
            aap_version="2.7" if api.gateway else "2.4",
            rate_limit=0,
        )
        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(api.handle))
        self.addAsyncCleanup(client.close)
        return client

    async def test_gateway_ids_are_remapped_on_both_sides_and_repeat_is_noop(self):
        source_api = API([fixture("revision-1")], writable=False)
        target_api = API([fixture("control")])
        source, target = await self.client(source_api), await self.client(target_api)
        before = deepcopy(target_api.controller.tables)
        plan = await synchronize(source, target, "aap-bridge")
        self.assertEqual(plan["summary"], {"create": 6})
        self.assertEqual(target_api.controller.tables, before)
        first = await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(first["summary"], {"create": 6})
        org = next(row for row in target_api.organizations if row["name"] == "aap-bridge")
        inventory = next(
            row for row in target_api.controller.tables["inventories"] if row["id"] != 90
        )
        self.assertNotEqual(inventory["organization"], org["id"])
        noop = await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(noop["summary"], {"unchanged": 6})
        source_api.organizations[0]["description"] = "updated shared organization"
        await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(org["description"], "updated shared organization")
        self.assertIn(
            ("PATCH", f"/api/gateway/v1/organizations/{org['id']}/", {}), target_api.requests
        )
        self.assertTrue(all(method == "GET" for method, _, _ in source_api.requests))
        for kind, rows in before.items():
            for row in rows:
                self.assertIn(row, target_api.controller.tables[kind])

    async def test_legacy_source_to_gateway_target_uses_controller_foreign_keys(self):
        source = await self.client(API([fixture("revision-1")], writable=False, gateway=False))
        target_api = API()
        target = await self.client(target_api)
        await synchronize(source, target, "aap-bridge", apply=True)
        org_id = target_api.controller.tables["organizations"][0]["id"]
        self.assertTrue(
            all(row["organization"] == org_id for row in target_api.controller.tables["projects"])
        )

    async def test_missing_or_ambiguous_controller_org_aborts_before_target_writes(self):
        for side in ("source", "target"):
            for ambiguous in (False, True):
                with self.subTest(side=side, ambiguous=ambiguous):
                    source_api = API([fixture("revision-1")], writable=False)
                    target_api = API([fixture("revision-1")])
                    selected = source_api if side == "source" else target_api
                    if ambiguous:
                        selected.controller.tables["organizations"].append(
                            {**selected.controller.tables["organizations"][0], "id": 999}
                        )
                    else:
                        selected.controller.tables["organizations"].clear()
                    source, target = await self.client(source_api), await self.client(target_api)
                    with self.assertRaises(SyncError):
                        await synchronize(source, target, "aap-bridge", apply=True)
                    self.assertEqual(target_api.controller.writes, [])

    async def test_new_org_visibility_timeout_stops_content_writes_and_retry_recovers(self):
        source = await self.client(API([fixture("revision-1")], writable=False, gateway=False))
        target_api = API()
        target_api.hide_controller_org = True
        target = await self.client(target_api)
        clock = SimpleNamespace(monotonic=Mock(side_effect=[0, 31]))
        with patch("aap_migration.org_sync.time", clock):
            with self.assertRaisesRegex(SyncError, "not visible on the Controller"):
                await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(len(target_api.controller.writes), 1)
        self.assertEqual(target_api.controller.writes[0][1], "organizations/")
        target_api.hide_controller_org = False
        retry = await synchronize(source, target, "aap-bridge", apply=True)
        self.assertEqual(retry["summary"], {"unchanged": 1, "create": 5})
        self.assertEqual(len(target_api.organizations), 1)


if __name__ == "__main__":
    unittest.main()
