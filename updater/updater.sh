#!/bin/sh
set -eu

STATE=/data/update-state.json
REQUEST=/data/update-request.json
PREVIOUS=/data/update-previous.txt
REPO_API=https://api.github.com/repos/adam1991tom/AT-Network-Dashboard

state() {
  status="$1"; shift
  message="$*"
  jq -n --arg status "$status" --arg message "$message" --arg ts "$(date -Iseconds)" '{status:$status,message:$message,updated_at:$ts}' > "$STATE.tmp"
  mv "$STATE.tmp" "$STATE"
}

state idle "Updater ready"

while true; do
  if [ ! -f "$REQUEST" ]; then
    sleep 2
    continue
  fi

  CHANNEL=$(jq -r '.channel // "stable"' "$REQUEST" 2>/dev/null || echo stable)
  TARGET=$(jq -r '.target // ""' "$REQUEST" 2>/dev/null || echo '')
  rm -f "$REQUEST"

  PREV=$(git -C /workspace rev-parse HEAD 2>/dev/null || true)
  [ -n "$PREV" ] && printf '%s\n' "$PREV" > "$PREVIOUS"

  state fetching "Fetching $CHANNEL update from GitHub"
  if ! git -C /workspace fetch --all --tags --prune; then
    state failed "Git fetch failed; installation left unchanged"
    continue
  fi

  if [ "$CHANNEL" = "stable" ]; then
    if [ -z "$TARGET" ] || [ "$TARGET" = "null" ]; then
      TARGET=$(curl -fsSL "$REPO_API/releases/latest" | jq -r '.tag_name // empty' || true)
    fi
    if [ -z "$TARGET" ]; then
      state failed "No stable release is currently published"
      continue
    fi
  else
    if [ -z "$TARGET" ] || [ "$TARGET" = "null" ]; then
      TARGET=$(git -C /workspace rev-parse origin/main)
    fi
  fi

  if ! git -C /workspace checkout -f main >/dev/null 2>&1; then
    git -C /workspace checkout -B main origin/main >/dev/null 2>&1 || true
  fi
  if ! git -C /workspace reset --hard "$TARGET"; then
    state failed "Could not switch source to requested update target"
    [ -n "$PREV" ] && git -C /workspace reset --hard "$PREV" >/dev/null 2>&1 || true
    continue
  fi

  state building "Building update; dashboard remains on the current container until build completes"
  if ! (cd /workspace && docker compose build at-network-dashboard); then
    state rollback "Build failed; restoring previous source"
    [ -n "$PREV" ] && git -C /workspace reset --hard "$PREV" >/dev/null 2>&1 || true
    state failed "Update build failed; previous version retained"
    continue
  fi

  state restarting "Restarting dashboard with the new build"
  if ! (cd /workspace && docker compose up -d --no-deps at-network-dashboard); then
    state rollback "Restart failed; rolling back"
    [ -n "$PREV" ] && git -C /workspace reset --hard "$PREV" >/dev/null 2>&1 || true
    (cd /workspace && docker compose up -d --build --no-deps at-network-dashboard) >/dev/null 2>&1 || true
    state failed "Restart failed; rollback attempted"
    continue
  fi

  sleep 15
  if curl -fsS --max-time 8 http://at-network-dashboard:3080/api/health >/dev/null 2>&1; then
    state complete "Update complete and health check passed"
  else
    state rollback "Health check failed; restoring previous version"
    if [ -n "$PREV" ]; then
      git -C /workspace reset --hard "$PREV" >/dev/null 2>&1 || true
      (cd /workspace && docker compose up -d --build --no-deps at-network-dashboard) >/dev/null 2>&1 || true
    fi
    state failed "New version failed health check; previous version restored"
  fi

done
