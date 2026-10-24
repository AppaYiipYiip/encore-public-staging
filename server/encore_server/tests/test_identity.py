"""Who the server is (docs/11 ADR-R40): a key made once, an id anybody can recompute from it, a signature only the server can make, and the
server's own list of addresses. What a phone does with these answers is `verify`, tested here as the phone's side."""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from encore_server.api import create_app
from encore_server.backup import copy_database
from encore_server.config import Settings, clean_url
from encore_server.db import Database
from encore_server.identity import SETTING_KEY, ServerIdentity, load_or_create, server_id_for, unb64u, verify
from tests.conftest import FakeVerifier, creds
from tests.test_api import V1, sign_in


def nonce() -> str:
    return secrets.token_urlsafe(24)


def identity_of(db: Database) -> ServerIdentity:
    with db.tx() as conn:
        return load_or_create(conn)


# ------------------------------------------------------------------------------------------------ the key


def test_the_key_is_made_once_and_is_the_same_after_a_restart(tmp_path: Path) -> None:
    first = identity_of(_database(tmp_path))
    again = identity_of(_database(tmp_path))  # a new process opening the same file

    assert first.server_id == again.server_id and first.public_key == again.public_key


def test_two_servers_are_two_identities(tmp_path: Path) -> None:
    assert identity_of(_database(tmp_path / "a")).server_id != identity_of(_database(tmp_path / "b")).server_id


def test_a_backup_restored_on_a_new_computer_is_the_same_server(tmp_path: Path) -> None:
    original = _database(tmp_path / "old")
    who = identity_of(original)
    backup = tmp_path / "backup.db"
    copy_database(original.path, backup)

    restored = tmp_path / "new" / "data" / "encore.db"
    restored.parent.mkdir(parents=True)
    shutil.copy(backup, restored)

    assert identity_of(Database(restored)).server_id == who.server_id, "phones that know this server keep knowing it"


def test_the_id_is_26_letters_and_digits_and_is_made_from_the_public_key(tmp_path: Path) -> None:
    who = identity_of(_database(tmp_path))

    assert len(who.server_id) == 26 and set(who.server_id) <= set("abcdefghijklmnopqrstuvwxyz234567")
    assert who.server_id == server_id_for(who.public_key)


def test_the_private_key_is_in_the_database_and_nowhere_in_what_the_server_says(tmp_path: Path, verifier: FakeVerifier) -> None:
    db = _database(tmp_path)
    identity_of(db)
    with db.read() as conn:
        secret_hex = conn.execute("SELECT value FROM setting WHERE key = ?", (SETTING_KEY,)).fetchone()["value"]
    app = create_app(
        Settings(
            data_dir=tmp_path / "data", music_dir=tmp_path / "music", youtube=False, navidrome_url="http://navidrome.invalid"
        ),
        verifier=verifier,
    )

    said = TestClient(app).get(f"{V1}/info", params={"challenge": nonce()}).text

    assert secret_hex not in said


# ------------------------------------------------------------------------------------------------ the phone's check


def test_an_answer_to_my_challenge_from_the_server_i_know_is_accepted(tmp_path: Path) -> None:
    who = identity_of(_database(tmp_path))
    n = nonce()

    answer = who.answer(n)

    assert verify(server_id=who.server_id, public_key=answer["publicKey"], nonce=n, signature=answer["signature"])


def test_an_old_answer_does_not_pass_for_a_new_challenge(tmp_path: Path) -> None:
    who = identity_of(_database(tmp_path))
    old = who.answer(nonce())

    assert not verify(server_id=who.server_id, public_key=old["publicKey"], nonce=nonce(), signature=old["signature"])


def test_somebody_who_copies_the_id_cannot_sign_for_it(tmp_path: Path) -> None:
    real = identity_of(_database(tmp_path / "real"))
    impostor = identity_of(_database(tmp_path / "impostor"))
    n = nonce()

    # Claims the real id, signs with its own key, shows its own public key.
    forged = impostor.answer(n)

    assert not verify(server_id=real.server_id, public_key=forged["publicKey"], nonce=n, signature=forged["signature"])
    # Shows the real public key but cannot make a signature that matches it.
    assert not verify(
        server_id=real.server_id, public_key=real.public_fields()["publicKey"], nonce=n, signature=forged["signature"]
    )


@pytest.mark.parametrize("junk", ["", "not base64 at all !!", "AAAA", "x" * 200])
def test_garbage_is_simply_no(tmp_path: Path, junk: str) -> None:
    who = identity_of(_database(tmp_path))
    good = who.answer(nonce())

    assert not verify(server_id=who.server_id, public_key=junk, nonce="n" * 20, signature=good["signature"])
    assert not verify(server_id=who.server_id, public_key=good["publicKey"], nonce="n" * 20, signature=junk)
    assert not verify(server_id=junk, public_key=good["publicKey"], nonce="n" * 20, signature=good["signature"])


