# Python slim + pinned runtime for /api/* (yfinance+pandas). Static files are
# served by server/server.py itself (stdlib ThreadingHTTPServer); nginx in
# front only proxies + caches. No build step, no node.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/wildbill

# Copy pinned deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code (data layer excluded via .dockerignore by default;
# mount it explicitly if you want full 688MB history inside the container).
COPY app/ ./app/
COPY server/ ./server/

EXPOSE 8910
CMD ["python", "server/server.py", "--port", "8910"]
