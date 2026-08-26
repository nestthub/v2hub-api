"""
Tests for `v2hub_api.utils.auth_hmac`.

These helpers bind a `(user_id, provider_hash)` pair for the provider
connection invite-link flow (see `provider.py`'s `create_connection` for
unknown users, and `admin/provider_authorization.py`'s
`process_provider_authorization_request` for where the HMAC gets
verified). If this HMAC could be forged or bypassed, any caller who knew
a target `user_id` could get a provider authorized against that user
without the user ever confirming anything -- so these are effectively
security-critical, even though the module itself is small.
"""

import hashlib
import hmac

import pytest

from v2hub_api.core.constants import AUTH_HMAC_LENGTH
from v2hub_api.utils.auth_hmac import generate_auth_hmac, verify_auth_hmac

SECRET = "test-hmac-secret"


class TestGenerateAuthHmac:
    def test_returns_hex_string_of_expected_length(self):
        digest = generate_auth_hmac(user_id=42, provider_hash="prov123", secret=SECRET)

        assert len(digest) == AUTH_HMAC_LENGTH
        # Must be valid hex (truncated hex digest, not raw bytes).
        int(digest, 16)

    def test_is_deterministic_for_same_inputs(self):
        first = generate_auth_hmac(42, "prov123", SECRET)
        second = generate_auth_hmac(42, "prov123", SECRET)

        assert first == second

    def test_differs_when_user_id_changes(self):
        a = generate_auth_hmac(42, "prov123", SECRET)
        b = generate_auth_hmac(43, "prov123", SECRET)

        assert a != b

    def test_differs_when_provider_hash_changes(self):
        a = generate_auth_hmac(42, "prov123", SECRET)
        b = generate_auth_hmac(42, "prov456", SECRET)

        assert a != b

    def test_differs_when_secret_changes(self):
        a = generate_auth_hmac(42, "prov123", SECRET)
        b = generate_auth_hmac(42, "prov123", "a-different-secret")

        assert a != b

    def test_matches_manual_hmac_sha256_computation(self):
        """
        Pin down the exact signing scheme (payload format + algorithm),
        so a refactor can't silently change it in a way that breaks
        already-issued (but not yet consumed) invite links.
        """
        expected_full_digest = hmac.new(SECRET.encode(), b"42:prov123", hashlib.sha256).hexdigest()

        digest = generate_auth_hmac(42, "prov123", SECRET)

        assert digest == expected_full_digest[:AUTH_HMAC_LENGTH]

    def test_truncates_rather_than_returning_full_digest(self):
        digest = generate_auth_hmac(42, "prov123", SECRET)
        full_digest = hmac.new(SECRET.encode(), b"42:prov123", hashlib.sha256).hexdigest()

        assert digest == full_digest[: len(digest)]
        assert len(digest) < len(full_digest)


class TestVerifyAuthHmac:
    def test_accepts_matching_hmac(self):
        digest = generate_auth_hmac(42, "prov123", SECRET)

        assert verify_auth_hmac(42, "prov123", SECRET, digest) is True

    def test_rejects_tampered_user_id(self):
        digest = generate_auth_hmac(42, "prov123", SECRET)

        assert verify_auth_hmac(999, "prov123", SECRET, digest) is False

    def test_rejects_tampered_provider_hash(self):
        digest = generate_auth_hmac(42, "prov123", SECRET)

        assert verify_auth_hmac(42, "someone-elses-provider", SECRET, digest) is False

    def test_rejects_wrong_secret(self):
        digest = generate_auth_hmac(42, "prov123", SECRET)

        assert verify_auth_hmac(42, "prov123", "wrong-secret", digest) is False

    def test_rejects_garbage_hmac(self):
        assert verify_auth_hmac(42, "prov123", SECRET, "not-a-real-hmac") is False

    def test_rejects_empty_hmac(self):
        assert verify_auth_hmac(42, "prov123", SECRET, "") is False

    @pytest.mark.parametrize("user_id", [0, 1, -1, 2**31 - 1])
    def test_round_trips_for_edge_case_user_ids(self, user_id):
        digest = generate_auth_hmac(user_id, "prov123", SECRET)

        assert verify_auth_hmac(user_id, "prov123", SECRET, digest) is True
