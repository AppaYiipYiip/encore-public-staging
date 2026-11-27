"""The add-on `music-web-page` (docs/35 section 2): the music server's own web page, sign-in and programming interface, through this server's address."""

from __future__ import annotations

from .model import OFF, RUNS, AddOn, switch

ADDON = AddOn(
    id="music-web-page",
    title="The music server's own web page",
    summary="Lets devices on your home network open the music server's own web page. Off, only the apps that use your server's address work.",
    states=(RUNS, OFF),
    default=OFF,
    running=switch("music_web_page"),
    setting="music_web_page",
    risk_text=(
        "This opens the music server's own web page, its sign-in and its programming interface to the devices this server can prove are on your home network. "
        "Where your computer hides who is visiting (Docker on Windows or a Mac, some network storage boxes, a router that forwards a port to it), the server cannot "
        "tell a visitor in your house from one on the internet, and keeps the page shut even with this on. Turn it on only if you use that web page."
    ),
)
