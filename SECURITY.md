# SECURITY

## Auth model

CardForge's data model always supports multiple `users` (Phase 2). The API's
enforcement of that is controlled by `CARDFORGE_AUTH_MODE`:

- `single-user-no-login` (default): no login screen, no session cookies. The
  API trusts whoever can reach it. **You are expected to restrict network
  access yourself** — bind it to a LAN/VPN-only interface, put it behind your
  own reverse proxy with auth (Caddy `basicauth`, Authelia, Tailscale, etc.),
  or keep it on an isolated home network. This mode exists because CardForge
  is typically a single collection owner's tool.
- `multi-user`: turns on login + session enforcement across the API. No
  schema migration is needed to switch — `users`/sessions always exist.

Do not expose a `single-user-no-login` instance directly to the public
internet.

## Persistent secrets

Four secrets exist: `db_password` (Postgres, shared with `DB_PASSWORD`),
`app_secret_key`, `grafana_admin_password`.

**Resolution order, decided once at `secrets-init` time (see
`backend/scripts/init_secrets.py`) and re-checked on every stack start:**

1. If a persistent file already exists at `./data/secrets/<name>`, **that
   file wins** — the corresponding environment variable is ignored.
   This is deliberate: it guarantees a restart, or someone editing `.env`
   later, can never silently change a password out from under an
   already-initialized Postgres role or already-issued session tokens.
2. Otherwise, the first non-empty of the documented environment variables
   (`POSTGRES_PASSWORD`/`DB_PASSWORD`, `APP_SECRET_KEY`,
   `GRAFANA_ADMIN_PASSWORD`) is used and written to the persistent file.
3. Otherwise, a cryptographically secure random value
   (`secrets.token_urlsafe(48)`) is generated and written to the persistent
   file.

Files are written with `0600` permissions inside `./data/secrets/` (`0700`
directory), owned by the container's `cardforge` user (uid 1000). Values are
never written to logs, and the app never dumps its own settings object with
secrets inlined (`app/core/secrets.py` deliberately keeps secret resolution
out of the general `Settings` object).

Postgres and Grafana receive secrets via the `*_FILE` mechanism their
official images support (`POSTGRES_PASSWORD_FILE`,
`GF_SECURITY_ADMIN_PASSWORD__FILE`) rather than plain environment variables,
so the value never appears in `docker inspect` output for those containers
either.

### Rotating a secret

Secrets are **never** overwritten automatically. To rotate one deliberately:

```bash
./scripts/reset-secrets.sh app_secret_key        # safe: only invalidates sessions
./scripts/reset-secrets.sh grafana_admin_password # safe
./scripts/reset-secrets.sh db_password            # see warning below
docker compose up -d                              # regenerates the removed secret(s)
```

Rotating `db_password` removes the file CardForge will use going forward,
but does **not** change the password Postgres already has for its
`cardforge` role. You must also run `ALTER ROLE cardforge WITH PASSWORD
'<new-value>';` inside Postgres with the new value (read it from
`./data/secrets/db_password` after `docker compose up -d` has regenerated
it), or the backend will fail to connect. This is why `reset-secrets.sh`
prints an explicit warning and requires typed confirmation per secret.

## SSRF protections (public URL imports, Phase 5)

The Moxfield/Archidekt adapters and any generic configurable source that
fetches a user-supplied URL go through a shared guard before making a
request:

- Only `http`/`https` schemes are allowed.
- The resolved IP is checked against RFC 1918 private ranges, loopback,
  link-local, and other non-routable ranges — all blocked.
- `localhost` and container/service DNS names on the compose network are
  blocked.
- Redirects are followed manually (not by the HTTP client) so each hop is
  re-validated against the same rules.
- Login pages, auth walls, and CAPTCHA pages are detected and reported as
  `AUTH_REQUIRED`, never bypassed.

CardForge never stores third-party credentials, never automates a login
form, and never solves/bypasses a CAPTCHA.

## Data handling

Collection data, decklists, and price observations are personal/private by
nature. Nothing in CardForge phones home; the only outbound network calls
are the ones you explicitly enable per source (Scryfall, MTGJSON, Moxfield,
Archidekt, Cardmarket) and each can be disabled independently in
**Sources**.

## Reporting a vulnerability

This is a self-hosted hobby project without a dedicated security contact
inbox at this time — please open a GitHub issue marked `security` (avoid
posting exploit details for unpatched issues in a public issue if the
project ever gains other users; until then, an issue is fine).
