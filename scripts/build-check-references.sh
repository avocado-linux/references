#!/usr/bin/env bash
#
# build-check-references.sh
# ---------------------------------------------------------------------------
# Reference-by-reference build verification for the Avocado OS references repo.
#
# For each reference (a top-level directory containing an avocado.yaml) it runs,
# in order:
#
#     avocado clean          # start from a clean slate
#     avocado unlock
#     avocado install -f
#     avocado build          # <- must succeed for the reference to PASS
#
# then tears the reference back down to a clean, commit-ready state:
#
#     avocado connect clean  # drop any Connect config (no-op if none)
#     avocado clean
#     avocado unlock
#     <remove build artifacts / non-committable files>
#
# After teardown the reference's git working tree contains only intended source
# changes (i.e. the avocado.yaml edits) -- no build output, no lockfile, no
# generated state.
#
# A live markdown report is (re)written after every step so progress can be
# watched while the run is in flight (see REPORT_FILE below).
#
# Usage:
#   scripts/build-check-references.sh [REF ...]   # given refs, or ALL if none
#
# Environment:
#   LOG_DIR      directory for per-reference logs (default: a fresh mktemp dir)
#   REPORT_FILE  markdown report path (default: $REPO_ROOT/scripts/build-report.md,
#                the tracked master report; override to write it elsewhere)
#   KEEP_GOING   1 = keep going after a reference fails (default); 0 = stop
#   TARGET       force a single target for every reference (default: per-ref
#                resolution via `avocado config show`)
# ---------------------------------------------------------------------------
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOG_DIR="${LOG_DIR:-$(mktemp -d -t avocado-refcheck-XXXXXX)}"
KEEP_GOING="${KEEP_GOING:-1}"
mkdir -p "$LOG_DIR"
REPORT_FILE="${REPORT_FILE:-$REPO_ROOT/scripts/build-report.md}"
AVOCADO_VERSION="$(avocado --version 2>/dev/null | head -1)"

# --- reference list ---------------------------------------------------------
if [ "$#" -gt 0 ]; then
  REFS=("$@")
else
  REFS=()
  for d in */; do
    [ -f "${d}avocado.yaml" ] && REFS+=("${d%/}")
  done
fi
COUNT=${#REFS[@]}

# --- live report state (parallel arrays; bash 3.2 compatible) ---------------
declare -a ST_TARGET ST_INSTALL ST_BUILD ST_RESULT ST_NOTE
for ((i = 0; i < COUNT; i++)); do
  ST_TARGET[$i]="—"; ST_INSTALL[$i]="…"; ST_BUILD[$i]="…"
  ST_RESULT[$i]="pending"; ST_NOTE[$i]=""
done
STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S %Z')"

# Rewrite the markdown report from current state (atomic: write tmp then mv).
render_report() {
  local now i pass=0 fail=0 pend=0
  now="$(date '+%Y-%m-%d %H:%M:%S %Z')"
  {
    echo "# Avocado References — Build Check"
    echo
    echo "- **Started:** ${STARTED_AT}"
    echo "- **Updated:** ${now}  _(rewritten after each step while the run is live)_"
    echo "- **CLI:** \`${AVOCADO_VERSION}\` · execution channel: bash"
    echo "- **Logs:** \`${LOG_DIR}\`"
    echo
    echo "Legend: ✅ pass · ❌ fail · ⏳ in progress · … pending · – skipped"
    echo
    echo "| # | Reference | Target | install | build | Result |"
    echo "|--:|-----------|--------|:-------:|:-----:|--------|"
    for ((i = 0; i < COUNT; i++)); do
      local res="${ST_RESULT[$i]}"
      [ -n "${ST_NOTE[$i]}" ] && res="${res} — ${ST_NOTE[$i]}"
      printf '| %d | %s | %s | %s | %s | %s |\n' \
        "$((i + 1))" "${REFS[$i]%/}" "${ST_TARGET[$i]}" \
        "${ST_INSTALL[$i]}" "${ST_BUILD[$i]}" "$res"
    done
    echo
    for ((i = 0; i < COUNT; i++)); do
      case "${ST_RESULT[$i]}" in
        PASS*) pass=$((pass + 1));;
        FAIL*) fail=$((fail + 1));;
        *)     pend=$((pend + 1));;
      esac
    done
    echo "**Totals:** ${pass} ✅ passed · ${fail} ❌ failed · ${pend} ⏳ pending — ${COUNT} total"
  } > "$REPORT_FILE.tmp" && mv "$REPORT_FILE.tmp" "$REPORT_FILE"
}

echo "==========================================================="
echo " Avocado references build check"
echo "   repo:    $REPO_ROOT"
echo "   logs:    $LOG_DIR"
echo "   report:  $REPORT_FILE"
echo "   count:   ${COUNT} reference(s)"
echo "==========================================================="
render_report

# --- helpers ----------------------------------------------------------------

# Resolve the target to build a reference for.
resolve_target() {
  if [ -n "${TARGET:-}" ]; then printf '%s' "$TARGET"; return; fi
  local out dt st
  out="$(avocado config show 2>/dev/null)"
  dt="$(printf '%s\n' "$out" | sed -n 's/^[[:space:]]*default_target:[[:space:]]*//p' | tr -d '"' | head -1)"
  if [ -n "$dt" ] && [ "$dt" != "*" ]; then printf '%s' "$dt"; return; fi
  st="$(printf '%s\n' "$out" | sed -n 's/.*supported_targets:[[:space:]]*\[\([^]]*\)\].*/\1/p' \
        | tr ',' '\n' | tr -d ' "' | grep -vE '^\*?$' | head -1)"
  if [ -n "$st" ]; then printf '%s' "$st"; return; fi
  printf 'qemuarm64'
}

