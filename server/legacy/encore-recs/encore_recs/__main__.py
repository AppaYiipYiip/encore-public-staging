"""`python -m encore_recs`: the recommendations service (docs/47)."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .builder import Builder
from .cache import Cache
from .navidrome import Navidrome
from .server import Api, serve
from . import __version__
from .sources import Sources, make_get, user_agent
from .store import Store

log = logging.getLogger("encore_recs")

#: How often the service looks at whether anybody needs a list (the nightly pass is the first look after the early hours begin).
LOOK_EVERY_S = 600
NIGHT_HOURS = (3, 4, 5)  # local time: when the nightly pass runs, once


def _forever(name: str, every: float, work: Callable[[], None]) -> None:
    def loop() -> None:
        while True:
            try:
                work()
            except Exception:  # noqa: BLE001 - housekeeping never stops the service
                log.exception("%s failed", name)
            time.sleep(every)

    threading.Thread(target=loop, daemon=True, name=name).start()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    env = os.environ
    data = Path(env.get("DATA_DIR", "/data"))
    data.mkdir(parents=True, exist_ok=True)
    store = Store(data / "recs.db")
    cache = Cache(data / "cache.db")
    # A private scratch folder for the music server's database copy (read-only container: /tmp is a tmpfs).
    builder = Builder(store=store, sources=Sources(cache, make_get(user_agent(__version__, env.get("CONTACT", "")))), database_dir=Path(env.get("NAVIDROME_DB_DIR", "/navidrome")),
                      scratch=Path(env.get("SCRATCH_DIR", "/tmp")))
    api = Api(store=store, navidrome=Navidrome(env.get("NAVIDROME_URL", "http://navidrome:4533")), builder=builder,
              people_url=env.get("PEOPLE_URL", "http://encore-people:8702"))

    def look() -> None:
        if not builder.enabled():
            return
        today = time.strftime("%Y-%m-%d")
        if time.localtime().tm_hour in NIGHT_HOURS and store.setting("nightly", "") != today:
            store.set_setting("nightly", today)
            builder.run(everyone=True)
            cache.sweep()
        else:
            builder.run(everyone=False)

    _forever("builder", LOOK_EVERY_S, look)
    server = serve(api, env.get("HOST", "0.0.0.0"), int(env.get("PORT", "8705")))  # noqa: S104 - the stack's own network
    log.info("recommendations service on %s", env.get("PORT", "8705"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
