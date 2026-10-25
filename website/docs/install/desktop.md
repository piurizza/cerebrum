# Desktop app

The desktop app shows Cerebrum in its own window instead of a browser tab, on
Linux, macOS and Windows. It is a window onto a server that's already running:
it has no notes or accounts of its own.

On first launch it looks for a server on the same computer
(`http://localhost:7811`, where the install script puts it) and connects
without asking if one answers. Otherwise it asks for the server's address.
You can change the address later with **Change server URL**.

Download the app from the
[latest release](https://github.com/piurizza/cerebrum/releases/latest).

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

!!! note
    CI installs and launches the Windows build on every change to the desktop
    app, but it hasn't been tried by hand on a Windows PC yet.

## Known limits

- No automatic updates: install the new release's package to update.
- Signing in with Google doesn't work in the desktop app, because Google
  refuses sign-in from embedded browsers. Self-hosted identity providers work.
- If the server drops in the moment between the app checking it and opening
  it, the window can show a raw error page. Restart the app.
