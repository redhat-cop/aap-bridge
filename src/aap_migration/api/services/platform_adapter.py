import httpx

from aap_migration.api.models import Connection
from aap_migration.api.services.token_crypto import decrypt_token


class PlatformAdapter:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.api_prefix = (
            conn.api_prefix
            if conn.api_prefix is not None
            else ("/api/v2" if conn.type == "awx" else "/api/controller/v2")
        )
        self.base_url = f"{conn.url}{self.api_prefix}"
        self.headers = {}
        token = decrypt_token(conn.token)
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = httpx.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            params=params,
            verify=self.conn.verify_ssl,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected response type for {path}: expected object")
        return data

    def discover_resource_types(self) -> list[dict]:
        data = self._get("/")
        if not isinstance(data, dict):
            return []
        return [
            {"name": key, "label": key.replace("_", " ").title(), "api_path": path}
            for key, path in sorted(data.items())
            if isinstance(path, str)
        ]

    def fetch_all(self, resource_type: str) -> list[dict]:
        results = []
        page = 1
        while True:
            data = self._get(f"/{resource_type}/", params={"page": page, "page_size": 200})
            results.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
        return results

    def list_resources(self, resource_type: str, page: int, page_size: int, search: str) -> dict:
        params: dict = {"page": page, "page_size": page_size}
        if search:
            params["search"] = search
        data = self._get(f"/{resource_type}/", params=params)
        return {
            "count": data.get("count", 0),
            "results": data.get("results", []),
            "page": page,
            "page_size": page_size,
        }
