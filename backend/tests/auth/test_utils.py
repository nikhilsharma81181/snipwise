import hashlib
import uuid

import jwt
import pytest

from src.auth.utils import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    hash_token,
    verify_password,
)


async def test_password_round_trip():
    hashed = await hash_password("correct horse")
    assert hashed != "correct horse"
    assert await verify_password("correct horse", hashed)
    assert not await verify_password("wrong", hashed)


def test_access_token_carries_user_and_role():
    uid = uuid.uuid7()
    payload = decode_access_token(create_access_token(uid, "USER"))
    assert payload["userId"] == str(uid)
    assert payload["role"] == "USER"


# a refresh token must never work as an access token (different secret)
def test_refresh_token_is_not_accepted_as_access_token():
    token, _ = create_refresh_token(uuid.uuid7(), "USER")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


def test_hash_token_is_stable_sha256():
    assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()