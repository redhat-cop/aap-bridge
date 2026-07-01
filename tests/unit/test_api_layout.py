"""Unit tests for AAP API layout and routing."""

import pytest

from aap_migration.client.api_layout import (
    CONTROLLER_API_PREFIX,
    GATEWAY_API_PREFIX,
    LEGACY_API_PREFIX,
    ApiLayout,
    ApiMode,
    api_topology_from_url,
    build_api_layout,
    join_api_base,
    normalize_host_url,
    normalize_rbac_content_type,
    parse_aap_major_minor,
    strip_api_path_prefix,
    uses_gateway_topology,
)


class TestApiPathConstants:
    def test_join_api_base(self) -> None:
        assert join_api_base("https://aap.example.com", LEGACY_API_PREFIX) == (
            "https://aap.example.com/api/v2"
        )

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/api/controller/v2/organizations/3/", "organizations/3/"),
            ("/api/gateway/v1/users/", "users/"),
            ("/api/v2/projects/1/", "projects/1/"),
            ("api/controller/v2/job_templates/5/", "job_templates/5/"),
        ],
    )
    def test_strip_api_path_prefix(self, path: str, expected: str) -> None:
        assert strip_api_path_prefix(path) == expected

    @pytest.mark.parametrize(
        ("url", "topology"),
        [
            ("https://aap.example.com/api/gateway/v1", "gateway"),
            ("https://aap.example.com/api/controller/v2", "controller"),
            ("https://aap.example.com/api/v2", "legacy"),
        ],
    )
    def test_api_topology_from_url(self, url: str, topology: str) -> None:
        assert api_topology_from_url(url) == topology


