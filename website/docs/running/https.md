# HTTPS

Out of the box, Cerebrum answers on the server only, at
`http://localhost:7811`. To use it from your phone or another computer, give
it an HTTPS address. HTTPS keeps your password and API tokens private on the
network, and phones need a **trusted** certificate to install the app and keep
it working offline.

| Option | Trusted by phones | Needs | Identity-provider sign-in |
|---|---|---|---|
| [Tailscale serve](#tailscale-serve) | Yes | A Tailscale account | Not yet |
| [Tailscale certificate on the built-in HTTPS port](#tailscale-certificate-on-the-built-in-https-port) | Yes | A Tailscale account, a monthly renewal | Yes |
| [Reverse proxy with a domain](#reverse-proxy-with-a-domain) | Yes | A domain, a proxy such as Caddy | Not yet |
| [Built-in self-signed certificate](#built-in-self-signed-certificate) | No | Nothing | Yes, after accepting the warning |

"Not yet": behind a proxy that handles HTTPS in front of Cerebrum, sign-in
with an [identity provider](identity-provider.md) builds its return address
with `http://`, and the provider rejects it. Password sign-in works.

## Tailscale serve

[Tailscale](https://tailscale.com) connects your devices in a private network,
your tailnet. `tailscale serve` publishes Cerebrum on the server's tailnet name
with a certificate Tailscale renews on its own. Only your tailnet's devices
can reach it, from anywhere.

1. Install Tailscale on the server and sign in (`sudo tailscale up`).
2. In the Tailscale admin console, under **DNS**, turn on **MagicDNS** and
   **HTTPS Certificates**.
3. Publish Cerebrum:

    ```sh
    sudo tailscale serve --bg 7811
    ```

    Use your `CEREBRUM_PORT` if you changed it. Tailscale prints the address,
    `https://<machine>.<tailnet>.ts.net/`.

4. Install Tailscale on your phone and other devices, signed in to the same
   account.

Keep `CEREBRUM_BIND_ADDRESS=127.0.0.1`: Tailscale reaches Cerebrum on the
server itself, so no port needs to be open to your network. To stop
publishing, run `sudo tailscale serve reset`.

## Tailscale certificate on the built-in HTTPS port

Cerebrum's web server also listens for HTTPS, on `CEREBRUM_HTTPS_PORT` (7812).
You can give it a Tailscale certificate instead of its self-signed one.

1. Set up Tailscale with **MagicDNS** and **HTTPS Certificates**, as above.
2. Allow your user to fetch certificates, once:

    ```sh
    sudo tailscale set --operator=$USER
    ```

3. Fetch a certificate for the server's tailnet name. `tailscale cert` with no
   name prints the name to use.

    ```sh
    tailscale cert <machine>.<tailnet>.ts.net
    ```

4. Copy it into Cerebrum and restart the web server, in the install folder:

    ```sh
    docker compose cp <machine>.<tailnet>.ts.net.crt frontend:/etc/nginx/certs/cerebrum.crt
    docker compose cp <machine>.<tailnet>.ts.net.key frontend:/etc/nginx/certs/cerebrum.key
    docker compose restart frontend
    ```

5. Let other devices reach the port: set `CEREBRUM_BIND_ADDRESS=0.0.0.0` in
   `.env` and run `docker compose up -d`.

Open `https://<machine>.<tailnet>.ts.net:7812` from any tailnet device.

Tailscale certificates last 90 days. Repeat steps 3 and 4 to renew; a monthly
cron job is enough, and thanks to step 2 it doesn't need root.

!!! warning
    With `0.0.0.0`, the ports are open on every network the server is on, not
    just the tailnet. Bind to the server's tailnet address instead (shown by
    `tailscale ip -4`) to keep them on the tailnet only.

## Reverse proxy with a domain

If you have a domain, put a reverse proxy such as Caddy or nginx in front of
Cerebrum, with a certificate from Let's Encrypt. Point it at
`http://127.0.0.1:7811` on the server. For example, with Caddy:

```caddy
notes.example.com {
    reverse_proxy 127.0.0.1:7811
}
```

This needs the domain to point at your server and, for Let's Encrypt, the
proxy to be reachable from the internet or to use a DNS challenge.

## Built-in self-signed certificate

Cerebrum makes a self-signed certificate on its first start, so
`https://localhost:7812` works on the server out of the box. Browsers warn
that it isn't trusted.

To use it from other devices on your network, set these **before the first
start**, since the certificate is made once:

```sh
CEREBRUM_BIND_ADDRESS=0.0.0.0
CEREBRUM_TLS_SAN=IP:192.0.2.10    # the server's address on your network
```

Then open `https://192.0.2.10:7812` and accept the warning once. This is
enough for offline use in a desktop browser, but **not** for installing the
phone app, which needs a trusted certificate.

To make a new certificate later, for example for a new address, delete the
certificate volume and restart: `docker compose down`, then
`docker volume ls` to find the volume ending in `cerebrum_tls_certs`,
`docker volume rm` it, and `docker compose up -d`.

## The session cookie

Over HTTPS, set `AUTH_COOKIE_SECURE=true` so browsers send the session cookie
only over HTTPS. Leave it off if you also sign in over plain `http://` from
another machine: with it on, sign-in over plain HTTP stops working. See
[Security](security.md).
