"""Who may do what to whose device, as a model checked against the real API on random sequences of events (docs/11 ADR-R41 T3, docs/32 rows DV-2, DV-3, DV-4, AC-22, AC-23).

The model is a few lines of plain Python: a device works while it has not been ended and its person is not locked, ending a device (signing
out, revoking it) only ever ends one of the **caller's own**, and **locking a person ends every device they have for good** (unlocking does not
bring them back: they sign in again). Hypothesis draws long random sequences of sign-ins, sign-outs (with the device token
and with the music server's login plus the device header, the way the app does), revocations, locks and unlocks, and after every step compares the
model with what the server says for every device and every person. The logout that ended somebody else's device (found on 2026-10-24, D-5) is
exactly the kind of thing a sequence like "nina signs in; marwa signs out naming nina's device" finds without anybody thinking of it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from encore_server.api import create_app
from encore_server.config import Settings
from tests.conftest import FakeVerifier, creds

V1 = "/encore/api/v1"
PEOPLE = ("marwa", "nina", "mia")
MEMBERS = ("nina", "mia")  # marwa is the only owner: she is never locked (a server needs one) and does the locking


class Device:
    def __init__(self, person: str, bearer: dict[str, str], device_id: str) -> None:
        self.person = person
        self.bearer = bearer
        self.id = device_id
        self.active = True


class Accounts(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        app = create_app(
            Settings(data_dir=root / "data", music_dir=root / "music", navidrome_url="http://navidrome.invalid", youtube=False),
            verifier=FakeVerifier(),
        )
        self.client = TestClient(app)
        self.client.__enter__()
        self.devices: list[Device] = []
        self.locked: set[str] = set()
        self.signins = dict.fromkeys(PEOPLE, 0)
        self.person_ids: dict[str, str] = {}

    def teardown(self) -> None:
        self.client.__exit__(None, None, None)
        self.folder.cleanup()

    # ---------------------------------------------------------------- what the model knows

    def _ids(self) -> dict[str, str]:
        """The server's id of each person (read once every person has signed in at least once)."""
        if len(self.person_ids) < len(PEOPLE):
            items = self.client.get(f"{V1}/people", params=creds("marwa")).json()["items"]
            self.person_ids = {item["username"]: item["id"] for item in items}
        return self.person_ids

    def _works(self, device: Device) -> bool:
        return device.active and device.person not in self.locked

    # ---------------------------------------------------------------- the events

    @rule(person=st.sampled_from(PEOPLE))
    def sign_in(self, person: str) -> None:
        if self.signins[person] >= 4:
            return  # five a minute for one name is the server's own limit (a different row)
        self.signins[person] += 1
        response = self.client.post(
            f"{V1}/auth/login", json={"username": person, "password": f"pw-{person}", "deviceName": f"{person}'s phone"}
        )
        if person in self.locked:
            assert response.status_code == 403, "a locked person cannot sign in"
            return
        assert response.status_code == 200, response.text
        bearer = {"Authorization": f"Bearer {response.json()['deviceToken']}"}
        self.devices.append(Device(person, bearer, response.json()["device"]["id"]))

    @precondition(lambda self: bool(self.devices))
    @rule(data=st.data())
    def sign_out_with_the_device_token(self, data: st.DataObject) -> None:
        device = data.draw(st.sampled_from(self.devices))
        response = self.client.post(f"{V1}/auth/logout", headers=device.bearer)
        if self._works(device):
            assert response.status_code == 200
            device.active = False
        else:
            assert response.status_code == 401

    @precondition(lambda self: bool(self.devices))
    @rule(data=st.data(), caller=st.sampled_from(PEOPLE))
    def sign_out_with_the_music_servers_login_and_a_device_header(self, data: st.DataObject, caller: str) -> None:
        if caller in self.locked:
            return
        device = data.draw(st.sampled_from(self.devices))
        response = self.client.post(f"{V1}/auth/logout", params=creds(caller), headers={"X-Encore-Device": device.id})
        assert response.status_code == 200
        if device.person == caller:
            device.active = False  # her own: ended
        # somebody else's: nothing happens to it (the model does not change)

    @precondition(lambda self: bool(self.devices))
    @rule(data=st.data(), caller=st.sampled_from(PEOPLE))
    def revoke_a_device(self, data: st.DataObject, caller: str) -> None:
        if caller in self.locked:
            return
        device = data.draw(st.sampled_from(self.devices))
        assert self.client.delete(f"{V1}/me/devices/{device.id}", params=creds(caller)).status_code == 200
        if device.person == caller:
            device.active = False

    @rule(person=st.sampled_from(MEMBERS))
    def the_owner_locks_somebody(self, person: str) -> None:
        if person in self.locked or self.signins[person] == 0:
            return
        response = self.client.patch(f"{V1}/people/{self._ids()[person]}", params=creds("marwa"), json={"locked": True})
        assert response.status_code == 200, response.text
        self.locked.add(person)
        for device in self.devices:
            if device.person == person:
                device.active = False  # a lock signs every device of theirs out, and an unlock does not sign them in again (B28)

    @rule(person=st.sampled_from(MEMBERS))
    def the_owner_unlocks_somebody(self, person: str) -> None:
        if person not in self.locked:
            return
        response = self.client.patch(f"{V1}/people/{self._ids()[person]}", params=creds("marwa"), json={"locked": False})
        assert response.status_code == 200, response.text
        self.locked.discard(person)

    # ---------------------------------------------------------------- what must always be true

    @invariant()
    def a_device_works_exactly_when_the_model_says(self) -> None:
        for device in self.devices:
            status = self.client.get(f"{V1}/me", headers=device.bearer).status_code
            assert (status == 200) == self._works(device), (
                f"{device.person}'s device {device.id}: the server answered {status}, the model says {self._works(device)}"
            )

    @invariant()
    def a_person_signs_in_with_the_music_servers_login_unless_locked(self) -> None:
        for person in PEOPLE:
            status = self.client.get(f"{V1}/me", params=creds(person)).status_code
            assert status == (403 if person in self.locked else 200), f"{person}: {status}"

    @invariant()
    def the_list_of_devices_is_the_active_ones_and_only_the_persons_own(self) -> None:
        for person in PEOPLE:
            if person in self.locked:
                continue
            listed = {d["id"] for d in self.client.get(f"{V1}/me/devices", params=creds(person)).json()["items"]}
            assert listed == {d.id for d in self.devices if d.person == person and d.active}, person


Accounts.TestCase.settings = settings(
    max_examples=8, stateful_step_count=14, deadline=None, suppress_health_check=list(HealthCheck), database=None
)
TestAccounts = Accounts.TestCase


def test_the_model_knows_that_a_lock_ends_the_persons_devices_for_good() -> None:
    """B28: locking a person signs every device of theirs out (`UPDATE device SET revoked_at`), and unlocking does not bring them back: they
    sign in again. The model said a device works whenever its person is not locked, so the sequence sign in, lock, unlock (which random
    sequences found in about four runs of ten) made it expect a 200 where the server rightly answers 401."""
    machine = Accounts()
    try:
        for person in PEOPLE:
            machine.sign_in(person)
        machine.the_owner_locks_somebody("nina")
        machine.the_owner_unlocks_somebody("nina")

        machine.a_device_works_exactly_when_the_model_says()
        machine.a_person_signs_in_with_the_music_servers_login_unless_locked()
        machine.the_list_of_devices_is_the_active_ones_and_only_the_persons_own()

        machine.sign_in("nina")  # signing in again after the unlock makes a device that works
        machine.a_device_works_exactly_when_the_model_says()
    finally:
        machine.teardown()
