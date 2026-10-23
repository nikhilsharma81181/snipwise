import logging

import pytest

from src.auth.exceptions import INVALID_CREDENTIALS
from src.exceptions import CATALOG, AppError, ErrorSpec

WRONG_LOGIN = {"email": "nobody@test.com", "password": "wrongpass1"}


def test_duplicate_code_is_rejected():
    # the client branches on codes, two meanings for one code would be a bug
    with pytest.raises(ValueError, match="duplicate"):
        ErrorSpec("invalid_credentials", 400, "something else")


def test_codes_are_snake_case():
    for code in CATALOG:
        assert code == code.lower() and " " not in code, code


def test_message_params_are_filled_in():
    spec = ErrorSpec("test_params", 400, "try again in {seconds}s")
    assert AppError(spec, params={"seconds": 7}).message == "try again in 7s"
    del CATALOG["test_params"]


async def test_handler_uses_spec_status_code_and_message(client):
    res = await client.post("/api/auth/login", json=WRONG_LOGIN)
    assert res.status_code == INVALID_CREDENTIALS.http_status
    assert res.json() == {
        "code": INVALID_CREDENTIALS.code,
        "message": INVALID_CREDENTIALS.message,
    }


async def test_handler_logs_at_spec_level(client, caplog):
    with caplog.at_level(logging.INFO, logger="src.exceptions"):
        await client.post("/api/auth/login", json=WRONG_LOGIN)

    record = next(r for r in caplog.records if "invalid_credentials" in r.getMessage())
    assert record.levelno == logging.INFO
    # no stack trace for an expected error
    assert not record.exc_info
