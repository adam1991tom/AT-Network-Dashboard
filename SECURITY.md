# Security notes

## Login protection

`/login` is rate-limited in-process: 5 failed attempts per `(ip, username)` and 20
failed attempts per `ip` (across usernames) within a 15-minute window return
HTTP 429. This resets on container restart and is not shared across replicas -
fine for the current single-instance deployment, but wouldn't hold up if this
app were ever run with multiple replicas behind a load balancer.

## CSRF

All non-GET `/api/*` routes (other than `/login` and `/setup-admin`, which
don't have a session yet) require a `X-CSRF-Token` header matching the
`at_csrf` cookie set at login (double-submit cookie pattern). `app/static/csrf.js`
attaches this automatically to same-origin `fetch()` calls, so page code
doesn't need to handle it manually. `Origin` is also checked when the browser
sends it, as defense-in-depth.

## Session cookie

The session and CSRF cookies are `Secure` only when `FORCE_HTTPS=true` (see
`.env.example`). Default is `false`, correct for a plain-HTTP LAN deployment.
Set it to `true` if this is ever put behind a reverse proxy terminating TLS -
otherwise browsers will drop the cookies.

## Docker socket on the updater sidecar

`at-network-dashboard-updater` mounts `/var/run/docker.sock` so it can rebuild
and restart the other two containers when a self-update is requested (see
`app/updater.py`, which writes `/data/update-request.json`/`update-state.json`
for the sidecar to act on). This grants that container full control of the
Docker daemon on the host - the single largest blast-radius item in this
stack. Accepted as-is for now since the sidecar's own surface area is small
and not web-exposed, but if this is ever hardened further, scope it through a
proxy such as `tecnativa/docker-socket-proxy` restricted to just the
containers/images verbs the updater actually needs, rather than the raw
socket.
