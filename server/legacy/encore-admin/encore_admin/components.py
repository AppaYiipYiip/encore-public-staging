"""Everything the server is made of, in plain words (docs/49 P3): what each part is called, how it is doing, and which ones may be restarted
from the website. Nothing here starts or stops anything the owner did not already switch on: parts are added with the setup command (`QUALITY=1
bash setup.sh`), the website only restarts and reads."""
from __future__ import annotations

#: container name -> the name a person would use. The order is the order of the page.
NAMES = {
    "navidrome": "Music server",
    "encore-people": "People and invitations",
    "encore-fetch": "Songs from YouTube",
    "encore-quality": "Best quality (the service)",
    "encore-lidarr": "Lidarr (finds and files albums)",
    "encore-slskd": "Soulseek client (slskd)",
    "encore-soularr": "Soularr (asks the network for what Lidarr wants)",
    "encore-recs": "Suggestions for each person",
    "encore-hub": "Jam (listening together)",
    "encore-tailscale": "Reaching it from outside (Tailscale)",
    "caddy": "Secure address with your own name (Caddy)",
    "encore-admin": "This website",
}

NOTES = {"running": "Running.", "starting": "Starting up…", "unhealthy": "Running, but its own check is failing.",
         "restarting": "Keeps stopping and starting again.", "stopped": "Stopped."}

#: The website runs in encore-admin: it cannot restart the container it is answering from.
CANNOT_RESTART = {"encore-admin"}


def describe(details: dict[str, dict]) -> list[dict]:
    """`{"container", "name", "state", "note", "image", "canRestart"}` for every part that exists, in the page's order."""
    out = []
    for container, name in NAMES.items():
        found = details.get(container)
        if found is None:
            continue
        image = found.get("image", "")
        if image.startswith("sha256:") or not ("/" in image or ":" in image):
            image = "built on this machine"  # an image made here has no name a person could look up
        out.append({"container": container, "name": name, "state": found["state"], "note": NOTES.get(found["state"], found["state"]),
                    "image": image, "canRestart": container not in CANNOT_RESTART})
    return out
