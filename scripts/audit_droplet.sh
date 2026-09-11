#!/bin/bash
# READ-ONLY droplet audit for wildbill-charts side-by-side check
# Does NOT change anything. Safe to run next to existing site.
set -u
echo "=== OS ==="; cat /etc/os-release 2>/dev/null | head -n 5; uname -r
echo; echo "=== RESOURCES ==="; free -h; echo; df -h / | tail -n 3; echo; nproc; uptime
echo; echo "=== PORTS (listeners) ==="; (ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null) | head -n 30
echo; echo "=== WEB SERVER ==="; (nginx -v 2>&1; apache2 -v 2>&1 | head -n 1; caddy version 2>&1 | head -n 1) | head
echo "-- nginx sites --"; ls -l /etc/nginx/sites-enabled/ 2>/dev/null; cat /etc/nginx/sites-enabled/* 2>/dev/null | grep -E "server_name|listen|root|proxy_pass" | head -n 40
echo "-- apache sites --"; ls -l /etc/apache2/sites-enabled/ 2>/dev/null
echo; echo "=== DOCKER? ==="; docker ps 2>&1 | head -n 20; docker --version 2>&1
echo; echo "=== PYTHON ==="; python3 --version 2>&1; python3 -c "import yfinance" 2>&1 | head -n 2
echo; echo "=== SYSTEMD wildbill? ==="; systemctl status wildbill* 2>&1 | head -n 10
echo; echo "=== PORT 8910 FREE? ==="; (ss -tln 2>/dev/null | grep -q ":8910" && echo "8910 TAKEN" || echo "8910 FREE")
echo; echo "=== DISK for 688MB data? ==="; du -sh /opt 2>/dev/null; df -h /opt 2>/dev/null | tail -n 1
echo; echo "AUDIT DONE - no changes made"
