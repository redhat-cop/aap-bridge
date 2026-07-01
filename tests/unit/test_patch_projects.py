"""Unit tests for Phase 2 project patching helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aap_migration.cli.commands.patch_projects import (
    _scm_fields_match,
    classify_project_patch_action,
)
from aap_migration.cli.context import MigrationContext


def _ctx_with_mappings(credential_map: dict[int, int] | None = None) -> MigrationContext:
    ctx = MagicMock(spec=MigrationContext)
    ctx.migration_state = MagicMock()
    ctx.migration_state.get_mapped_id.side_effect = lambda rtype, sid: (
        credential_map.get(sid) if rtype == "credentials" and credential_map else None
    )
    ctx.target_client = AsyncMock()
    return ctx


def test_scm_fields_match_requires_matching_scm_type_and_url() -> None:
    ctx = _ctx_with_mappings()
    deferred = {
        "scm_type": "git",
        "scm_url": "https://example.com/repo.git",
        "scm_branch": "main",
    }
    target = {
        "scm_type": "git",
        "scm_url": "https://example.com/repo.git",
        "scm_branch": "main",
    }
    assert _scm_fields_match(target, deferred, ctx) is True

    target["scm_type"] = ""
    assert _scm_fields_match(target, deferred, ctx) is False


@pytest.mark.asyncio
async def test_classify_project_patch_action_skips_already_configured_project() -> None:
    ctx = _ctx_with_mappings()
    ctx.target_client.get.return_value = {
        "scm_type": "git",
        "scm_url": "https://example.com/repo.git",
        "scm_branch": "main",
        "status": "successful",
    }
    deferred = {
        "scm_type": "git",
        "scm_url": "https://example.com/repo.git",
        "scm_branch": "main",
    }

    action = await classify_project_patch_action(ctx, 42, deferred)

    assert action == "skip"


@pytest.mark.asyncio
async def test_classify_project_patch_action_patches_manual_project() -> None:
    ctx = _ctx_with_mappings()
    ctx.target_client.get.return_value = {
        "scm_type": "",
        "scm_url": "",
        "status": "successful",
    }
    deferred = {
        "scm_type": "git",
        "scm_url": "https://example.com/repo.git",
        "scm_branch": "main",
    }

    action = await classify_project_patch_action(ctx, 42, deferred)

    assert action == "patch"


@pytest.mark.asyncio
async def test_classify_project_patch_action_retries_failed_sync_without_repatch() -> None:
    ctx = _ctx_with_mappings()
    ctx.target_client.get.return_value = {
        "scm_type": "git",
        "scm_url": "https://example.com/repo.git",
        "scm_branch": "main",
        "status": "failed",
    }
    deferred = {
        "scm_type": "git",
        "scm_url": "https://example.com/repo.git",
        "scm_branch": "main",
    }

    action = await classify_project_patch_action(ctx, 42, deferred)

    assert action == "retry_sync"
