from __future__ import annotations

import pytest

from safemeal.interfaces.http.authentication import Principal, authorize_user_id


def test_principal_scopes_storage_identity_to_tenant() -> None:
    principal = Principal(subject="alice", tenant_id="kitchen-a")

    assert principal.storage_subject == "kitchen-a:alice"
    assert authorize_user_id(principal, "alice") == "kitchen-a:alice"


def test_principal_cannot_claim_another_user() -> None:
    principal = Principal(subject="alice", tenant_id="kitchen-a")

    with pytest.raises(Exception):
        authorize_user_id(principal, "bob")
