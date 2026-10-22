from uuid import UUID

from database.locks import advisory_lock_key


def test_advisory_lock_key_is_stable_and_resource_scoped() -> None:
    workspace_id = UUID("00000000-0000-7000-8000-000000000003")

    first = advisory_lock_key(workspace_id, "search-index-write")
    second = advisory_lock_key(workspace_id, "search-index-write")
    other = advisory_lock_key(workspace_id, "object-storage-write")

    assert first == second
    assert first != other
    assert -(2**63) <= first < 2**63