class TestNormalizeHostUrl:
    """Tests for normalize_host_url."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://aap.example.com", "https://aap.example.com"),
            ("https://aap.example.com/", "https://aap.example.com"),
            ("https://aap.example.com/api/v2", "https://aap.example.com"),
            ("https://aap.example.com/api/controller/v2", "https://aap.example.com"),
            ("https://aap.example.com/api/gateway/v1", "https://aap.example.com"),
        ],
    )
    def test_strips_api_suffixes(self, raw: str, expected: str) -> None:
        assert normalize_host_url(raw) == expected

    def test_accepts_instance_label(self) -> None:
        assert (
            normalize_host_url("https://aap.example.com", instance="source")
            == "https://aap.example.com"
        )


class TestVersionParsing:
    """Tests for configured version parsing."""

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("2.4", (2, 4)),
            ("2.4.1", (2, 4)),
            ("2.6.20260325", (2, 6)),
            ("1.2", (1, 2)),
        ],
    )
    def test_parse_aap_major_minor(self, version: str, expected: tuple[int, int]) -> None:
        assert parse_aap_major_minor(version) == expected

    @pytest.mark.parametrize(
        ("version", "uses_gateway"),
        [
            ("2.4", False),
            ("2.4.9", False),
            ("2.5", True),
            ("2.6", True),
            ("2.7", True),
        ],
    )
    def test_uses_gateway_topology(self, version: str, uses_gateway: bool) -> None:
        assert uses_gateway_topology(version) is uses_gateway


class TestApiLayoutRouting:
    """Tests for ApiLayout endpoint routing."""

    def test_legacy_routes_all_to_legacy_base(self) -> None:
        layout = ApiLayout(
            host_url="https://aap.example.com",
            mode=ApiMode.LEGACY,
            aap_version="2.4",
            legacy_base="https://aap.example.com/api/v2",
        )
        assert layout.base_for_endpoint("organizations/") == "https://aap.example.com/api/v2"
        assert layout.base_for_endpoint("projects/") == "https://aap.example.com/api/v2"

    def test_gateway_routes_shared_resources_to_gateway(self) -> None:
        layout = ApiLayout(
            host_url="https://aap.example.com",
            mode=ApiMode.GATEWAY,
            aap_version="2.6",
            gateway_base="https://aap.example.com/api/gateway/v1",
            controller_base="https://aap.example.com/api/controller/v2",
        )
        assert layout.base_for_endpoint("organizations/") == "https://aap.example.com/api/gateway/v1"
        assert layout.base_for_endpoint("users/42/") == "https://aap.example.com/api/gateway/v1"
        assert layout.base_for_endpoint("role_definitions/") == (
            "https://aap.example.com/api/gateway/v1"
        )

    def test_gateway_routes_controller_resources(self) -> None:
        layout = ApiLayout(
            host_url="https://aap.example.com",
            mode=ApiMode.GATEWAY,
            aap_version="2.6",
            gateway_base="https://aap.example.com/api/gateway/v1",
            controller_base="https://aap.example.com/api/controller/v2",
        )
        assert layout.base_for_endpoint("projects/") == "https://aap.example.com/api/controller/v2"
        assert layout.base_for_endpoint("inventories/5/hosts/") == (
            "https://aap.example.com/api/controller/v2"
        )

    def test_role_assignments_route_by_content_type(self) -> None:
        layout = ApiLayout(
            host_url="https://aap.example.com",
            mode=ApiMode.GATEWAY,
            aap_version="2.6",
            gateway_base="https://aap.example.com/api/gateway/v1",
            controller_base="https://aap.example.com/api/controller/v2",
        )
        assert layout.base_for_role_assignment("awx.jobtemplate") == (
            "https://aap.example.com/api/controller/v2"
        )
        assert layout.base_for_role_assignment("awx.organization") == (
            "https://aap.example.com/api/gateway/v1"
        )
        assert layout.base_for_role_assignment("shared.organization") == (
            "https://aap.example.com/api/gateway/v1"
        )
        assert layout.base_for_role_assignment("shared.team") == (
            "https://aap.example.com/api/gateway/v1"
        )
        assert layout.role_assignment_bases() == (
            "https://aap.example.com/api/gateway/v1",
            "https://aap.example.com/api/controller/v2",
        )

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/api/controller/v2/organizations/3/", "organizations/3/"),
            ("/api/gateway/v1/users/", "users/"),
            ("/api/v2/projects/1/", "projects/1/"),
        ],
    )
    def test_relative_endpoint_strips_known_prefixes(self, path: str, expected: str) -> None:
        layout = ApiLayout(
            host_url="https://aap.example.com",
            mode=ApiMode.GATEWAY,
            aap_version="2.6",
            legacy_base="https://aap.example.com/api/v2",
            gateway_base="https://aap.example.com/api/gateway/v1",
            controller_base="https://aap.example.com/api/controller/v2",
        )
        assert layout.relative_endpoint(path) == expected


class TestNormalizeRbacContentType:
    """Tests for gateway RBAC content_type normalization."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("shared.organization", "awx.organization"),
            ("shared.team", "awx.team"),
            ("awx.project", "awx.project"),
            (None, None),
        ],
    )
    def test_normalize_aliases(self, raw: str | None, expected: str | None) -> None:
        assert normalize_rbac_content_type(raw) == expected


class TestBuildApiLayout:
    """Tests for build_api_layout."""

    def test_builds_legacy_layout_for_2_4(self) -> None:
        layout = build_api_layout("https://aap24.example.com", "2.4.1")

        assert layout.mode is ApiMode.LEGACY
        assert layout.aap_version == "2.4.1"
        assert layout.legacy_base == join_api_base("https://aap24.example.com", LEGACY_API_PREFIX)
        assert layout.gateway_base is None
        assert layout.controller_base is None

    def test_builds_gateway_layout_for_2_5_plus(self) -> None:
        layout = build_api_layout(
            "https://aap25.example.com/api/controller/v2",
            "2.6",
        )

        assert layout.mode is ApiMode.GATEWAY
        assert layout.host_url == "https://aap25.example.com"
        assert layout.gateway_base == join_api_base("https://aap25.example.com", GATEWAY_API_PREFIX)
        assert layout.controller_base == join_api_base(
            "https://aap25.example.com", CONTROLLER_API_PREFIX
        )