def test_the_public_key_is_32_bytes(tmp_path: Path) -> None:
    assert len(unb64u(identity_of(_database(tmp_path)).public_fields()["publicKey"])) == 32


# ------------------------------------------------------------------------------------------------ the routes


def test_info_names_the_server_by_its_key_without_a_login(client: TestClient) -> None:
    body = client.get(f"{V1}/info").json()

    assert len(body["serverId"]) == 26 and server_id_for(unb64u(body["publicKey"])) == body["serverId"]
    assert "signature" not in body, "no challenge, no signature"


def test_info_signs_the_challenge_it_is_given(client: TestClient) -> None:
    n = nonce()

    body = client.get(f"{V1}/info", params={"challenge": n}).json()

    assert verify(server_id=body["serverId"], public_key=body["publicKey"], nonce=n, signature=body["signature"])
    assert body["name"] == "My music server" and body["apiVersion"] == "1.0", "everything it said before is still there"


@pytest.mark.parametrize("bad", ["short", "x" * 65, "has space in it ok?", "semi;colon-----", "ünï-code-ünï-code-ünï"])
def test_a_challenge_that_is_not_a_plain_random_string_is_refused_and_signed_by_nobody(client: TestClient, bad: str) -> None:
    response = client.get(f"{V1}/info", params={"challenge": bad})

    assert response.status_code == 400 and response.json()["error"]["code"] == "validation"
    assert "signature" not in response.text


def test_the_server_never_asks_for_a_login_to_prove_itself(client: TestClient) -> None:
    """The point of the whole thing: the probe carries nothing secret."""
    response = client.get(f"{V1}/info", params={"challenge": nonce()})

    assert response.status_code == 200 and "authorization" not in {k.lower() for k in response.request.headers}


def test_server_lists_nothing_for_somebody_who_is_not_signed_in(client: TestClient) -> None:
    assert client.get(f"{V1}/server").status_code == 401


def test_server_says_who_it_is_and_has_no_addresses_until_somebody_gave_it_some(client: TestClient) -> None:
    headers = sign_in(client)

    body = client.get(f"{V1}/server", headers=headers).json()

    assert body["serverId"] == client.get(f"{V1}/info").json()["serverId"]
    assert body["name"] == "My music server" and body["addresses"] == []


def test_server_hands_out_the_home_and_the_away_address_it_was_told(tmp_path: Path, verifier: FakeVerifier) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        music_dir=tmp_path / "music",
        youtube=False,
        navidrome_url="http://navidrome.invalid",
        home_url="http://192.168.1.20:4533",
        away_url="https://encore-home.tail1234.ts.net",
    )
    with TestClient(create_app(settings, verifier=verifier)) as client:
        body = client.get(f"{V1}/server", params=creds("marwa")).json()

    assert body["addresses"] == [
        {"kind": "home", "url": "http://192.168.1.20:4533"},
        {"kind": "away", "url": "https://encore-home.tail1234.ts.net"},
    ]


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("http://192.168.1.20:4533", "http://192.168.1.20:4533"),
        (" https://encore-home.tail1234.ts.net/ ", "https://encore-home.tail1234.ts.net"),
        ("", ""),
        ("encore-home.local", ""),
        ("http://host/path", ""),
        ("javascript:alert(1)", ""),
        ("http://a b", ""),
        ("ftp://host", ""),
    ],
)
def test_an_address_is_kept_only_when_it_is_a_plain_http_or_https_address(given: str, kept: str) -> None:
    assert clean_url(given) == kept
    assert Settings.from_env({"ENCORE_HOME_URL": given}).home_url == kept
    assert Settings.from_env({"ENCORE_AWAY_URL": given}).away_url == kept


def _database(root: Path) -> Database:
    database = Database(root / "data" / "encore.db")
    database.migrate()
    return database


def test_the_key_made_from_a_known_seed_gives_the_id_and_signature_the_phone_expects() -> None:
    """The same vector is in the app's `server_identity_test.dart`: the two implementations must agree byte for byte, or no phone can verify any server."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    who = ServerIdentity(Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33))))
    answer = who.answer("test-nonce-0123456789abcdef")

    assert who.server_id == "mw3am46w5weex4a4fqrc3avnua"
    assert answer["publicKey"] == "ebVWLo_mVPlAeLES6KmLp5AfhTrmlb7X4OORC60ElmQ"
    assert answer["signature"] == "6w18cE-CIfP1IoMZF4IM_PtyrTWiF9TD-BXhzgxLWYGLxIGZe28K5hF20GX-NEz-R3yM7__1YXvjdd-gzCU7Aw"
