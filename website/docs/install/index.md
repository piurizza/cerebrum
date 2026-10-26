# Install

Cerebrum is a server you run once, then reach from any browser, the phone app
or the desktop app. The server runs in Docker.

| You want to | Use |
|---|---|
| Install on Linux or macOS with one command | [The install script](docker.md) |
| Install on Windows, or manage the Compose file yourself | [Install by hand](by-hand.md) |
| Use Cerebrum on a phone | [Phone app](phone.md) |
| Use Cerebrum in its own window on a computer | [Desktop app](desktop.md) |
| Move to a newer release | [Upgrade](upgrade.md) |

New to all this? The [quick start](../quick-start.md) walks one path from
start to finish.

## Requirements

**To run Cerebrum:** Docker with the Compose v2 plugin (`docker compose`), on
x86_64 or arm64 (including Apple Silicon Macs and other ARM machines). The
images are prebuilt, so nothing is compiled.

| Resource | Needed | Measured |
|---|---|---|
| RAM | 150 MB | 116 MB backend and 20 MB web server, idle |
| CPU | Any | Under 1% of one core when idle |
| Disk, images | 450 MB | 338 MB backend and 105 MB web server |
| Disk, notes | Your notes plus their index | 3.2 MB for 58 notes, index and accounts included |

Measured with the documentation's 58-note demo vault on x86_64 with Docker
Engine. The arm64 images run on Apple Silicon and are tested in CI; a
Raspberry Pi is untested.

Cerebrum uses two ports, **7811** (HTTP) and **7812** (HTTPS), by default.
Both listen on the server only until you choose otherwise.

!!! note "On Linux, use Docker Engine"
    Docker Engine runs containers directly. Docker Desktop on Linux runs them in
    a virtual machine, which adds memory use and file-sharing delays, and is not
    recommended for Cerebrum.

**Browsers:** the end-to-end tests run on Chrome, including a phone-sized
view. Other current browsers are expected to work. Offline use and installing
on a phone need [HTTPS](../running/https.md).

**To build the images yourself** instead of using the published ones, see
[Development](../development/index.md).
