# shellcheck shell=bash
#
# scripts/lib/common.sh
# ---------------------------------------------------------------------------
# Helpers for compat-check-targets.sh. Source it; do not execute it.
#
#   fmt_dur SECONDS               "45s" / "3m07s"
#   fail_reason LOG               one-line root cause extracted from a step log
#   step LABEL LOG ARGS...        run `avocado ARGS...` appending to LOG
#   state_volume [DIR]            docker volume named in DIR/.avocado-state
#   avocado_light_reset           drop exited containers; keep volume, stamps, lock
#   avocado_full_reset TARGET     light reset, then volume/state/lock/prune
#   verify_clean [VOLUME]         assert no state/lock/volume left behind
#   docker_prune [LEVEL]          scoped (default) | images | all
#   sdk_image_exists RELEASE      docker manifest probe for avocadolinux/sdk
#   feed_targets REL CHAN         targets published in that feed (targets.json)
#   feed_boards REL CHAN TGT      boards = avocado-bsp-* in the target's -ext repo
#
# Environment (all optional):
#   PRUNE_LEVEL        scoped | images | all       (default: scoped)
#   CONFIRM_PRUNE_ALL  must be 1 for PRUNE_LEVEL=all — it nukes unrelated docker
#                      work on a shared box
#   AVOCADO_REPO_URL   feed base URL (default: https://repo.avocadolinux.org,
#                      avocado-cli's DEFAULT_REPO_URL)
# ---------------------------------------------------------------------------

AVOCADO_REPO_URL="${AVOCADO_REPO_URL:-https://repo.avocadolinux.org}"
PRUNE_LEVEL="${PRUNE_LEVEL:-scoped}"

# Format a duration in seconds as e.g. "45s" or "3m07s".
fmt_dur() {
  local s=$1
  if [ "$s" -ge 60 ]; then printf '%dm%02ds' $((s / 60)) $((s % 60)); else printf '%ds' "$s"; fi
}

# Extract a one-line failure reason from a step log: prefer a known root-cause
# fingerprint; fall back to the last generic error line. ANSI/noise stripped.
fail_reason() {
  local log="$1" r
  r="$(grep -aiE 'no match for argument|unable to find a match|failed to fetch|nothing provides|fatal error|cannot execute|could not open|error 255|undefined reference to|no space left|ext build .* failed|failed to compile|validation failed|file\(s\) not found|dependencies not satisfied' "$log" 2>/dev/null \
       | sed 's/\x1b\[[0-9;]*m//g' | grep -aviE '/etc/passwd|/etc/group|no target architecture specified' | head -1)"
  if [ -z "$r" ]; then
    r="$(grep -aE '\[ERROR\]|^Error:|error:|\*\*\* ' "$log" 2>/dev/null \
         | sed 's/\x1b\[[0-9;]*m//g' | grep -aviE '/etc/passwd|/etc/group|warning|no target architecture specified' | tail -1)"
  fi
  printf '%s' "$(printf '%s' "$r" | sed 's/^[[:space:]]*//' | cut -c1-200)"
}

# Run an avocado step; args after the log file are passed to avocado verbatim.
step() {
  local label="$1" log="$2"; shift 2
  echo "    → avocado $*"
  avocado "$@" >>"$log" 2>&1
  local rc=$?
  if [ "$rc" -eq 0 ]; then echo "      ✅ $label"; else echo "      ❌ $label (exit $rc)"; fi
  return $rc
}

# Docker volume name recorded in .avocado-state (JSON), or empty.
state_volume() {
  sed -n 's/.*"volume_name":[[:space:]]*"\([^"]*\)".*/\1/p' "${1:-.}/.avocado-state" 2>/dev/null | head -1
}

# Remove exited avocado run containers (never running ones).
_rm_exited_avocado_containers() {
  local ids
  ids="$(docker ps -aq -f status=exited -f name=avocado- 2>/dev/null)"
  [ -n "$ids" ] && docker rm $ids >/dev/null 2>&1
  return 0
}

# Light reset, run between install and build: drop leftover containers only.
# Do NOT touch stamps or the lock here — `build` gates on the install stamps
# (sdk/<arch>/install.stamp) and fails with "dependencies not satisfied"
# without them, and the volume holds the sysroots build consumes.
avocado_light_reset() {
  _rm_exited_avocado_containers
}

