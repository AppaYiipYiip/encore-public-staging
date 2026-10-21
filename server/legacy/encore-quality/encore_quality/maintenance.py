"""Keeping the quality tier in shape, and saying in plain words whether it is (docs/46 sections 8 and 10, docs/49 P4).

Every few minutes: the folders exist, Lidarr and Soularr are wired the way the tier needs, slskd is connected to the Soulseek network
exactly when the owner has said it may be (it starts disconnected, and "off" means off), and quick copies kept for the way back are
cleared after 14 days. The self-test is the same set of questions asked out loud, for the owner's page.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path, PurePosixPath
from typing import Callable

from . import delivery
from .config import Config
from .lidarr import Lidarr, LidarrError
from .navidrome import Navidrome
from .slskd import Slskd
from .store import Store
from .wiring import Wiring, ensure_lidarr, render_soularr, write_if_changed

log = logging.getLogger("encore_quality.maintenance")

SOULSEEK = "soulseek"  # the setting: "on" or "off"


class Maintenance:
    def __init__(self, *, config: Config, lidarr: Lidarr, slskd: Slskd, navidrome: Navidrome, store: Store,
                 clock: Callable[[], float] = time.time) -> None:
        self._config = config
        self._lidarr = lidarr
        self._slskd = slskd
        self._nd = navidrome
        self._store = store
        self._clock = clock
        self._wiring: Wiring | None = None
        self.last_error = ""

    # ------------------------------------------------------------------ what it is

    @property
    def wiring(self) -> Wiring | None:
        return self._wiring

    @property
    def pool_in_lidarr(self) -> str:
        return str(PurePosixPath(self._config.music_dir.as_posix()) / delivery.POOL_DIR)

    @property
    def downloads(self) -> Path:
        return self._config.music_dir / delivery.DOWNLOADS_DIR

    def soulseek_on(self) -> bool:
        return self._store.setting(SOULSEEK, "off") == "on"

    def set_soulseek(self, on: bool) -> None:
        self._store.set_setting(SOULSEEK, "on" if on else "off")
        self._sync_soulseek()

    # ------------------------------------------------------------------ the periodic work

    def run(self) -> None:
        folders = lidarr = ""
        for folder in (delivery.POOL_DIR, delivery.INCOMPLETE_DIR, delivery.REPLACED_DIR):
            try:
                (self._config.music_dir / folder).mkdir(parents=True, exist_ok=True)
            except OSError as error:
                folders = f"The music folder is not writable ({error.strerror})."
                log.warning("cannot make %s: %s", folder, error)
        try:
            self._wiring = ensure_lidarr(self._lidarr, self.pool_in_lidarr)
        except LidarrError as error:
            self._wiring = None
            lidarr = "Lidarr is not answering or refused its settings."
            log.warning("Lidarr is not ready: %s", error)
        self.last_error = folders or lidarr
        self._write_soularr()
        self._sync_soulseek()
        purged = delivery.purge_replaced(self._config.music_dir, self._clock())
        if purged:
            log.info("cleared %d old quick copies", purged)

    def _write_soularr(self) -> None:
        c = self._config
        if not (c.lidarr_api_key and c.slskd_api_key):
            return
        text = render_soularr(lidarr_key=c.lidarr_api_key, lidarr_url=c.lidarr_url, slskd_key=c.slskd_api_key, slskd_url=c.slskd_url,
                              downloads=str(PurePosixPath(c.music_dir.as_posix()) / delivery.DOWNLOADS_DIR))
        try:
            if write_if_changed(c.soularr_config, text):
                log.info("Soularr's settings were written")
        except OSError as error:
            log.warning("could not write Soularr's settings: %s", error)

    def _sync_soulseek(self) -> None:
        state = self._slskd.state()
        if state is None:
            return
        if self.soulseek_on() and not state["loggedIn"]:
            self._slskd.connect()
        elif not self.soulseek_on() and state["connected"]:
            self._slskd.disconnect()

    # ------------------------------------------------------------------ for the owner's page

    def health(self) -> dict:
        """What the owner's page shows without running the self-test: is each part up, and is Soulseek on."""
        lidarr = self._lidarr.version()
        slskd = self._slskd.state()
        return {
            "lidarr": {"up": lidarr is not None, "version": lidarr or ""},
            "slskd": {"up": slskd is not None, "version": (slskd or {}).get("version", ""),
                      "connected": bool(slskd and slskd["loggedIn"])},
            "soulseek": "on" if self.soulseek_on() else "off",
            "wired": self._wiring is not None,
            "problem": self.last_error,
        }

    def selftest(self, *, search: bool = True) -> list[dict]:
        """Plain questions with plain answers: `{"key", "name", "state": ok|problem|off, "note"}`. A real download from the network
        cannot be tried without asking strangers for music, so it is not: what is tried is everything up to that point."""
        checks: list[dict] = []

        def add(key: str, name: str, state: str, note: str = "") -> None:
            checks.append({"key": key, "name": name, "state": state, "note": note})

        version = self._lidarr.version()
        add("lidarr", "Lidarr (finds and files the albums)", "ok" if version else "problem",
            f"Version {version}." if version else "It does not answer.")
        add("wiring", "Lidarr is set up for Encore", "ok" if self._wiring else "problem",
            "Its folder and its quality settings are in place." if self._wiring else (self.last_error or "Not yet."))
        state = self._slskd.state()
        add("slskd", "Soulseek client", "ok" if state else "problem", f"Version {state['version']}." if state else "It does not answer.")
        if state is not None:
            if not self.soulseek_on():
                add("soulseek", "Soulseek network", "off", "Switched off. Nothing is sent or shared until the owner switches it on.")
            elif state["loggedIn"]:
                add("soulseek", "Soulseek network", "ok", "Connected.")
            else:
                add("soulseek", "Soulseek network", "problem", "Not connected yet. This is tried again every few minutes.")
        add("soularr", "Soularr (asks the network for what Lidarr wants)", *self._soularr_check())
        admin = self._nd.admin_ok()
        add("admin", "Encore can see where songs are kept", "ok" if admin else "problem",
            "" if admin else "The music server did not accept the administrator login the service was given.")
        add("folders", "Folders for the better copies", *self._links_check())
        free = delivery.free_bytes(self._config.music_dir) / 1024 ** 3
        add("space", "Free space", "ok" if free >= self._config.min_free_gb else "problem",
            f"{free:.0f} GB free." + ("" if free >= self._config.min_free_gb else " New albums wait until there is more room."))
        if search and state is not None and self.soulseek_on() and state["loggedIn"]:
            answered = self._slskd.search_answers("encore connection test")
            add("network", "The network answers", "ok" if answered else "problem",
                f"{answered} people answered a harmless search." if answered else
                "Nobody answered. The network may be slow, or this connection may be blocked.")
        return checks

    def _soularr_check(self) -> tuple[str, str]:
        path = self._config.soularr_config
        if not path.is_file():
            return "problem", "Its settings file is not there yet."
        log_file = path.parent / "soularr.log"
        if not log_file.is_file():
            return "ok", "Its settings are in place. It has not run yet (it runs every five minutes)."
        age = self._clock() - log_file.stat().st_mtime
        if age > 1800:
            return "problem", "It has not run for over half an hour."
        return "ok", "It ran a few minutes ago."

    def _links_check(self) -> tuple[str, str]:
        """The one thing the whole design rests on: a file in the downloads folder can get a second name in the library folder."""
        mark = f".selftest-{secrets.token_hex(4)}"
        first, second = self.downloads / mark, self._config.music_dir / delivery.POOL_DIR / mark
        try:
            first.parent.mkdir(parents=True, exist_ok=True)
            second.parent.mkdir(parents=True, exist_ok=True)
            first.write_bytes(b"x")
            os.link(first, second)
            same = os.path.samefile(first, second)
        except OSError as error:
            return "problem", f"A file could not get a second name ({error.strerror}). The folders must be on the same drive."
        finally:
            for path in (first, second):
                try:
                    path.unlink()
                except OSError:
                    pass
        return ("ok", "Files can be shared between the downloads and the library without a second copy.") if same else \
            ("problem", "The folders are on different drives, so every better copy would use disk twice.")
