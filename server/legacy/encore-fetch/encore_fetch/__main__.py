"""`python -m encore_fetch` - run the service from environment settings."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import Config
from .download import YtDlpDownloader
from .catalogue import Deezer
from .imports import ImportQueue
from .jobs import Dispatcher, JobManager
from .library import PersonLayout
from .account_test import check_account
from .accounts import Accounts
from .identity import account_identity
from .navidrome import Auth, Navidrome
from .owners import OwnerCheck
from .playlists import read_playlist, ytdlp_reader, ytmusic_reader
from .stream import StreamProxy
from .profile import ProfileStore
from .resolve import YtDlpResolver
from .server import Api, serve


def build(config: Config) -> Api:
    # The YouTube accounts (docs/50): one private file each; the single login file of the first version is adopted.
    accounts = Accounts(config.accounts_dir or config.work_dir / "youtube",
                        legacy_file=Path(config.cookies_file) if config.cookies_file else None,
                        identify=None if config.fake else account_identity, identify_in_background=not config.fake)
    if config.fake:
        from .fake import FakeDownloader, FakeNavidrome, FakeResolver

        nd: Navidrome = FakeNavidrome()
        resolver = FakeResolver()
        downloader = FakeDownloader()
    else:
        admin = None
        if config.admin_user and config.admin_password:
            import hashlib
            import secrets

            salt = secrets.token_hex(6)
            admin = Auth(
                config.admin_user,
                hashlib.md5(  # noqa: S324 - Subsonic's token scheme
                    (config.admin_password + salt).encode()).hexdigest(),
                salt,
            )
        nd = Navidrome(config.navidrome_url, admin=admin)
        legacy = YtDlpResolver(
            config.ytdlp, cookies=accounts,
            max_duration_s=config.max_duration_s)
        extractor = None
        resolver = legacy
        if config.resolver != "legacy":
            from .lean import InProcessExtractor, LeanResolver, YtmusicApiSearcher

            resolver = LeanResolver(YtmusicApiSearcher(), fallback=legacy, max_duration_s=config.max_duration_s)
            extractor = InProcessExtractor(cache_dir=config.work_dir / "ytdlp-cache", fast_clients=config.youtube_fast_clients)
        downloader = YtDlpDownloader(
            config.ytdlp, cookies=accounts,
            max_file_mb=config.max_file_mb, extractor=extractor,
            direct=config.direct_download and extractor is not None)
    config.work_dir.mkdir(parents=True, exist_ok=True)
    manager = JobManager(
        music_dir=config.music_dir,
        work_dir=config.work_dir,
        resolver=resolver,
        downloader=downloader,
        navidrome=nd,
        executor=Dispatcher(workers=config.workers, bulk_slots=max(1, config.workers - 1)),
        min_free_gb=0 if config.fake else config.min_free_gb,
        skip_index=config.fake or config.dev_local,
        watcher_wait_s=config.watcher_wait_s,
        max_duration_s=config.max_duration_s,
        daily_limit=config.user_daily_limit,
        active_limit=config.user_active_limit,
        cache_max_mb=config.cache_mb,
        enricher=Deezer(config.work_dir / "catalogue-cache.json").lookup
        if config.lookup_albums and not config.fake else None,
        people=PersonLayout(config.music_dir, config.person_folders) if config.people else None,
    )
    store = None
    if config.profile:
        store = ProfileStore(config.profile_dir or config.work_dir / "profile")
    flat = ytdlp_reader(config.ytdlp, cookies=accounts)
    listing = ytmusic_reader()
    imports = ImportQueue(manager, nd, config.work_dir / "imports", workers=config.import_workers,
                          gap_s=0.0 if config.fake else config.import_gap_s,
                          max_per_hour=config.import_max_per_hour, max_song_s=config.max_duration_s,
                          account_ceiling=accounts.capacity)
    streams = None if config.fake else StreamProxy(
        candidates=manager.stream_candidates, extract=manager.extract_streams, work_dir=config.work_dir, fault=config.fault)
    return Api(manager, nd, store, streams=streams,
               playlist_reader=lambda url: read_playlist(url, ytdlp=flat, ytmusic=listing), imports=imports,
               owner_check=OwnerCheck(config.people_url if config.people else None, nd),
               accounts=accounts, visitor_per_hour=config.import_max_per_hour,
               account_tester=lambda path: check_account(config.ytdlp, path))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.from_env()
    if config.fake or config.dev_local:
        config.music_dir.mkdir(parents=True, exist_ok=True)
    api = build(config)
    httpd = serve(api, config.host, config.port)
    mode = "FAKE" if config.fake else "live"
    print(f"encore-fetch ({mode}) on {config.host}:{config.port}, "
          f"library {config.music_dir}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
