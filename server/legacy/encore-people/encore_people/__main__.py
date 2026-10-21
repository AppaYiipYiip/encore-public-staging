"""`python -m encore_people`: the invite and friend-activity service."""
from __future__ import annotations

import logging
import sys

from .activity import Activity
from .config import Config
from .invites import Invites
from .navidrome import Navidrome
from .parts import Parts
from .people import Roles
from .provision import NavidromeProvisioner
from .server import Api, Settings, serve
from .standing import Standing


def build(config: Config) -> Api:
    if not (config.admin_user and config.admin_password):
        raise SystemExit("NAVIDROME_ADMIN_USER and NAVIDROME_ADMIN_PASSWORD are needed: the service creates accounts for invited people.")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    provisioner = NavidromeProvisioner(config.navidrome_url, config.admin_user, config.admin_password, config.music_dir,
                                       music_root=config.music_root)
    return Api(
        invites=Invites(config.data_dir / "people.db", provisioner=provisioner),
        activity=Activity(config.data_dir / "sharing.json"),
        navidrome=Navidrome(config.navidrome_url),
        settings=Settings(public_url=config.public_url, server_name=config.server_name, owners=config.owners),
        roles=Roles(config.data_dir / "roles.db"),
        standing=Standing(config.data_dir / "standing.db"),
        directory=provisioner,
        parts=Parts(music_url=config.navidrome_url, fetch_url=config.fetch_url or None, hub_url=config.hub_url or None,
                    quality_url=config.quality_url or None, recs_url=config.recs_url or None),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    api = build(config)
    server = serve(api, config.host, config.port)
    logging.getLogger("encore_people").info("people service on %s:%s (public address: %s)", config.host, config.port,
                                            config.public_url or "not set yet")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
