# SaaS deployment

This directory records the production-specific setup used for the `/video/`
service. Runtime secrets and generated data are intentionally excluded.

## Files

- `../../docker-compose.saas.yml`: Streamlit `/video` base path, resource limits,
  persistent storage, and source overrides.
- `nginx-video.conf.example`: authenticated reverse proxy and protected downloads.
- `site-nav.js`: shared Chat/Video navigation injected by Nginx.

## Deploy

1. Copy `config.example.toml` to `config.toml` and fill credentials locally.
2. Replace `CHANGE_ME_SHARED_SSO_COOKIE_VALUE` in the Nginx example with the
   same protected value used by the Chat login service.
3. Install `site-nav.js` at `/var/www/site-nav/site-nav.js`.
4. Merge the Nginx locations into the domain's HTTPS server block and run
   `nginx -t` before reloading.
5. From the repository root, run:

   ```bash
   docker compose -f docker-compose.saas.yml up -d
   ```

Do not commit `config.toml`, `storage/`, TLS private keys, or authentication
cookie values.
