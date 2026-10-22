from __future__ import annotations

from fastapi.testclient import TestClient

from encore_server.ids import new_id
from tests.conftest import FakeVerifier, creds, resolve, song

V1 = "/encore/api/v1"


def sign_in(client: TestClient, user: str = "marwa", device: str = "Pixel") -> dict[str, str]:
    """A device token, the way the app gets one: with the music server's login, once."""
    response = client.post(f"{V1}/auth/login", json={"username": user, "password": f"pw-{user}", "deviceName": device})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['deviceToken']}"}


class TestInfoAndErrors:
    def test_the_server_says_what_it_is_without_a_login(self, client: TestClient) -> None:
        body = client.get(f"{V1}/info").json()
        assert body["apiVersion"] == "1.0" and body["name"] == "My music server"
        assert {"library", "playback", "live"} <= set(body["features"])
        assert abs(body["serverTime"] - __import__("time").time() * 1000) < 5000

    def test_every_error_has_the_one_shape(self, client: TestClient) -> None:
        response = client.get(f"{V1}/library/changes")
        assert response.status_code == 401
        error = response.json()["error"]
        assert set(error) == {"code", "message", "retryable", "retryAfterMs", "details"}
        assert error["code"] == "unauthorized" and error["retryable"] is False

    def test_a_body_that_is_not_json_is_a_validation_error_not_a_crash(self, client: TestClient) -> None:
        response = client.post(
            f"{V1}/refs/resolve", params=creds("marwa"), content=b"{not json", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400 and response.json()["error"]["code"] == "validation"

    def test_an_unknown_route_does_not_leak_anything(self, client: TestClient) -> None:
        assert client.get(f"{V1}/nothing-here").status_code == 404


class TestSigningIn:
    def test_the_music_servers_login_works_as_it_does_today(self, client: TestClient) -> None:
        assert client.get(f"{V1}/me", params=creds("marwa")).json()["role"] == "owner"
        assert client.get(f"{V1}/me", params=creds("nina")).json()["role"] == "member"

    def test_a_wrong_password_is_refused(self, client: TestClient) -> None:
        response = client.get(f"{V1}/me", params=creds("marwa", "wrong"))
        assert response.status_code == 401 and response.json()["error"]["code"] == "unauthorized"

    def test_signing_in_gives_a_device_token_and_never_stores_the_password(self, client: TestClient, tmp_path) -> None:  # type: ignore[no-untyped-def]
        response = client.post(f"{V1}/auth/login", json={"username": "marwa", "password": "pw-marwa", "deviceName": "Pixel 8"})
        body = response.json()
        assert response.status_code == 200 and body["deviceToken"].startswith("ed_")
        assert body["person"]["role"] == "owner"
        stored = (tmp_path / "data" / "encore.db").read_bytes()
        assert b"pw-marwa" not in stored and body["deviceToken"].encode() not in stored, "only a hash of the token is kept"

    def test_a_wrong_password_at_sign_in_is_a_plain_sentence(self, client: TestClient) -> None:
        response = client.post(f"{V1}/auth/login", json={"username": "marwa", "password": "nope"})
        assert response.status_code == 401
        assert "password was not accepted" in response.json()["error"]["message"]

    def test_the_device_token_works_without_asking_the_music_server_again(
        self, client: TestClient, verifier: FakeVerifier
    ) -> None:
        headers = sign_in(client)
        checks = verifier.checks
        assert client.get(f"{V1}/me", headers=headers).json()["username"] == "marwa"
        assert verifier.checks == checks

    def test_the_music_servers_answer_is_remembered_for_ten_minutes(self) -> None:
        from encore_server.auth import NavidromeVerifier, subsonic_token

        calls: list[str] = []

        class Http:
            def get(self, url, params):  # type: ignore[no-untyped-def]
                calls.append(url)

                class Response:
                    def json(self_inner):  # type: ignore[no-untyped-def]
                        return {"subsonic-response": {"status": "ok"}}

                return Response()

        now = [0.0]
        verifier = NavidromeVerifier("http://nd", client=Http(), ttl=600, clock=lambda: now[0])  # type: ignore[arg-type]
        token = subsonic_token("pw", "salt1234")
        assert verifier.verify("marwa", token, "salt1234") and verifier.verify("marwa", token, "salt1234")
        assert len(calls) == 1
        now[0] = 601
        verifier.verify("marwa", token, "salt1234")
        assert len(calls) == 2

    def test_signing_out_ends_that_device_only(self, client: TestClient) -> None:
        phone, tablet = sign_in(client, device="Phone"), sign_in(client, device="Tablet")
        assert client.post(f"{V1}/auth/logout", headers=phone).status_code == 200
        assert client.get(f"{V1}/me", headers=phone).status_code == 401
        assert client.get(f"{V1}/me", headers=tablet).status_code == 200

    def test_a_person_sees_their_devices_and_can_revoke_one(self, client: TestClient) -> None:
        phone, tablet = sign_in(client, device="Phone"), sign_in(client, device="Tablet")
        items = client.get(f"{V1}/me/devices", headers=phone).json()["items"]
        assert {d["name"] for d in items} == {"Phone", "Tablet"}
        assert [d["name"] for d in items if d["thisDevice"]] == ["Phone"]
        tablet_id = next(d["id"] for d in items if d["name"] == "Tablet")
        assert client.delete(f"{V1}/me/devices/{tablet_id}", headers=phone).status_code == 200
        assert client.get(f"{V1}/me", headers=tablet).status_code == 401

    def test_nobody_revokes_somebody_elses_device(self, client: TestClient) -> None:
        mine, hers = sign_in(client, "marwa"), sign_in(client, "nina", "Her phone")
        her_id = client.get(f"{V1}/me/devices", headers=hers).json()["items"][0]["id"]
        client.delete(f"{V1}/me/devices/{her_id}", headers=mine)
        assert client.get(f"{V1}/me", headers=hers).status_code == 200


class TestSongRefs:
    def test_two_people_describing_the_same_song_get_the_same_ref(self, client: TestClient) -> None:
        a = resolve(client, "marwa", song())[0]
        b = resolve(client, "nina", song(title="weird fishes / arpeggi", durationMs=319000))[0]
        assert a["id"] == b["id"]

    def test_a_ref_can_be_read_back(self, client: TestClient) -> None:
        ref = resolve(client, "marwa", song(videoId="bgsmr7t8zGE"))[0]
        body = client.get(f"{V1}/refs/{ref['id']}", params=creds("nina")).json()
        assert body["title"] == "Weird Fishes / Arpeggi" and body["videoId"] == "bgsmr7t8zGE"

    def test_an_unknown_ref_is_not_found_in_words(self, client: TestClient) -> None:
        response = client.get(f"{V1}/refs/sr_00000000000000000000000000", params=creds("marwa"))
        assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"

    def test_a_list_of_songs_that_is_empty_or_huge_is_refused(self, client: TestClient) -> None:
        assert client.post(f"{V1}/refs/resolve", params=creds("marwa"), json={"songs": []}).status_code == 400
        assert client.post(f"{V1}/refs/resolve", params=creds("marwa"), json={"songs": [song()] * 501}).status_code == 400


class TestTheLibrary:
    def test_a_like_shows_up_in_the_changes_and_not_for_somebody_else(self, client: TestClient) -> None:
        ref = resolve(client, "marwa", song())[0]["id"]
        assert client.put(f"{V1}/likes/{ref}", params=creds("marwa")).json()["changed"] is True

        mine = client.get(f"{V1}/library/changes", params={**creds("marwa"), "since": "0"}).json()
        hers = client.get(f"{V1}/library/changes", params={**creds("nina"), "since": "0"}).json()
        assert [like["ref"] for like in mine["likes"]] == [ref] and [r["id"] for r in mine["refs"]] == [ref]
        assert hers["likes"] == []

    def test_liking_twice_and_unliking_what_was_not_liked_are_harmless(self, client: TestClient) -> None:
        ref = resolve(client, "marwa", song())[0]["id"]
        assert client.put(f"{V1}/likes/{ref}", params=creds("marwa")).json()["changed"] is True
        assert client.put(f"{V1}/likes/{ref}", params=creds("marwa")).json()["changed"] is False
        assert client.delete(f"{V1}/likes/{ref}", params=creds("marwa")).json()["changed"] is True
        assert client.delete(f"{V1}/likes/{ref}", params=creds("marwa")).json()["changed"] is False

    def test_a_cursor_is_the_way_to_ask_for_only_what_is_new(self, client: TestClient) -> None:
        a, b = (r["id"] for r in resolve(client, "marwa", song(), song("Reckoner")))
        client.put(f"{V1}/likes/{a}", params=creds("marwa"))
        first = client.get(f"{V1}/library/changes", params={**creds("marwa"), "since": "0"}).json()
        client.put(f"{V1}/likes/{b}", params=creds("marwa"))
        second = client.get(f"{V1}/library/changes", params={**creds("marwa"), "since": first["cursor"]}).json()
        assert [like["ref"] for like in second["likes"]] == [b]

    def test_a_cursor_that_is_not_a_number_is_a_validation_error(self, client: TestClient) -> None:
        assert client.get(f"{V1}/library/changes", params={**creds("marwa"), "since": "abc"}).status_code == 400

    def test_a_playlist_from_start_to_finish(self, client: TestClient) -> None:
        who = creds("marwa")
        refs = [r["id"] for r in resolve(client, "marwa", song(), song("Reckoner"), song("Nude"))]
        pl = new_id("pl")
        assert client.post(f"{V1}/playlists", params=who, json={"id": pl, "name": "Radiohead"}).status_code == 201
        added = client.post(f"{V1}/playlists/{pl}/entries", params=who, json={"songs": [{"ref": r} for r in refs]}).json()[
            "added"
        ]
        assert len(added) == 3

        body = client.get(f"{V1}/playlists/{pl}", params=who).json()
        assert [e["ref"] for e in body["entries"]] == refs

        client.put(f"{V1}/playlists/{pl}/order", params=who, json={"entryIds": list(reversed(added))})
        client.patch(f"{V1}/playlists/{pl}", params=who, json={"name": "In Rainbows"})
        client.request("DELETE", f"{V1}/playlists/{pl}/entries", params=who, json={"entryIds": [added[0]]})

        body = client.get(f"{V1}/playlists/{pl}", params=who).json()
        assert body["name"] == "In Rainbows"
        assert [e["ref"] for e in body["entries"]] == [refs[2], refs[1]]

        assert client.delete(f"{V1}/playlists/{pl}", params=who).json()["changed"] is True
        assert client.get(f"{V1}/playlists/{pl}", params=who).status_code == 404
        assert client.get(f"{V1}/playlists", params=who).json()["items"] == []

    def test_a_playlist_create_that_is_retried_after_a_lost_answer_is_one_playlist(self, client: TestClient) -> None:
        who, pl = creds("marwa"), new_id("pl")
        client.post(f"{V1}/playlists", params=who, json={"id": pl, "name": "Road trip"})
        client.post(f"{V1}/playlists", params=who, json={"id": pl, "name": "Road trip"})
        assert len(client.get(f"{V1}/playlists", params=who).json()["items"]) == 1

    def test_somebody_elses_playlist_is_not_found(self, client: TestClient) -> None:
        pl = new_id("pl")
        client.post(f"{V1}/playlists", params=creds("marwa"), json={"id": pl, "name": "Mine"})
        assert client.get(f"{V1}/playlists/{pl}", params=creds("nina")).status_code == 404

    def test_a_play_that_is_reported_twice_is_one_play(self, client: TestClient) -> None:
        ref = resolve(client, "marwa", song())[0]["id"]
        play = {"id": "01JA0000000000000000000001", "ref": ref, "at": 1_700_000_000_000, "msPlayed": 200000}
        assert client.post(f"{V1}/plays", params=creds("marwa"), json=play).json()["stored"] is True
        assert client.post(f"{V1}/plays", params=creds("marwa"), json=play).json()["stored"] is False

    def test_every_response_carries_the_servers_clock(self, client: TestClient) -> None:
        assert "serverTime" in client.get(f"{V1}/library/changes", params=creds("marwa")).json()


class TestPlayback:
    def refs(self, client: TestClient, n: int) -> list[str]:
        return [r["id"] for r in resolve(client, "marwa", *[song(f"Song {i}", durationMs=100000 + i * 20000) for i in range(n)])]

    def test_a_new_person_has_an_empty_state(self, client: TestClient) -> None:
        state = client.get(f"{V1}/playback", params=creds("marwa")).json()["state"]
        assert state["ref"] is None and state["rev"] == 0 and state["queue"] == []

    def test_what_is_playing_is_kept_and_the_rev_moves_on(self, client: TestClient) -> None:
        headers, queue = sign_in(client), self.refs(client, 3)
        body = {
            "rev": 0,
            "ref": queue[1],
            "positionMs": 151000,
            "queue": queue,
            "index": 1,
            "playing": True,
            "context": "playlist:x",
        }
        first = client.put(f"{V1}/playback", headers=headers, json=body).json()["state"]
        assert (first["rev"], first["ref"], first["positionMs"], first["queue"]) == (1, queue[1], 151000, queue)
        assert client.get(f"{V1}/playback", headers=headers).json()["state"]["positionMs"] == 151000

    def test_a_write_based_on_an_old_rev_is_a_conflict_with_the_current_state(self, client: TestClient) -> None:
        headers, queue = sign_in(client), self.refs(client, 2)
        client.put(f"{V1}/playback", headers=headers, json={"rev": 0, "ref": queue[0], "positionMs": 1000, "playing": False})
        stale = client.put(f"{V1}/playback", headers=headers, json={"rev": 0, "ref": queue[1], "positionMs": 5, "playing": False})
        assert stale.status_code == 409
        error = stale.json()["error"]
        assert error["code"] == "conflict" and error["details"]["state"]["ref"] == queue[0]

    def test_the_state_needs_to_say_which_revision_it_is_based_on(self, client: TestClient) -> None:
        assert client.put(f"{V1}/playback", params=creds("marwa"), json={"ref": None}).status_code == 400

    def test_a_queue_of_things_that_are_not_songs_is_refused(self, client: TestClient) -> None:
        response = client.put(f"{V1}/playback", params=creds("marwa"), json={"rev": 0, "queue": ["not-a-ref"]})
        assert response.status_code == 400

    def test_starting_to_play_on_another_device_takes_over(self, client: TestClient) -> None:
        phone, tablet = sign_in(client, device="Phone"), sign_in(client, device="Tablet")
        queue = self.refs(client, 1)
        a = client.put(f"{V1}/playback", headers=phone, json={"rev": 0, "ref": queue[0], "playing": True}).json()["state"]
        devices = {d["name"]: d["id"] for d in client.get(f"{V1}/me/devices", headers=phone).json()["items"]}
        assert a["activeDevice"] == devices["Phone"]

        b = client.put(f"{V1}/playback", headers=tablet, json={"rev": a["rev"], "ref": queue[0], "playing": True}).json()["state"]
        assert b["activeDevice"] == devices["Tablet"]

    def test_pausing_on_another_device_does_not_take_over(self, client: TestClient) -> None:
        phone, tablet = sign_in(client, device="Phone"), sign_in(client, device="Tablet")
        queue = self.refs(client, 1)
        a = client.put(f"{V1}/playback", headers=phone, json={"rev": 0, "ref": queue[0], "playing": True}).json()["state"]
        b = client.put(
            f"{V1}/playback", headers=tablet, json={"rev": a["rev"], "ref": queue[0], "playing": False, "positionMs": 10}
        ).json()["state"]
        assert b["activeDevice"] == a["activeDevice"]

    def test_claiming_playback_makes_this_device_the_one(self, client: TestClient) -> None:
        phone, tablet = sign_in(client, device="Phone"), sign_in(client, device="Tablet")
        devices = {d["name"]: d["id"] for d in client.get(f"{V1}/me/devices", headers=phone).json()["items"]}
        assert client.post(f"{V1}/playback/claim", headers=phone).json()["state"]["activeDevice"] == devices["Phone"]
        assert client.post(f"{V1}/playback/claim", headers=tablet).json()["state"]["activeDevice"] == devices["Tablet"]

    def test_claiming_needs_a_device_token(self, client: TestClient) -> None:
        assert client.post(f"{V1}/playback/claim", params=creds("marwa")).status_code == 400

    def test_each_person_has_their_own_state(self, client: TestClient) -> None:
        queue = self.refs(client, 1)
        client.put(f"{V1}/playback", params=creds("marwa"), json={"rev": 0, "ref": queue[0], "positionMs": 99})
        assert client.get(f"{V1}/playback", params=creds("nina")).json()["state"]["ref"] is None


class TestTheLiveChannel:
    def connect(self, client: TestClient, headers: dict[str, str]):  # type: ignore[no-untyped-def]
        token = headers["Authorization"].split()[1]
        ws = client.websocket_connect("/encore/live")
        socket = ws.__enter__()
        socket.send_json({"type": "auth", "token": token})
        hello = socket.receive_json()
        assert hello["type"] == "hello"
        return ws, socket

    def test_a_device_hears_about_a_change_made_on_another_device(self, client: TestClient) -> None:
        phone, tablet = sign_in(client, device="Phone"), sign_in(client, device="Tablet")
        ref = resolve(client, "marwa", song())[0]["id"]
        ws, socket = self.connect(client, tablet)
        try:
            client.put(f"{V1}/likes/{ref}", headers=phone)
            event = socket.receive_json()
        finally:
            ws.__exit__(None, None, None)
        assert event["type"] == "library.changed" and int(event["cursor"]) >= 1

    def test_the_device_that_made_the_change_is_not_told(self, client: TestClient) -> None:
        phone = sign_in(client, device="Phone")
        ref = resolve(client, "marwa", song())[0]["id"]
        ws, socket = self.connect(client, phone)
        try:
            client.put(f"{V1}/likes/{ref}", headers=phone)
            client.put(f"{V1}/likes/{resolve(client, 'marwa', song('Other'))[0]['id']}", headers=sign_in(client, device="Third"))
            event = socket.receive_json()
        finally:
            ws.__exit__(None, None, None)
        # the first event this device sees is about the third device's like, not its own
        assert event["type"] == "library.changed" and int(event["cursor"]) == 2

    def test_nobody_hears_about_somebody_elses_library(self, client: TestClient) -> None:
        hers = sign_in(client, "nina", "Her phone")
        ref = resolve(client, "marwa", song())[0]["id"]
        ws, socket = self.connect(client, hers)
        try:
            client.put(f"{V1}/likes/{ref}", params=creds("marwa"))
            client.put(f"{V1}/playback", params=creds("nina"), json={"rev": 0, "ref": ref, "playing": False})
            event = socket.receive_json()
        finally:
            ws.__exit__(None, None, None)
        assert event["type"] == "playback.changed", "her own device was told of her playback, never of his likes"

    def test_the_device_that_is_taken_over_from_is_told(self, client: TestClient) -> None:
        phone, tablet = sign_in(client, device="Phone"), sign_in(client, device="Tablet")
        ref = resolve(client, "marwa", song())[0]["id"]
        first = client.put(f"{V1}/playback", headers=phone, json={"rev": 0, "ref": ref, "playing": True}).json()["state"]
        ws, socket = self.connect(client, phone)
        try:
            client.put(f"{V1}/playback", headers=tablet, json={"rev": first["rev"], "ref": ref, "playing": True})
            seen = {socket.receive_json()["type"], socket.receive_json()["type"]}
        finally:
            ws.__exit__(None, None, None)
        assert seen == {"playback.changed", "device.takeover"}

    def test_a_socket_that_does_not_sign_in_is_closed(self, client: TestClient) -> None:
        import pytest
        from starlette.websockets import WebSocketDisconnect

        with client.websocket_connect("/encore/live") as socket:
            socket.send_json({"type": "auth", "token": "ed_nonsense"})
            with pytest.raises(WebSocketDisconnect) as caught:
                socket.receive_json()
        assert caught.value.code == 4401
