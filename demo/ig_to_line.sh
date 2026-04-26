#!/usr/bin/env bash
# Hackathon hack: when Brave's frontmost tab lands on an Instagram reel /
# post, paste the URL into the currently-focused LINE Desktop chat and send.
#
# Intended demo flow:
#   - Browse IG DM in Brave. New reel arrives in the thread.
#   - Click the reel → IG pushes the URL to instagram.com/reel/<shortcode>.
#   - Script picks it up on the next poll and sends to LINE.
#   - Close the reel (URL reverts to /direct/t/...) and wait for the next one.
#
# Setup (one-time):
#   - Grant Terminal "Accessibility" + "Automation" permissions on first run.
#
# Each run:
#   1. Open LINE Desktop, click the chat you want to send to, leave the cursor
#      in the message input box.
#   2. Open Brave with the IG DM thread as the frontmost tab.
#   3. bash demo/ig_to_line.sh
#
# Tweakables (env vars):
#   BROWSER_APP    "Brave Browser" (default). "Google Chrome", "Safari", etc.
#   POLL_INTERVAL  seconds between polls (default 2)
#   SEND_KEY       "return" (default) or "cmd_return" — match LINE's send-key.
#
# Stop with Ctrl+C.

set -euo pipefail

BROWSER_APP="${BROWSER_APP:-Brave Browser}"
POLL_INTERVAL="${POLL_INTERVAL:-2}"
SEND_KEY="${SEND_KEY:-return}"

get_active_tab_url() {
  if [[ "$BROWSER_APP" == "Safari" ]]; then
    osascript <<EOF 2>/dev/null || true
tell application "Safari"
  if (count of windows) = 0 then return ""
  try
    return URL of current tab of front window
  on error
    return ""
  end try
end tell
EOF
  else
    osascript <<EOF 2>/dev/null || true
tell application "$BROWSER_APP"
  if (count of windows) = 0 then return ""
  try
    return URL of active tab of front window
  on error
    return ""
  end try
end tell
EOF
  fi
}

is_instagram_post() {
  case "$1" in
    *instagram.com/reel/*|*instagram.com/reels/*|*instagram.com/p/*|*instagram.com/tv/*) return 0 ;;
    *) return 1 ;;
  esac
}

send_to_line() {
  local url="$1"
  printf '%s' "$url" | pbcopy
  if [[ "$SEND_KEY" == "cmd_return" ]]; then
    osascript <<'EOF'
tell application "LINE" to activate
delay 0.5
tell application "System Events"
  keystroke "v" using {command down}
  delay 0.25
  keystroke return using {command down}
end tell
EOF
  else
    osascript <<'EOF'
tell application "LINE" to activate
delay 0.5
tell application "System Events"
  keystroke "v" using {command down}
  delay 0.25
  key code 36
end tell
EOF
  fi
}

LAST_URL=""
SENT_URL=""

echo "[ig_to_line] watching $BROWSER_APP frontmost tab every ${POLL_INTERVAL}s. Ctrl+C to stop."
echo "[ig_to_line] click any new reel in the DM thread; URL will be forwarded to LINE."

while true; do
  url="$(get_active_tab_url || true)"
  url="$(printf '%s' "$url" | tr -d '\r\n')"

  if [[ -n "$url" ]] && is_instagram_post "$url"; then
    if [[ "$url" == "$LAST_URL" && "$url" != "$SENT_URL" ]]; then
      echo "[ig_to_line] sending: $url"
      send_to_line "$url"
      SENT_URL="$url"
    fi
  fi

  LAST_URL="$url"
  sleep "$POLL_INTERVAL"
done