# run a build step; args after the log file are passed to avocado verbatim.
step() {
  local label="$1" log="$2"; shift 2
  echo "    → avocado $*"
  avocado "$@" >>"$log" 2>&1
  local rc=$?
  if [ "$rc" -eq 0 ]; then echo "      ✅ $label"; else echo "      ❌ $label (exit $rc)"; fi
  return $rc
}

# Best-effort teardown; never aborts the run.
teardown() {
  local ref="$1" log="$2"
  echo "    -- teardown --"
  avocado connect clean          >>"$log" 2>&1 || true
  avocado clean -f               >>"$log" 2>&1 || true
  avocado unlock --no-tui        >>"$log" 2>&1 || true
  rm -f avocado.lock
  git -C "$REPO_ROOT" clean -fdx -- "$ref" >>"$log" 2>&1 || true
  # Restore any *tracked* generated files that `avocado clean` removed on disk
  # (e.g. docker-registry/.avocado-state) without disturbing the avocado.yaml edit.
  while IFS= read -r p; do
    [ -n "$p" ] && git -C "$REPO_ROOT" checkout -- "$p" 2>/dev/null || true
  done < <(git -C "$REPO_ROOT" ls-files --deleted -- "$ref" | grep -v '/avocado.yaml$')
  # Undo any in-place rewrite of avocado.yaml by a teardown step (connect clean).
  [ -f "$LOG_DIR/$ref.avocado.yaml.orig" ] && cp -p "$LOG_DIR/$ref.avocado.yaml.orig" avocado.yaml
}

# --- main loop --------------------------------------------------------------
overall_rc=0

for ((i = 0; i < COUNT; i++)); do
  ref="${REFS[$i]%/}"
  log="$LOG_DIR/$ref.log"
  : >"$log"
  echo
  echo "-----------------------------------------------------------"
  echo "[$ref]"

  if [ ! -f "$REPO_ROOT/$ref/avocado.yaml" ]; then
    echo "    ⚠️  no avocado.yaml -- skipping"
    ST_RESULT[$i]="– SKIP"; ST_INSTALL[$i]="–"; ST_BUILD[$i]="–"; ST_NOTE[$i]="no avocado.yaml"
    render_report
    continue
  fi

  cd "$REPO_ROOT/$ref"
  # Snapshot avocado.yaml: teardown's `avocado connect clean` rewrites it in
  # place (strips connect section / connect-config extension), so we restore
  # this exact copy afterwards to avoid leaking edits into a tracked file.
  cp -p avocado.yaml "$LOG_DIR/$ref.avocado.yaml.orig" 2>/dev/null || true
  target="$(resolve_target)"
  echo "    target: $target"
  ST_TARGET[$i]="$target"; ST_RESULT[$i]="⏳ running"; ST_INSTALL[$i]="⏳"
  render_report

  status="PASS"; failed_step=""

  avocado clean -f                     >>"$log" 2>&1 || true
  avocado unlock --no-tui -t "$target" >>"$log" 2>&1 || true

  if step "install" "$log" --target "$target" install -f --no-tui; then
    ST_INSTALL[$i]="✅"; ST_BUILD[$i]="⏳"; render_report
    if step "build" "$log" --target "$target" build --no-tui; then
      ST_BUILD[$i]="✅"
    else
      ST_BUILD[$i]="❌"; status="FAIL"; failed_step="build"
    fi
  else
    ST_INSTALL[$i]="❌"; ST_BUILD[$i]="–"; status="FAIL"; failed_step="install"
  fi
  render_report

  teardown "$ref" "$log"
  cd "$REPO_ROOT"

  # Verify the working tree for this ref is clean apart from the avocado.yaml edit.
  dirty="$(git status --porcelain -- "$ref" | grep -vE '^ M .*/avocado.yaml$' || true)"
  if [ -n "$dirty" ]; then
    echo "    ⚠️  residual git changes after teardown:"
    printf '%s\n' "$dirty" | sed 's/^/        /'
    ST_NOTE[$i]="⚠ residual git changes"
  fi

  if [ "$status" = "PASS" ]; then
    echo "    RESULT: ✅ PASS"
    ST_RESULT[$i]="PASS"
  else
    echo "    RESULT: ❌ FAIL @ $failed_step  (see $log)"
    ST_RESULT[$i]="FAIL @ $failed_step"
    overall_rc=1
  fi
  render_report

  [ "$status" = "FAIL" ] && [ "$KEEP_GOING" = "0" ] && { echo; echo "KEEP_GOING=0 -> stopping."; break; }
done

# --- summary ----------------------------------------------------------------
render_report
echo
echo "==========================================================="
echo " SUMMARY  (report: $REPORT_FILE)"
echo "==========================================================="
pass=0; fail=0
for ((i = 0; i < COUNT; i++)); do
  case "${ST_RESULT[$i]}" in
    PASS*) pass=$((pass + 1)); printf 'PASS  %s (%s)\n' "${REFS[$i]%/}" "${ST_TARGET[$i]}";;
    FAIL*) fail=$((fail + 1)); printf 'FAIL  %s (%s) %s\n' "${REFS[$i]%/}" "${ST_TARGET[$i]}" "${ST_RESULT[$i]}";;
    *)     printf 'SKIP  %s\n' "${REFS[$i]%/}";;
  esac
done | tee "$LOG_DIR/summary.txt"
echo
echo "PASS: $pass   FAIL: $fail   (logs: $LOG_DIR)"
exit $overall_rc
