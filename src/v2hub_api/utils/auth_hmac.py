"""
HMAC helpers for provider connection invite links.

When a provider tries to create a connection for a `user_id` that has no
account yet, the API cannot approve anything server-side -- there is no
user to authorize. Instead it hands back an invite link
(`conn_{hmac}_{provider_name}`) that the user is expected to open (e.g. a
Telegram deep link handled by a bot). Whatever trusted internal service
handles that link calls the admin API to finalize the connection; that
admin call must prove the `(user_id, provider_hash)` pair actually came
from a link this API generated, not from an arbitrary caller guessing a
`user_id`. The HMAC over `(user_id, provider_hash)` is that proof.

The digest is truncated to `AUTH_HMAC_LENGTH` characters purely to keep
invite links short (e.g. for Telegram's `?start=` deep-link payload,
which has a 64-byte limit) -- constant-time comparison still uses the
truncated value on both sides, so the effective security margin is
bounded by the truncated length rather than the full digest.
"""

import hashlib
import hmac

from v2hub_api.core.constants import AUTH_HMAC_LENGTH


def _signing_payload(user_id: int, provider_hash: str) -> bytes:
    return f"{user_id}:{provider_hash}".encode()


def generate_auth_hmac(user_id: int, provider_hash: str, secret: str) -> str:
    """
    Generate a truncated HMAC-SHA256 hex digest binding a user_id to a
    provider_hash, for use in a connection invite link.

    Args:
        user_id: Target Telegram/user ID the invite is for.
        provider_hash: Hash of the provider issuing the invite.
        secret: `settings.auth_hmac_secret`.

    Returns:
        A hex string of length `AUTH_HMAC_LENGTH`.
    """
    digest = hmac.new(secret.encode(), _signing_payload(user_id, provider_hash), hashlib.sha256)
    return digest.hexdigest()[:AUTH_HMAC_LENGTH]


def verify_auth_hmac(user_id: int, provider_hash: str, secret: str, provided_hmac: str) -> bool:
    """
    Verify a truncated HMAC previously produced by `generate_auth_hmac`.

    Uses a constant-time comparison to avoid leaking timing information
    about how many leading characters matched.

    Args:
        user_id: user_id claimed by the caller finalizing the invite.
        provider_hash: provider_hash claimed by the caller.
        secret: `settings.auth_hmac_secret`.
        provided_hmac: The HMAC extracted from the invite link/payload.

    Returns:
        True if `provided_hmac` matches the expected HMAC for this
        (user_id, provider_hash) pair, False otherwise.
    """
    expected = generate_auth_hmac(user_id, provider_hash, secret)
    return hmac.compare_digest(expected, provided_hmac)
