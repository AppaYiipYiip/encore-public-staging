"""`python -m encore_quality`: the quality tier's service (docs/46)."""
from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Callable

from .config import Config
from .engine import Engine
from .lidarr import Lidarr
from .lidarr import http_for as lidarr_http
from .maintenance import Maintenance
from .navidrome import Navidrome
from .server import Api, serve
from .slskd import Slskd
from .slskd import http_for as slskd_http
from .store import Store

log = logging.getLogger("encore_quality")

STEP_EVERY_S = 20
MAINTAIN_EVERY_S = 300


def build(config: Config) -> tuple[Api, Engine, Maintenance]:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(config.data_dir / "quality.db")
    navidrome = Navidrome(config.navidrome_url, admin_user=config.navidrome_admin_user or None,
                          admin_password=config.navidrome_admin_password or None)
    lidarr = Lidarr(lidarr_http(config.lidarr_url, config.lidarr_api_key))
    slskd = Slskd(slskd_http(config.slskd_url, config.slskd_api_key))
    maintenance = Maintenance(config=config, lidarr=lidarr, slskd=slskd, navidrome=navidrome, store=store)
    api = Api(config=config, store=store, navidrome=navidrome, maintenance=maintenance)
    engine = Engine(store=store, lidarr=lidarr, navidrome=navidrome, music=config.music_dir, wiring=lambda: maintenance.wiring, slskd=slskd,
                    limits=api.limits, soulseek_on=maintenance.soulseek_on)
    return api, engine, maintenance


def _forever(name: str, every: "float | Callable[[], float]", work: Callable[[], None]) -> None:
    def loop() -> None:
        while True:
            try:
                work()
            except Exception:  # noqa: BLE001 - housekeeping never stops the service
                log.exception("%s failed", name)
            time.sleep(every() if callable(every) else every)

    threading.Thread(target=loop, daemon=True, name=name).start()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    if not (config.lidarr_api_key and config.slskd_api_key):
        raise SystemExit("LIDARR_API_KEY and SLSKD_API_KEY are needed: the service looks after both programs.")
    api, engine, maintenance = build(config)
    # Until Lidarr has been set up (it takes a minute to start the first time) look again every few seconds, not every five minutes.
    _forever("maintenance", lambda: MAINTAIN_EVERY_S if maintenance.wiring is not None else 15, maintenance.run)
    _forever("engine", STEP_EVERY_S, engine.step)
    server = serve(api, config.host, config.port)
    log.info("quality service on %s:%s", config.host, config.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
