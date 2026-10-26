# Desktop app

The desktop app shows Cerebrum in its own window instead of a browser tab, on
Linux, macOS and Windows. It is a window onto a server that's already running:
it has no notes or accounts of its own.

On first launch it looks for a server on the same computer
(`http://localhost:7811`, where the install script puts it) and connects
without asking if one answers. Otherwise it asks for the server's address. To
point it at another server later, see
[Connect to a different server](#connect-to-a-different-server).

Download the app from the
[latest release](https://github.com/piurizza/cerebrum/releases/latest). Each
package carries a build attestation from this project's release workflow; to
check a download before installing it:

```sh
gh attestation verify <downloaded file> --owner piurizza
```

## Linux

The release has a `.deb` and an `.rpm` for x86_64. Install with your package
manager, which also pulls in WebKitGTK:

```sh
sudo apt install ./Cerebrum_*_amd64.deb      # Debian, Ubuntu
sudo dnf install ./Cerebrum-*.x86_64.rpm     # Fedora
```

## macOS

Open the `.dmg` (one for Apple Silicon and Intel) and drag Cerebrum into
**Applications**.

The app is not notarized by Apple, so macOS blocks the first launch. Open it
once, then go to **System Settings**, **Privacy & Security**, and choose
**Open Anyway**. macOS remembers the choice. Removing the download flag has the
same effect:

```sh
xattr -dr com.apple.quarantine /Applications/Cerebrum.app
```

## Windows

Run the setup `.exe`. It installs for your user only, without administrator
rights.

The installer is not code-signed, so SmartScreen shows "Windows protected your
PC". Choose **More info**, then **Run anyway**. The app uses Microsoft's
WebView2, which Windows 11 includes; on Windows 10 the installer downloads it
if it's missing.

Windows support is new; please
[report any problem](https://github.com/piurizza/cerebrum/issues).

## Connect to a different server

The app remembers the first server it connects to. To switch, quit the app,
delete its saved settings, and start it again; it then asks for an address.
The file is `settings.json` in:

| System | Folder |
|---|---|
| Linux | `~/.local/share/com.piurizza.cerebrum/` |
| macOS | `~/Library/Application Support/com.piurizza.cerebrum/` |
| Windows | `%APPDATA%\com.piurizza.cerebrum\` |

If the app can't reach an address it has never connected to, it shows
**Change server URL** there and then.

## Known limits

- No automatic updates: install the new release's package to update.
- Signing in with Google doesn't work in the desktop app, because Google
  refuses sign-in from embedded browsers. Self-hosted identity providers work.
- If the window shows a browser error page, restart the app.
