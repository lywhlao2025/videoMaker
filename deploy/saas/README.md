# SaaS deployment

This directory records the production-specific setup used for the `/video/`
service. Runtime secrets and generated data are intentionally excluded.

## Files

- `../../docker-compose.saas.yml`: Streamlit `/video` service plus an independent
  durable worker, SQLite task state, resource limits, and source overrides.
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

The WebUI writes jobs to `storage/webui_jobs/pending`. The worker claims them in
a separate container, so closing the browser does not cancel generation. Task
state is shared through `storage/task_state.sqlite3`, and every task writes a
persistent `storage/tasks/<task-id>/task.log` file.

The high-quality workflow stores Project/Run/Candidate metadata in
`storage/pipeline.sqlite3` and immutable stage artifacts under
`storage/projects/<project-id>/runs/<run-id>`. Script scoring and revision jobs
use the same durable worker queue as video rendering jobs.

Do not commit `config.toml`, `storage/`, TLS private keys, or authentication
cookie values.
