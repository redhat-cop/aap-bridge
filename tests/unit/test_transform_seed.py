from aap_migration.cli.commands.transform import (
    credential_types_support_managed_filter,
    is_builtin_credential_type,
)


def test_credential_types_support_managed_filter() -> None:
    assert credential_types_support_managed_filter("2.3") is True
    assert credential_types_support_managed_filter("2.6") is True
    assert credential_types_support_managed_filter("1.0") is False
    assert credential_types_support_managed_filter("2.2") is False


def test_is_builtin_credential_type() -> None:
    assert is_builtin_credential_type({"managed": True, "name": "Machine"}) is True
    assert is_builtin_credential_type({"namespace": "tower", "name": "Ansible Tower"}) is True
    assert is_builtin_credential_type({"name": "Custom"}) is False
