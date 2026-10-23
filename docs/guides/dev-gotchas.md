# Developer gotchas: traps met on this project's Windows PC and the pattern that works

Each line cost a failed call or a lost hour once. No secrets and no machine addresses are in this file. It describes tools as they were on 2026-10-22; if a tool has changed, trust
the tool and fix the line. Rules about *what* to do are in `docs/30-engineering-guide.md`; this file is *how* not to trip.

## Windows, PowerShell 5.1 and the shell

| Trap | What works |
|------|-----------|
| PowerShell 5.1 cannot set a `Range` header (`Invoke-WebRequest -Headers @{Range=…}` throws) | `curl.exe -r 0-65535 -o NUL -w …` |
| After `powershell -File x.ps1`, a following `ssh -o …` is read by PowerShell as `-OutputFormat` | Run `ssh` from the Bash tool |
| A foreground `sleep` or `Start-Sleep` before a command is blocked | Start a polling loop in the background and do other work; it wakes you when it exits |
| The Bash tool's `cd` persists and changes the working directory | Use absolute paths |
| The working tree is CRLF; Linux shells and `ssh … 'cat > f'` choke on it | Strip with `tr -d '\r'` before sending anything to Linux |
| A long shell here-document with quotes breaks the parser; Python patches with `\n` in non-raw strings break | Write scripts with a file-writing tool; edit shell scripts with an editor tool |
| `flutter build` run through PowerShell reports "failed (exit 1)" when Gradle prints a deprecation warning | Run it from the Bash tool, or check the APK's timestamp, or `aapt2 dump badging` for the version code |
| Gradle cannot reach Google when the PC picks IPv6 | `./gradlew --stop`, then `JAVA_TOOL_OPTIONS=-Djava.net.preferIPv4Stack=true`, then build |
| The pre-commit gate takes 2 to 4 minutes and floods output; with three emulators and Gradle running, a commit was killed for memory | Redirect its output and check `git log`; run `./gradlew --stop` first; keep at most two emulators running |
| The gate rejects unsorted imports and more: a stricter profile (`app/analysis_options_strict.yaml`) applies to `lib/{app,core,data,design,domain,features,playback}` and the matching `test/` folders (and to `packages/encore_session`) | Sort imports (`directives_ordering`; `dart format` does not); await or `unawaited(...)` every Future, cancel subscriptions, close sinks, never `print`, annotate types (strict casts and inference) |
| Docs-only commits skip the gate | That is intended; it is the pre-commit hook's second step |

## Building and testing

* Release APK for an emulator: `flutter build apk --release --target-platform android-x64`; for phones, arm64. The app's launch component is `app.encore.player/app.encore.player.MainActivity`.
* Server (`server/encore_server`): `pip install -e '.[youtube,dev]'`, then `ruff check . && ruff format --check . && mypy encore_server && pytest`. Plain `pytest` does not put the project folder on
  the path, which is why `pyproject.toml` sets `pythonpath`. The legacy server suites use `python -m unittest discover -s tests` (not `-I`).
* Integration suite (a real music server in Docker): `docker compose -f tests/integration/compose.yaml up --build --abort-on-container-exit --exit-code-from tests`; run `down -v` before each run.
* CI: the App check took about 15 minutes for its main job and about 27 in total with the debug build (as recorded on 2026-10-22), and it **restarts on every push** to a pull request that changes `app/**`; batch pushes, and keep server-only work on its own
  branch. A workflow runs from a branch only if its file is on that branch; `gh workflow run` needs the workflow on `main`. Do not push tags.
* The architecture test forbids a silent `on Object {}` and ratchets catch-alls: log inside every `catch`.

## Driving the emulator (`tools/journeys/ui.py`)

* **Never tap blind.** Run `ui.py dump` first and tap by position from it. The sign-in fields have empty labels. Move focus with TAB, hide the keyboard with BACK; the form shifts when the
  keyboard opens, so dump again before the next field. `pm clear` resets a form that took stray input.
* `ui.py dump` hangs while the player screen animates: use `shot`, or tap by coordinates. `tap "text"` can hit a longer sentence that contains the word: tap the button by position.
* In Git Bash set `MSYS_NO_PATHCONV=1` for `adb` paths. `adb shell am start … --es X 'text with spaces'` needs the whole command in **one** quoted string.
* A freshly booted emulator has no network for a few seconds (the join screen said "Can't reach" once and worked on retry).
* **Passwords:** `python -I tools/journeys/ui.py typefile <login file>` types only the `password:` line (any other file is typed whole), pushes it, types it and deletes it. It prints nothing.
  Never screenshot while a password field is filled. A readable screenshot has leaked a password once.
* Over ssh, `pkill -f <pattern>` kills its own shell (the pattern is in its command line): use `pkill -x name`.

## Docker and Linux hosts

* A bind-mounted folder that does not exist is created by the Docker daemon as root; anything running as another user that writes there needs its owner fixed first.
* Ubuntu 26.04's `sudo` is `sudo-rs`: it has no `-E`, so environment variables do not pass through. The installer finds the GitHub login of the person who typed `sudo` (`SUDO_USER`) instead.
* A large image download on a slow line also starves the home internet: check the rate before starting one.

## Music-server (Navidrome) facts that surprised us

* Its Subsonic `path` is built from tags, not the file name: match kept files by size.
* A moved file keeps its id; a re-tag only takes effect when the old tags are dropped (`-map_metadata -1`).
* It serves covers as immutable per id: a cached blank placeholder never refreshes by itself (the app's cover cache refuses a blank answer for that reason).
* After a new install the music server may answer HTTP 429 ("too many sign-ins") for a while: wait it out; the installer does.
