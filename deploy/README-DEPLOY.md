# Deploy wildbill-charts alongside existing site (DigitalOcean droplet)

Goal: existing site on :80/443 stays untouched. Wildbill runs isolated on
127.0.0.1:8910 via systemd + new nginx server{} (subdomain).

Files:
- requirements.txt — pinned runtime (yfinance 1.2.0 + pandas 2.3.3, tested)
- Dockerfile — optional docker path (python:3.12-slim, data excluded by default)
- .dockerignore — keeps 688MB app/data/ out of docker context
- deploy/wildbill.service — systemd unit (www-data, hardens, port 8910)
- deploy/wildbill-refresh.service + .timer — monthly constituent and new-symbol refresh
- deploy/nginx-charts.conf — subdomain vhost (Option A) + /charts/ alt (Option B)
- deploy/deploy.sh — audit (default) + --apply installer
- scripts/audit_droplet.sh — read-only preflight (run first)

Recommended: systemd+venv (simpler, matches server.py stdlib design).
Docker is provided as an alternative, not the default.

## 0. What I need from you (paste into chat)
1. SSH: `root@IP` (or user@IP), key auth, `~/.ssh/config` Host `wildbill`
2. OS + size: e.g. Ubuntu 22.04, 1vCPU/2GB, 50GB (X GB free)
3. Existing stack: nginx+WP / Node:port / docker / static + domain
   + output of `bash /tmp/audit_droplet.sh` (copy audit_droplet.sh there first)
4. Decision: full 688MB app/data/ vs DOW30-only ~36MB; systemd+venv vs docker

## 1. Preflight (read-only, safe next to existing site)
scp scripts/audit_droplet.sh wildbill:/tmp/ && ssh wildbill "bash /tmp/audit_droplet.sh"
Expect: 8910 FREE, nginx present, enough disk (2GB free for full, 500MB for dow30).

Verify SSH base facts too:
ssh wildbill "cat /etc/os-release; nginx -v; docker ps 2>&1 | head -3"

## 2. Install (on droplet as root)
## 3. TLS (after DNS points subdomain at droplet IP)
certbot --nginx -d charts.example.com && systemctl reload nginx

## 4. Verify (existing site must still pass)
curl -fsS http://127.0.0.1:8910/api/health
curl -fsS "http://127.0.0.1:8910/api/delta?symbol=AAPL&since_daily=2099-01-01&since_5m=9999999999"
curl -s -o /dev/null -w "charts:%{http_code}\n" http://charts.example.com/
curl -s -o /dev/null -w "existing-site:%{http_code}\n" https://your-existing-domain/
nginx -T | grep -E "server_name|proxy_pass" | head -20

## 5. Rollback (if anything looks wrong — restores prior state)
systemctl stop wildbill; systemctl disable wildbill
rm /etc/nginx/sites-enabled/wildbill-charts /etc/nginx/sites-available/wildbill-charts /etc/systemd/system/wildbill.service
systemctl daemon-reload && nginx -t && systemctl reload nginx
# Existing site never edited, so it keeps serving throughout.
# DOW30 default (light). Full history if disk allows:
CHARTS_DOMAIN=charts.example.com DATA_MODE=dow30 bash deploy/deploy.sh --apply
# or: DATA_MODE=full CHARTS_DOMAIN=charts.example.com bash deploy/deploy.sh --apply
# Script does: clone /opt/wildbill-charts, venv+pip, trim data (unless full),
# systemd enable+start, monthly refresh timer, curl /api/health, new nginx vhost,
# nginx -t && reload.

## 6. Monthly market-data refresh
The deploy script enables `wildbill-refresh.timer`, which runs on the first day
of each month at 03:00 server time, with up to a 15-minute randomized delay.
It runs `fetch_constituents.py` first, then refreshes existing daily history for
all known symbols with `fetch_market.py --refresh-existing --daily-only`, and
writes only under `/srv/wildbill-charts/app`.

Check or run it manually on the droplet:
```bash
systemctl list-timers wildbill-refresh.timer
systemctl status wildbill-refresh.timer
sudo systemctl start wildbill-refresh.service
journalctl -u wildbill-refresh.service -n 100 --no-pager
```

Before changing the timer to refresh the full archive, run a small daily-only
pilot. This refreshes up to five existing files and preserves their archived
intraday bars:
```bash
cd /srv/wildbill-charts
.venv/bin/python scripts/fetch_market.py --refresh-existing --daily-only --limit 5
```
Long runs can be resumed with `--start-after SYMBOL` if the process is
interrupted.

