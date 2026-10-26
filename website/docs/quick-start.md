---
description: Install Cerebrum on a home server with Docker, reach it over HTTPS with Tailscale, and install it on your phone.
---

# Quick start

This guide takes you from a home server with Docker to Cerebrum running, your
account created, a first note written and the app installed on your phone. It
takes about 15 minutes.

It makes a few choices for you: Cerebrum runs on the server with the install
script, and your phone reaches it through [Tailscale](https://tailscale.com),
which gives it a private HTTPS address with no domain and no open ports. Other
setups are covered in [Install](install/index.md) and
[HTTPS](running/https.md).

## 1. Check what you need

- A Linux or macOS machine that stays on, with **Docker** and the
  **Compose v2** plugin (`docker compose version` prints a version). On Linux,
  Docker Engine works better than Docker Desktop.
- About **500 MB of disk** for the images, plus room for your notes.
- A free **Tailscale account**, and your phone.

## 2. Install Cerebrum

On the server, as your normal user (not root):

```sh
curl -fsSL https://github.com/piurizza/cerebrum/releases/latest/download/install.sh | sh
```

The script installs into `~/cerebrum-server`, generates the secrets, starts
Cerebrum and waits until it answers. At the end it prints a one-time
**invite token**. Copy it; you need it in step 4.

!!! tip "Prefer to read the script first?"
    Download it, check that this project's release workflow built it, then run
    it:

    ```sh
    curl -fsSLO https://github.com/piurizza/cerebrum/releases/latest/download/install.sh
    gh attestation verify install.sh --owner piurizza
    sh install.sh
    ```

Cerebrum now answers at `http://localhost:7811`, on the server only.

## 3. Give it an HTTPS address with Tailscale

Phones only install web apps from a trusted HTTPS address. Tailscale serve
gives Cerebrum one, with a certificate it renews on its own.

1. Install Tailscale on the server and sign in:

    === "Linux"

        ```sh
        curl -fsSL https://tailscale.com/install.sh | sh
        sudo tailscale up
        ```

        Tailscale's script picks the right package for your distribution.

    === "Fedora"

        ```sh
        sudo dnf install tailscale
        sudo systemctl enable --now tailscaled
        sudo tailscale up
        ```

    === "macOS"

        Install the Tailscale app from
        [tailscale.com/download](https://tailscale.com/download) and sign in.
        Run the commands below with its command-line tool, as Tailscale's
        documentation for macOS describes.

    `tailscale up` opens a sign-in link. Other systems are on
    [Tailscale's download page](https://tailscale.com/download).

2. In the Tailscale admin console, open **DNS** and turn on **MagicDNS** and
   **HTTPS Certificates**.

3. Publish Cerebrum on the tailnet:

    ```sh
    sudo tailscale serve --bg 7811
    ```

    It prints the address, of the form
    `https://<machine>.<tailnet>.ts.net/`. The setting survives reboots;
    `sudo tailscale serve reset` removes it.

Only devices signed in to your tailnet can open that address.

## 4. Create your account

Open `https://<machine>.<tailnet>.ts.net/` in a browser on any device in your
tailnet. Choose **Register**, pick a username and password, and paste the
invite token from step 2 as the **Invite token**.

This first account is the admin. Other people get their own invite from
**Settings**; see [Accounts and invites](running/accounts.md).

## 5. Write a first note

Choose **+ New note**, pick a folder (or stay at the top) and type a file
name, such as `first-note.md`. The new note opens; choose **Edit** and start
writing. Type `[[` to link to another note. Save with ++ctrl+s++ (++cmd+s++
on a Mac).

Your note is now a file in `~/cerebrum-server/vault`.

## 6. Install it on your phone

1. Install the Tailscale app on your phone and sign in to the same account.
2. Open `https://<machine>.<tailnet>.ts.net/` and sign in.
3. Install the app:
    - **Android, Chrome:** browser menu, then **Install app**. Or **Settings**,
      then **Install app**, inside Cerebrum.
    - **iPhone, Safari:** **Share**, then **Add to Home Screen**.

Cerebrum opens full screen from your home screen and keeps your notes readable
offline. See [Phone app](install/phone.md) for details.

## Next steps

- [Back up your vault and accounts](running/backups.md).
- [Bring notes from another app](import/index.md).
- [Connect an AI assistant over MCP](agents/index.md).
- [Install the desktop app](install/desktop.md).
- Learn the [features](features/index.md).
- When a new release comes out, read its
  [upgrade notes](upgrade/index.md), then [upgrade](install/upgrade.md) by
  running the install command again.
