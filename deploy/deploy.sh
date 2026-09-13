#!/bin/bash
# deploy.sh — side-by-side install on droplet ALREADY hosting another site.
# SAFE: audit by default; --apply adds /srv checkout + venv + ONE systemd
# unit + ONE nginx vhost file, then `nginx -t && reload` (NEVER restart).
# Existing vhosts are never edited. Rollback = stop unit, delete 2 new
# files, reload. See README-DEPLOY.md for full steps + rollback.
# Usage on droplet as root:
#   bash deploy.sh                                      # AUDIT only
#   CHARTS_DOMAIN=charts.example.com bash deploy.sh --apply
#   DATA_MODE=full CHARTS_DOMAIN=charts.example.com bash deploy.sh --apply
set -u
REPO="${REPO:-https://github.com/abcgiga-droid/wildbill-charts.git}"
BRANCH="${BRANCH:-main}"
DEST="${DEST:-/srv/wildbill-charts}"
PORT="${PORT:-8910}"
CHARTS_DOMAIN="${CHARTS_DOMAIN:-charts.example.com}"
DATA_MODE="${DATA_MODE:-dow30}"
MODE="${1:-audit}"
say() { printf '%s\n' "$*"; }
if [ "$MODE" != "--apply" ]; then
  say "=== AUDIT (read-only, no changes) ==="
  say "OS:        $(cat /etc/os-release 2>/dev/null | grep -E '^PRETTY' || uname -s)"
  say "Disk:      $(df -h / | tail -1)"
  say "RAM:       $(free -h | head -2 | tail -1)"
  if command -v nginx >/dev/null 2>&1; then
    say "nginx:     $(nginx -v 2>&1)"
    say "vhosts:    $(ls /etc/nginx/sites-enabled/ 2>/dev/null | tr '\n' ' ')"
  else say "nginx:     NOT FOUND (apt install -y nginx first)"; fi
  if (ss -tln 2>/dev/null | grep -q ":$PORT ") ; then say "port $PORT:  TAKEN (!!)";
  else say "port $PORT:  FREE (good)"; fi
  if systemctl list-units --all 2>/dev/null | grep -q wildbill; then
    say "wildbill:  EXISTS"; else say "wildbill:  absent (good)"; fi
  say "dest:      $DEST ($([ -d "$DEST" ] && echo EXISTS || echo absent))"
  say "domain:    $CHARTS_DOMAIN (DNS must point here for TLS)"
  say "data:      $DATA_MODE (full=688MB/587 files, dow30=~36MB/30)"
  say ""
  say "Install: CHARTS_DOMAIN=$CHARTS_DOMAIN DATA_MODE=$DATA_MODE bash $0 --apply"
  say "AUDIT DONE - no changes made."
  exit 0
fi
say "=== APPLY: $DEST (domain $CHARTS_DOMAIN, data $DATA_MODE) ==="
set -e

test "$(id -u)" -eq 0 || { say "Run as root on the droplet."; exit 1; }
command -v nginx >/dev/null || { say "nginx missing: apt install -y nginx"; exit 1; }
if ss -tln 2>/dev/null | grep -q ":$PORT "; then say "Port $PORT TAKEN - abort."; exit 1; fi
say "[1/6] checkout $REPO@$BRANCH -> $DEST"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch origin
  git -C "$DEST" checkout "$BRANCH"
  git -C "$DEST" pull --ff-only origin "$BRANCH"
else git clone --branch "$BRANCH" --depth 1 "$REPO" "$DEST"; fi
say "[2/6] venv + pinned deps"
apt-get update -qq && apt-get install -y -qq git curl >/dev/null
command -v /usr/bin/python3.11 >/dev/null || { say "python3.11 missing: apt install -y python3.11 python3.11-venv"; exit 1; }
[ -x "$DEST/.venv/bin/python" ] || /usr/bin/python3.11 -m venv "$DEST/.venv"
"$DEST/.venv/bin/pip" install -q --upgrade pip
"$DEST/.venv/bin/pip" install -q -r "$DEST/requirements.txt"
say "[3/6] data ($DATA_MODE)"
if [ "$DATA_MODE" = "full" ]; then
  say "  full history in clone (688MB/587 files) - nothing to trim."
else
  KEEP="MMM GOOGL AXP AMGN AMZN AAPL BA CAT CVX CSCO KO DIS GS HD HON IBM JNJ JPM MCD MRK MSFT NKE NVDA PG CRM SHW TRV UNH V WMT"
  n=0
  for f in "$DEST"/app/data/*.json; do
    base="$(basename "$f" .json)"; keep_one=0
    for k in $KEEP; do [ "$base" = "$k" ] && keep_one=1; done
    if [ "$keep_one" -eq 0 ]; then rm -f "$f"; n=$((n+1)); fi
  done
  say "  removed $n non-DOW30 files; kept $(ls "$DEST"/app/data | wc -l) files ($(du -sh "$DEST"/app/data | cut -f1))"
fi
chown -R hamid:www-data "$DEST"
say "[4/6] systemd unit (new file only)"
sed -e "s#WorkingDirectory=.*#WorkingDirectory=$DEST#" \
    -e "s#ExecStart=.*#ExecStart=$DEST/.venv/bin/python server/server.py --port $PORT#" \
    -e "s#^User=.*#User=hamid#" \
    "$DEST/deploy/wildbill.service" > /etc/systemd/system/wildbill.service
  sed "s#/srv/wildbill-charts#$DEST#g" \
    "$DEST/deploy/wildbill-refresh.service" > /etc/systemd/system/wildbill-refresh.service
  cp "$DEST/deploy/wildbill-refresh.timer" /etc/systemd/system/wildbill-refresh.timer
systemctl daemon-reload
systemctl enable --now wildbill
  systemctl enable --now wildbill-refresh.timer
sleep 2
curl -fsS "http://127.0.0.1:$PORT/api/health" | head -c 300; echo
systemctl is-active wildbill | grep -q active || { say "wildbill failed - journalctl -u wildbill"; exit 1; }
say "[5/6] nginx vhost (new file only, existing vhosts untouched)"
sed "s/charts.example.com/$CHARTS_DOMAIN/g; s#http://127.0.0.1:8910#http://127.0.0.1:$PORT#g" \
  "$DEST/deploy/nginx-charts.conf" > /etc/nginx/sites-available/wildbill-charts
ln -sf /etc/nginx/sites-available/wildbill-charts /etc/nginx/sites-enabled/wildbill-charts
nginx -t && systemctl reload nginx
say "  live (http): http://$CHARTS_DOMAIN/ - TLS after DNS: certbot --nginx -d $CHARTS_DOMAIN"
say "[6/6] verify"
curl -fsS "http://127.0.0.1:$PORT/api/health" | head -c 300; echo
nginx -T 2>/dev/null | grep -E "$CHARTS_DOMAIN|proxy_pass http://127.0.0.1:$PORT" | head -5
say ""
say "DEPLOY OK. Rollback:"
say "  systemctl stop wildbill; systemctl disable wildbill"
say "  systemctl disable --now wildbill-refresh.timer"
say "  rm /etc/nginx/sites-enabled/wildbill-charts /etc/nginx/sites-available/wildbill-charts /etc/systemd/system/wildbill.service /etc/systemd/system/wildbill-refresh.service /etc/systemd/system/wildbill-refresh.timer"
say "  systemctl daemon-reload && nginx -t && systemctl reload nginx"