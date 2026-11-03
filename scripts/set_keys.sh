#!/usr/bin/env bash
# Pune cheile în .env, pe rând. Ce lipești la secrete nu apare pe ecran.
# Rulare, din folderul botului:  bash scripts/set_keys.sh
# Enter gol = sari peste cheia respectivă (o adaugi mai târziu, rulând din nou scriptul).
set -euo pipefail
cd "$(dirname "$0")/.."
ENV_FILE=".env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

get() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true; }

put() {
  local name="$1" value="$2" tmp
  tmp="$(mktemp)"
  grep -v -E "^$name=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$name" "$value" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

default() { [ -n "$(get "$1")" ] || put "$1" "$2"; }

ask() {
  local name="$1" label="$2" hidden="$3" value="" answer=""
  if [ -n "$(get "$name")" ]; then
    printf '%s e deja salvată. O schimbi? (d/N) ' "$label"
    read -r answer
    case "$answer" in d|D|da|DA|Da) ;; *) return 0 ;; esac
  fi
  if [ "$hidden" = "da" ]; then
    printf '%s (lipește și apasă Enter; nu se vede pe ecran): ' "$label"
    read -r -s value
    echo
  else
    printf '%s: ' "$label"
    read -r value
  fi
  value="$(printf '%s' "$value" | tr -d '[:space:]')"
  if [ -z "$value" ]; then
    echo "  sărit"
    return 0
  fi
  put "$name" "$value"
  echo "  salvat"
}

echo "Cheile botului. Se salvează doar în .env, pe Mac-ul tău (nu ajung pe GitHub)."
echo

ask ALPACA_API_KEY     "Alpaca Key ID (contul paper TRADING, începe cu PK)" nu
ask ALPACA_SECRET_KEY  "Alpaca Secret Key" da
ask FINNHUB_API_KEY    "Finnhub API key" da
ask GEMINI_API_KEY     "Gemini API key (proiectul nou theo-trading-bot)" da
ask TELEGRAM_BOT_TOKEN "Telegram bot token (de la @BotFather)" da
ask DASHBOARD_PASSWORD "Parola pentru dashboard (fără spații)" da
ask GH_DISPATCH_TOKEN  "GitHub token pentru dashboard (abia la etapa 8)" da

default ALPACA_PAPER true
default TRADING_MODE PAPER
default BOT_CAPITAL 500

key_id="$(get ALPACA_API_KEY)"
if [ -n "$key_id" ] && [ "${key_id#PK}" = "$key_id" ]; then
  echo
  echo "Atenție: Key ID-ul Alpaca nu începe cu PK. Cheile de paper încep cu PK; verifică să fii pe contul TRADING."
fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git ls-files --error-unmatch "$ENV_FILE" >/dev/null 2>&1; then
  echo
  echo "PROBLEMĂ: .env e urmărit de git. Spune-i agentului să-l scoată din git înainte de orice push."
fi

echo
echo "Stare:"
for name in ALPACA_API_KEY ALPACA_SECRET_KEY FINNHUB_API_KEY GEMINI_API_KEY TELEGRAM_BOT_TOKEN DASHBOARD_PASSWORD GH_DISPATCH_TOKEN; do
  if [ -n "$(get "$name")" ]; then echo "  ✓ $name"; else echo "  · $name (lipsește)"; fi
done
echo "  BOT_CAPITAL=$(get BOT_CAPITAL), TRADING_MODE=$(get TRADING_MODE)"