# Full reset: stamps + lock entries first (must run while the volume exists —
# --stamps rm -rf's inside the SDK container), then drop the volume, state
# file, lockfile and local build dir, then prune per PRUNE_LEVEL.
# Best-effort throughout; verify_clean is the gate.
avocado_full_reset() {
  local target="$1"
  avocado clean --skip-volumes --stamps --unlock -C avocado.yaml --target "$target" --no-tui >/dev/null 2>&1 || true
  _rm_exited_avocado_containers
  avocado clean -f --no-tui >/dev/null 2>&1 || true
  rm -f avocado.lock .avocado-state
  rm -rf .avocado
  docker_prune "$PRUNE_LEVEL"
}

# Assert the project dir is pristine. Pass the volume name captured BEFORE
# the reset (state_volume) so its removal can be checked too.
# Prints what is dirty; returns non-zero if anything is.
verify_clean() {
  local vol="${1:-}" bad=""
  [ -e .avocado-state ] && bad="$bad .avocado-state"
  [ -e avocado.lock ]   && bad="$bad avocado.lock"
  if [ -n "$vol" ] && docker volume inspect "$vol" >/dev/null 2>&1; then bad="$bad volume:$vol"; fi
  if [ -n "$bad" ]; then echo "    ⚠️  not clean:$bad" >&2; return 1; fi
  return 0
}

# scoped: exited avocado containers + volumes avocado itself considers
#         abandoned (avocado prune). Never `docker volume prune` — on a dev
#         box that deletes every other project's sysroot volume.
# images: also drop all unused images -> forces SDK re-pull (true cold start).
# all:    docker system prune -af --volumes. Guarded.
docker_prune() {
  case "${1:-scoped}" in
    scoped)
      _rm_exited_avocado_containers
      avocado prune >/dev/null 2>&1 || true ;;
    images)
      _rm_exited_avocado_containers
      avocado prune >/dev/null 2>&1 || true
      docker image prune -af >/dev/null 2>&1 || true ;;
    all)
      if [ "${CONFIRM_PRUNE_ALL:-0}" != "1" ]; then
        echo "PRUNE_LEVEL=all needs CONFIRM_PRUNE_ALL=1 (it removes unrelated docker work)" >&2
        return 1
      fi
      docker system prune -af --volumes >/dev/null 2>&1 || true ;;
    *) echo "unknown PRUNE_LEVEL '$1'" >&2; return 1 ;;
  esac
}

# The SDK image is tagged by release only (sdk:2024, sdk:2026 — there is no
# sdk:2024-next); channel affects the feed path, not the image.
sdk_image_exists() {
  docker manifest inspect "docker.io/avocadolinux/sdk:$1" >/dev/null 2>&1
}

# Board targets published in RELEASE/CHANNEL, one per line, from the feed's
# targets.json — the source of truth (the CLI deliberately refuses to
# enumerate targets for supported_targets: '*'). Empty output = feed absent.
# ponytail: 2024/edge also lists tune/arch keys (cortexa53, x86_64_v2, noarch,
# qcm6490 SoC); they are filtered by NON_BOARD_RE. Boards never use '_'.
NON_BOARD_RE='_|^noarch$|^qcm[0-9]+$'
feed_targets() {
  curl -sf "$AVOCADO_REPO_URL/$1/$2/targets.json" 2>/dev/null \
    | jq -r 'keys[]' 2>/dev/null | grep -vE "$NON_BOARD_RE" | sort
}

# Boards published for TARGET in RELEASE/CHANNEL: the avocado-bsp-<board>
# packages in the target's -ext repo, one per line. With no board set the CLI
# resolves {{ avocado.target.board }} to the target itself, so when the -ext
# repo publishes no BSP at all we still emit the bare target — the cell then
# runs and its failure is caught rather than silently skipped.
feed_boards() {
  local release="$1" channel="$2" target="$3" base primary out
  base="$AVOCADO_REPO_URL/$release/$channel/target/$target-ext"
  primary="$(curl -sf "$base/repodata/repomd.xml" 2>/dev/null \
             | grep -o 'href="[^"]*primary.xml[^"]*"' | head -1 | cut -d'"' -f2)"
  out="$( [ -n "$primary" ] && curl -sf "$base/$primary" 2>/dev/null | gunzip -c 2>/dev/null \
          | grep -oE '<name>avocado-bsp-[^<]+</name>' | sed 's/<name>avocado-bsp-//;s/<\/name>//' | sort -u )"
  if [ -n "$out" ]; then printf '%s\n' "$out"; else printf '%s\n' "$target"; fi
}
