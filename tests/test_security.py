import pytest
from fastapi import HTTPException

from app.core.security import (
    create_access_token,
    create_oauth_state_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_password_and_verify():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_roundtrip():
    token = create_access_token(42)
    payload = decode_token(token, "access")
    assert payload["sub"] == "42"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip():
    token = create_refresh_token(7)
    payload = decode_token(token, "refresh")
    assert payload["sub"] == "7"
    assert payload["type"] == "refresh"


def test_decode_token_wrong_type_rejected():
    token = create_access_token(1)
    with pytest.raises(HTTPException) as exc_info:
        decode_token(token, "refresh")
    assert exc_info.value.status_code == 401


def test_decode_token_invalid_signature_rejected():
    with pytest.raises(HTTPException):
        decode_token("not-a-real-jwt", "access")


def test_oauth_state_token_carries_purpose_and_user():
    token = create_oauth_state_token(user_id=5, purpose="connect_gmail")
    payload = decode_token(token, "oauth_state")
    assert payload["sub"] == "5"
    assert payload["purpose"] == "connect_gmail"


def test_oauth_state_token_without_user_defaults_to_zero():
    token = create_oauth_state_token(user_id=None, purpose="login")
    payload = decode_token(token, "oauth_state")
    assert payload["sub"] == "0"
