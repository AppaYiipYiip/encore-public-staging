"""The admin website over https (docs/50 section 4).

The sign-in window is a browser streamed to the page, and a browser only lets a page use what such a stream needs (WebCodecs) from a
*secure context*: an https address. So the website serves https. It makes itself a certificate the first time it starts (with the
`openssl` tool the image carries), keeps it in its data folder, and uses it from then on. A browser warns once about a certificate
it does not know ("not private"): that is expected for a server in somebody's house, and the page says so on the way; a server
reached through Tailscale's own https needs none of this.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

log = logging.getLogger("encore_admin.tls")


def ensure_certificate(directory: Path, names: tuple[str, ...] = (), *,
                       run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run) -> tuple[Path, Path] | None:
    """`(certificate, key)` files in [directory], made if they are not there yet; `None` when they cannot be made (the website
    then serves plain http and says the sign-in window needs https)."""
    certificate, key = directory / "admin.crt", directory / "admin.key"
    if certificate.is_file() and key.is_file():
        return certificate, key
    try:
        directory.mkdir(parents=True, exist_ok=True)
        alt = ["DNS:localhost", "IP:127.0.0.1"] + [("IP:" if name.replace(".", "").isdigit() else "DNS:") + name for name in names if name]
        done = run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650", "-subj", "/CN=Encore admin",
                    "-addext", "subjectAltName=" + ",".join(alt), "-keyout", str(key), "-out", str(certificate)],
                   capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        log.warning("no https: the certificate could not be made (%s)", type(error).__name__)
        return None
    if done.returncode != 0 or not certificate.is_file() or not key.is_file():
        log.warning("no https: openssl said: %s", (done.stderr or "").strip()[-200:])
        return None
    try:
        key.chmod(0o600)
    except OSError:
        pass
    log.info("made a certificate for the admin website (it lasts ten years)")
    return certificate, key
