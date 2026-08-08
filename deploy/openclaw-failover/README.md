# OpenClaw HTTP failover policy

This directory tracks the HTTP-status allowlist deployed on the personal OpenClaw server.

Only statuses listed in `switchHttpStatuses` are classified as failover errors. All other
HTTP statuses are treated as non-failover errors. The installer currently rejects
401, 402, 403 and 429 to prevent automatic account switching for authentication,
billing and rate-limit failures.

## Server paths

- Policy: `/root/.openclaw/failover-policy.json`
- Installer: `/root/.openclaw/failover-policy/install.mjs`
- Test: `/root/.openclaw/failover-policy/test.mjs`
- systemd drop-in: `/root/.config/systemd/user/openclaw-gateway.service.d/failover-policy.conf`

No OAuth tokens, WeChat credentials, SSH keys or proxy credentials belong in this directory.

## Deploy

Run from this directory on the server, or copy the files to their paths first:

```bash
install -m 600 failover-policy.json /root/.openclaw/failover-policy.json
install -d -m 700 /root/.openclaw/failover-policy
install -m 700 install.mjs test.mjs /root/.openclaw/failover-policy/
install -d -m 700 /root/.config/systemd/user/openclaw-gateway.service.d
install -m 600 failover-policy.conf \
  /root/.config/systemd/user/openclaw-gateway.service.d/failover-policy.conf

systemctl --user daemon-reload
/root/.openclaw/tools/node/bin/node /root/.openclaw/failover-policy/install.mjs
/root/.openclaw/tools/node/bin/node /root/.openclaw/failover-policy/test.mjs
systemctl --user restart openclaw-gateway.service
systemctl --user status openclaw-gateway.service --no-pager
```

The installer is idempotent. OpenClaw upgrades may replace its bundled classifier; the
systemd pre-start hook reapplies the patch and fails visibly if the expected classifier
signature has changed.
