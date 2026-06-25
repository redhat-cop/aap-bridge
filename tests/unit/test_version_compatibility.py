import pytest

from aap_migration.resources import COMPATIBILITY_MATRIX, get_version_path

SOURCE_VERSIONS_UP_TO_26 = [
    "1.0",
    "1.1",
    "1.2",
    "2.0",
    "2.1",
    "2.2",
    "2.3",
    "2.4",
    "2.5",
    "2.6",
]
SOURCE_VERSIONS_UP_TO_27 = SOURCE_VERSIONS_UP_TO_26 + ["2.7"]


@pytest.mark.parametrize("source_version", SOURCE_VERSIONS_UP_TO_26)
def test_version_path_lookup_to_26(source_version):
    """Every declared source through 2.6 has a compatibility entry for 2.6."""
    path = get_version_path(source_version, "2.6.0")
    assert path is not None
    assert path.status in ("supported", "partial", "unsupported")
    assert path.source == source_version
    assert path.target == "2.6"


@pytest.mark.parametrize("source_version", SOURCE_VERSIONS_UP_TO_27)
def test_version_path_lookup_to_27(source_version):
    """Every declared source through 2.7 has a compatibility entry for 2.7."""
    path = get_version_path(source_version, "2.7.0")
    assert path is not None
    assert path.status in ("supported", "partial", "unsupported")
    assert path.source == source_version
    assert path.target == "2.7"


def test_version_path_major_minor_matching():
    """Test that patch versions are ignored during lookup."""
    path1 = get_version_path("2.3.0", "2.6.0")
    path2 = get_version_path("2.3.5", "2.6.12")
    path3 = get_version_path("2.6.1", "2.7.3")

    assert path1 is not None
    assert path2 is not None
    assert path3 is not None
    assert path1 == path2
    assert path3.target == "2.7"


def test_version_path_unsupported():
    """Test lookup for unsupported version pair."""
    # Target 2.8 is not in our matrix
    path = get_version_path("2.3.0", "2.8.0")
    assert path is None

    # Source 3.0 is not in our matrix
    path = get_version_path("3.0.0", "2.6.0")
    assert path is None

    # 2.7 source to 2.6 target is not a declared path
    path = get_version_path("2.7.0", "2.6.0")
    assert path is None


def test_version_path_has_notes():
    """Every compatibility entry has notes and known_exceptions."""
    for path in COMPATIBILITY_MATRIX:
        assert path.notes
        assert isinstance(path.known_exceptions, list)
        assert len(path.known_exceptions) > 0


def test_version_path_invalid_input():
    """Test lookup with invalid/empty inputs."""
    assert get_version_path("", "2.6.0") is None
    assert get_version_path("2.3.0", "") is None
    assert get_version_path(None, "2.6.0") is None
