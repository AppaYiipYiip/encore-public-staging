"""The application: wires the settings, the database, the background workers and the route modules into one FastAPI app (docs/04, docs/17).

The routes themselves are in `routes/`, one module per area (P3-31; docs/17 names the module of each group): `/encore/api/v1/...`, the signed
audio and pictures, the invitation page, and the live channel `/encore/live`. One error shape (errors.py), ids with prefixes, idempotent writes,
state-based `library/changes`. Handlers are plain functions run in worker threads (SQLite and the music server's check block briefly); the live
sockets stay on the event loop.
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import (
    __version__,
    deezer,
    gateway,
    keyrepair,
    refs,
    textnorm,
)
from .accounts import Accounts, Limiter
from .album_pass import AlbumFinder, KeepAsker
from .artist_finder import ArtistFinder, ArtistLookup
from .auth import (
    MusicServerUnavailable,
    NavidromeVerifier,
    Verifier,
    forget_credentials,
    stream_secret,
)
from .bodylimit import BodyLimit
from .catalogue import Cache, Catalogue
from .config import Settings
from .cover_finder import CoverFinder, deezer_lookup
from .db import Database
from .deezer import DeezerClient, Gate
from .errors import ApiError
from .identity import load_or_create
from .imports.service import ImportService
from .imports.watch import ImportWatch
from .keep_watch import KeepWatch
from .keeper.keeper import Keeper, KeepSettings
from .live import Hub
from .navidrome import NavidromeClient
from .navidrome_admin import NavidromeAdmin
from .notifications import Notifications
from .prepare import Preparer
from .quiet import InFlight, InFlightMiddleware
from .ref_janitor import RefJanitor
from .routes import catalogue as catalogue_routes
from .routes import imports as imports_routes
from .routes import info as info_routes
from .routes import keep as keep_routes
from .routes import library as library_routes
from .routes import live as live_routes
from .routes import media as media_routes
from .routes import people as people_routes
from .routes import playback as playback_routes
from .routes import playlists as playlists_routes
from .routes import refs as refs_routes
from .routes import session as session_routes
from .routes.common import (
    API_PREFIX,
    Services,
    _youtube_status,
    authorize_public_subsonic,
    is_public_request,
)
from .scanner import LibraryLinker
from .scheduler import Scheduler
from .sources.youtube.pace import Pacer
from .sources.youtube.rest import DbRestStore, Rest
from .sources.youtube.source import YoutubeSource
from .sources.youtube.tools import Active, ToolStore
from .sources.youtube.updater import Tools, create_tools
from .stopping import LIFESPAN_STOP_S, MIN_JOIN_S
from .tombstone_purge import TombstonePurge
from .verdicts import RefVerdicts

log = logging.getLogger("encore_server.api")


# ------------------------------------------------------------------------------------------------ the application


def _default_youtube(settings: Settings, database: Database) -> YoutubeSource | None:
    """The real YouTube source, when its libraries are installed (a server without them still runs: songs it keeps still play)."""

    def remember(ref_id: str, video_id: str, replacing: str | None = None) -> None:
        with database.tx() as conn:
            refs.remember_video(conn, ref_id, video_id, replacing=replacing)

    if importlib.util.find_spec("yt_dlp") is None or importlib.util.find_spec("ytmusicapi") is None:
        log.warning("yt-dlp or ytmusicapi is not installed: songs that are not kept cannot be streamed")
        return None
    return YoutubeSource(
        settings.data_dir / "work",
        fast_clients=("visionos",),
        fault=settings.fault,
        remember_video=remember,
        rest=Rest(store=DbRestStore(database)),
        pace=Pacer(settings.youtube_pace_s) if settings.youtube_pace_s > 0 else None,
    )


def _default_catalogue(settings: Settings) -> Catalogue:
    """The catalogue as this server runs it: Deezer through the one gate, remembered in a file of its own beside the database. Switched off by the Host
    (`ENCORE_CATALOGUE=0`), the gate opens no connection and no file is made."""
    gate = Gate(enabled=settings.catalogue)
    cache = Cache(settings.data_dir / "catalogue-cache.db") if settings.catalogue else None
    return Catalogue(DeezerClient(gate), cache)


def _default_tools(
    settings: Settings,
    youtube: YoutubeSource | None,
    scheduler: Scheduler | None,
    in_flight: InFlight,
    active: Active | None,
) -> Tools | None:
    """The yt-dlp updater, for a server that really fetches from YouTube, runs its background work and has not switched it off."""
    if not (settings.auto_tools and settings.workers and isinstance(youtube, YoutubeSource)):
        return None
    pacer = youtube.pacer
    return create_tools(
        ToolStore(settings.data_dir / "tools" / "yt-dlp"),
        active,
        rest=youtube.rest,
        lookups=youtube.lookups,
        wait_turn=pacer.wait_turn if pacer is not None else None,
        busy=lambda: in_flight.count > 0 or (scheduler is not None and scheduler.running() > 0),
    )


def _background(
    settings: Settings,
    database: Database,
    hub: Hub,
    youtube: YoutubeSource | None,
    client: NavidromeClient,
    notifications: Notifications,
    catalogue: Catalogue,
) -> tuple[Scheduler | None, Keeper | None, ImportService]:
    """The background work: matching the songs of imports to uploads, and the keeper. Without a way to fetch songs nothing is queued,
    and without a music-server account that can find what was kept the keeper is off: every song still plays by streaming, and the
    server says in its log why it keeps nothing."""
    handlers: dict[str, Any] = {}
    keeper: Keeper | None = None
    if not settings.keep:
        pass
    elif youtube is None or not client.configured:
        log.warning(
            "keeping is off: %s",
            "no way to fetch songs (yt-dlp is not installed or YouTube is off)"
            if youtube is None
            else "ENCORE_NAVIDROME_ADMIN_USER / ENCORE_NAVIDROME_ADMIN_PASSWORD are not set",
        )
    else:

        def tell(touched: dict[str, int]) -> None:
            for person, cursor in touched.items():
                hub.publish(person, {"type": "library.changed", "cursor": str(cursor)})

        keeper = Keeper(
            database,
            youtube,
            client,
            KeepSettings(music_dir=settings.music_dir, min_free_gb=settings.min_free_gb),
            settings.data_dir / "work",
            on_changed=tell,
            find_cover_=deezer_lookup,
            # N-34 slice 3: which album the song being kept is on, asked of the catalogue (the very selection, matcher and write rule of the album pass) before its tags and
            # its folder are made. A catalogue that cannot be asked never delays or stops a keep.
            identify_=KeepAsker.on(database, catalogue) if settings.album_pass else None,
        )
        handlers["keep"] = keeper.handle
    imports = ImportService(database, hub, youtube, notifications=notifications)
    if youtube is not None:
        handlers["match"] = imports.match
        handlers["prepare"] = Preparer(database, youtube).handle
    scheduler = Scheduler(database, handlers, workers={"interactive": 1, "background": 2}) if handlers else None
    imports.use(scheduler)
    return scheduler, keeper, imports


def create_app(
    settings: Settings | None = None,
    *,
    verifier: Verifier | None = None,
    db: Database | None = None,
    youtube: YoutubeSource | None = None,
    navidrome: NavidromeClient | None = None,
    gateway_client: httpx.AsyncClient | None = None,
    navidrome_admin: NavidromeAdmin | None = None,
    tools_active: Active | None = None,
    artist_lookup: ArtistLookup | None = None,
    catalogue: Catalogue | None = None,
) -> FastAPI:
    # FIRST of all, before a folder or a database is opened: a stored key is a function of the Unicode data of the Python that made it, so a server on a Python that is
    # not the pinned one (the image's, 3.12) does not start at all (P2-25; no setting turns this off). It would otherwise serve and write keys nothing ever re-checks.
    textnorm.require_pinned_unicode()
    settings = settings or Settings.from_env()
    database = db or Database(settings.db_path)
    database.migrate(version=__version__)
    # Right after the migrations and before anything else runs (no thread has started, no request can come), the stored keys that are not what the fold makes now are
    # rewritten (P2-25: a song in another alphabet was the key `||`; the plan runs at every start, so the keys of a rollback image are caught too), with its own backup, in
    # one transaction, never stopping the server from starting. The songs the old library scan made twice (N-11) are NOT merged here any more (N-47, audit B-138): a merge
    # cannot be undone and is judged on files the music server still lists, which only a COMPLETE pass of the library link can show (`refmerge.repair(db, listing)`, called at
    # the end of every such pass in `scanner.link_library`); the keys are already new by then, so the tombstones a merge writes carry them.
    keyrepair.repair(database)
    if youtube is None and settings.youtube:
        youtube = _default_youtube(settings, database)
    if isinstance(youtube, YoutubeSource) and youtube.verdicts is None:
        # The memory of the songs the source cannot get (N-13) lives in the database, so any source the application runs is given it here.
        youtube.verdicts = RefVerdicts(database)
    hub = Hub()
    client = navidrome or NavidromeClient(
        settings.navidrome_url, settings.navidrome_admin_user, settings.navidrome_admin_password
    )
    with database.tx() as conn:
        identity = load_or_create(conn)
        stream_key = stream_secret(conn)
    notifications = Notifications(database, hub)
    catalogue = catalogue or _default_catalogue(settings)
    # The ONE gate to the catalogue: every look-up of this server that has no client of its own (the cover finder, the artist finder, the keeper's cover and its album question)
    # goes through it, and so do the routes. Taken away again when the server stops (a test makes many apps in one process). Made BEFORE the keeper, which asks through it.
    deezer.install(catalogue.client)
    scheduler, keeper, imports = _background(settings, database, hub, youtube, client, notifications, catalogue)
    keep_watch = (
        KeepWatch(database, scheduler, hub, lambda: _youtube_status(youtube))
        if scheduler is not None and scheduler.handles("keep")
        else None
    )
    import_watch = (
        ImportWatch(database, scheduler, hub, imports)
        if scheduler is not None and imports is not None and scheduler.handles("keep")
        else None
    )
    the_verifier = verifier or NavidromeVerifier(settings.navidrome_url)

    def ended(person_id: str, user: str | None) -> None:
        # Locked, removed or given a new password: the live connections of the person close and the music server's remembered yes is forgotten.
        hub.end(person_id)
        forget_credentials(the_verifier, user)

    accounts = Accounts(
        database,
        navidrome_admin
        or NavidromeAdmin(settings.navidrome_url, settings.navidrome_admin_user, settings.navidrome_admin_password),
        notifications=notifications,
        server_name=settings.server_name,
        on_ended=ended,
    )
    # N-34 slice 2: which album a song is on, asked of the catalogue BEFORE the cover finder, so the one search that finds the album also gives the picture.
    album_pass = AlbumFinder.on(database, catalogue, music_dir=settings.music_dir) if settings.album_pass else None
    if not settings.album_pass:
        log.info(
            "the album pass is switched off (ENCORE_ALBUM_PASS=0): no album is asked of the catalogue and none is stamped, by the hourly pass or by a new keep"
        )
    finder = CoverFinder(database, music_dir=settings.music_dir, after=client.start_scan if client.configured else None)
    artist_finder = (
        ArtistFinder(database, client, artist_lookup, music_dir=settings.music_dir, after=client.start_scan)
        if client.configured
        else None
    )

    tombstone_purge = TombstonePurge(database)
    ref_janitor = RefJanitor(database)

    def errands() -> None:
        for errand in (
            accounts.heal_libraries,
            *((album_pass.run_once,) if album_pass is not None else ()),
            finder.run_once,
            *((artist_finder.run_once,) if artist_finder is not None else ()),
            tombstone_purge.run_once,  # N-31: old tombstones and old import lists go, so that the janitor below finds their songs unpointed
            ref_janitor.run_once,  # N-27: the song refs nobody points at (after the finders: they look at refs too)
        ):
            try:
                errand()
            except Exception:  # noqa: BLE001 - one errand failing must not stop the next, nor the library link
                log.exception("a background errand failed")

    linker = (
        LibraryLinker(
            database,
            client,
            scan_status=lambda: client.scan_status(quiet=True),
            every_s=settings.scan_every_min * 60.0,
            before=errands,
        )
        if client.configured and settings.scan_every_min > 0
        else None
    )

    # Not counted: the Docker health check, which would break every quiet moment.
    in_flight = InFlight(ignore=(f"{API_PREFIX}/info",))
    tools = _default_tools(settings, youtube, scheduler, in_flight, tools_active)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.hold_open()  # after the migrations (create_app ran them): see Database.hold_open
        if settings.workers:
            if scheduler is not None:
                scheduler.start()
            if linker is not None:
                linker.start()
            if tools is not None:
                tools.start()
            if keep_watch is not None:
                keep_watch.start()
            if import_watch is not None:
                import_watch.start()
        try:
            yield
        finally:
            # ONE budget for all the background threads (stopping.py): each is told to stop, then waited for only as long as the budget lasts. Before, every
            # stop had its own join (the scheduler 5 s for each of its four workers): a stop with busy workers outlasted Docker's ten seconds (B-129).
            deadline = time.monotonic() + LIFESPAN_STOP_S

            def room() -> float:
                return max(MIN_JOIN_S, deadline - time.monotonic())

            if import_watch is not None:
                import_watch.stop(timeout=room())
            if keep_watch is not None:
                keep_watch.stop(timeout=room())
            if tools is not None:
                tools.stop(timeout=room())
            if linker is not None:
                linker.stop(timeout=room())
            if scheduler is not None:
                scheduler.stop(timeout=room())
            # After the threads that ask the catalogue (the errands, the keeper) have stopped, not before: a look-up in flight would find its client closed.
            if deezer.installed() is catalogue.client:
                deezer.install(None)
            catalogue.close()
            database.release()

    app = FastAPI(title="Encore server", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.services = Services(
        settings=settings,
        db=database,
        hub=hub,
        verifier=the_verifier,
        youtube=youtube,
        scheduler=scheduler,
        keeper=keeper,
        linker=linker,
        imports=imports,
        accounts=accounts,
        notifications=notifications,
        limiter=Limiter(),
        tools=tools,
        identity=identity,
        music=client,
        keep_watch=keep_watch,
        import_watch=import_watch,
        stream_key=stream_key,
        artist_finder=artist_finder,
        catalogue=catalogue,
    )
    app.add_middleware(InFlightMiddleware, tracker=in_flight)
    app.add_middleware(BodyLimit)
    # The order is the order of the groups in docs/17; a path that could match two routes is matched by the first.
    for group in (
        info_routes,
        session_routes,
        people_routes,
        refs_routes,
        keep_routes,
        library_routes,
        playlists_routes,
        imports_routes,
        playback_routes,
        catalogue_routes,
    ):
        app.include_router(group.router)
    app.add_api_route("/encore/stream/{ref_id}", media_routes.stream, methods=["GET", "HEAD"])
    app.add_api_route("/encore/cover/{cover_id}", media_routes.cover, methods=["GET", "HEAD"])
    # Before the music server's catch-all below: an invitation link must never reach it (D-39).
    app.add_api_route("/encore/join/{code}", people_routes.join_page, methods=["GET", "HEAD"], include_in_schema=False)
    app.add_api_websocket_route("/encore/live", live_routes.live)
    gateway.mount(
        app, settings.navidrome_url, client=gateway_client, public=is_public_request, authorize_public=authorize_public_subsonic
    )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(MusicServerUnavailable)
    async def music_server_away(_: Request, error: MusicServerUnavailable) -> JSONResponse:
        # Not a wrong password and not counted as a guess (the handler runs before anything counts it): a retryable 503 the phone waits out (AUDIT B-41).
        log.info("the music server could not check a login: %s", error)
        away = ApiError("server_busy", "The music server is not answering just now. Try again in a moment.")
        return JSONResponse(away.body(), status_code=away.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(ApiError("validation").body(), status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, error: Exception) -> JSONResponse:
        log.exception("unexpected error: %s", error)
        return JSONResponse(ApiError("internal").body(), status_code=500)

    return app
