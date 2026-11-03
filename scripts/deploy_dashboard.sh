#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DASH_DIR="$ROOT_DIR/dashboard"
ENV_FILE="$ROOT_DIR/.env"

if ! vercel whoami >/dev/null 2>&1; then
  echo "=== Autentificare Vercel (se deschide browserul) ==="
  vercel login
fi

cd "$DASH_DIR"

echo "=== Conectare la proiectul Vercel nou: theo-trading-bot ==="
vercel link --yes --project theo-trading-bot

if [ -f "$ENV_FILE" ]; then
  echo "=== Setare variabile din .env în Vercel (fără afișare în terminal) ==="
  for VAR_NAME in DASHBOARD_PASSWORD GH_DISPATCH_TOKEN; do
    VAL="$(grep -E "^${VAR_NAME}=" "$ENV_FILE" | head -n 1 | cut -d= -f2- || true)"
    if [ -n "$VAL" ]; then
      for ENV_TARGET in production preview development; do
        printf "%s" "$VAL" | vercel env add "$VAR_NAME" "$ENV_TARGET" --force >/dev/null 2>&1 || true
      done
      echo "  ✓ $VAR_NAME setat în Vercel"
    fi
  done
fi

echo "=== Deploy în producție pe Vercel ==="
vercel --prod --yes
