from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import auth
from models import PasswordChange
from routers.auth_routes import change_password


def connection_with_cursor():
    conn = MagicMock()
    return conn, conn.cursor.return_value.__enter__.return_value


def test_change_password_rejects_wrong_current():
    conn, cur = connection_with_cursor()
    cur.fetchone.return_value = {"password_hash": auth.hash_password("old-password-ok")}
    with pytest.raises(HTTPException) as error:
        change_password(
            PasswordChange(current_password="wrong-password", new_password="new-password-1"),
            {"id": str(uuid4())},
            conn,
        )
    assert error.value.status_code == 400
    assert error.value.detail == "current_password_incorrect"
    conn.commit.assert_not_called()


def test_change_password_rejects_same_password():
    conn, cur = connection_with_cursor()
    cur.fetchone.return_value = {"password_hash": auth.hash_password("same-pass-1")}
    with pytest.raises(HTTPException) as error:
        change_password(
            PasswordChange(current_password="same-pass-1", new_password="same-pass-1"),
            {"id": str(uuid4())},
            conn,
        )
    assert error.value.status_code == 400
    assert error.value.detail == "password_unchanged"
    conn.commit.assert_not_called()


def test_change_password_rejects_short_new_password():
    with pytest.raises(ValidationError):
        PasswordChange(current_password="old-password-ok", new_password="short")


def test_change_password_updates_hash():
    conn, cur = connection_with_cursor()
    user_id = str(uuid4())
    cur.fetchone.return_value = {"password_hash": auth.hash_password("old-password-ok")}
    result = change_password(
        PasswordChange(current_password="old-password-ok", new_password="new-password-1"),
        {"id": user_id},
        conn,
    )
    assert result == {"ok": True}
    password_update = next(
        call for call in cur.execute.call_args_list
        if "SET password_hash" in call.args[0]
    )
    args = password_update.args[1]
    assert auth.verify_password("new-password-1", args[0])
    assert args[1] == user_id
    conn.commit.assert_called_once()
