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
# watched while the run is in flight (see REPORT_FILE below). The report records
# per-step install/build durations and, for each failure, the extracted reason.
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
#                resolution from avocado.yaml)
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
declare -a ST_TARGET ST_INSTALL ST_BUILD ST_RESULT ST_NOTE ST_INSTALL_T ST_BUILD_T ST_REASON
for ((i = 0; i < COUNT; i++)); do
  ST_TARGET[$i]="—"; ST_INSTALL[$i]="…"; ST_BUILD[$i]="…"
  ST_RESULT[$i]="pending"; ST_NOTE[$i]=""
  ST_INSTALL_T[$i]=""; ST_BUILD_T[$i]=""; ST_REASON[$i]=""
done
STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S %Z')"
SWEEP_T0=$SECONDS

# Format a duration in seconds as e.g. "45s" or "3m07s".
fmt_dur() {
  local s=$1
  if [ "$s" -ge 60 ]; then printf '%dm%02ds' $((s / 60)) $((s % 60)); else printf '%ds' "$s"; fi
}

# Extract a one-line failure reason from a step log: prefer a known root-cause
# fingerprint; fall back to the last generic error line. ANSI/noise stripped.
fail_reason() {
  local log="$1" r
  r="$(grep -aiE 'no match for argument|unable to find a match|failed to fetch|nothing provides|fatal error|cannot execute|could not open|error 255|undefined reference to|no space left|ext build .* failed|failed to compile' "$log" 2>/dev/null \
       | sed 's/\x1b\[[0-9;]*m//g' | grep -aviE '/etc/passwd|/etc/group|no target architecture specified' | head -1)"
  if [ -z "$r" ]; then
    r="$(grep -aE '\[ERROR\]|^Error:|error:|\*\*\* ' "$log" 2>/dev/null \
         | sed 's/\x1b\[[0-9;]*m//g' | grep -aviE '/etc/passwd|/etc/group|warning|no target architecture specified' | tail -1)"
  fi
  printf '%s' "$(printf '%s' "$r" | sed 's/^[[:space:]]*//' | cut -c1-200)"
}

# Rewrite the markdown report from current state (atomic: write tmp then mv).
render_report() {
  local now i pass=0 fail=0 pend=0 ic bc res
  now="$(date '+%Y-%m-%d %H:%M:%S %Z')"
  {
    echo "# Avocado References — Build Check"
    echo
    echo "- **Started:** ${STARTED_AT}"
    echo "- **Updated:** ${now}  _(rewritten after each step while the run is live)_"
    echo "- **Elapsed:** $(fmt_dur $((SECONDS - SWEEP_T0)))"
    echo "- **CLI:** \`${AVOCADO_VERSION}\` · execution channel: bash"
    echo "- **Logs:** \`${LOG_DIR}\`"
    echo
    echo "Legend: ✅ pass · ❌ fail · ⏳ in progress · … pending · – skipped"
    echo
    echo "| # | Reference | Target | install | build | Result |"
    echo "|--:|-----------|--------|:-------:|:-----:|--------|"
    for ((i = 0; i < COUNT; i++)); do
      ic="${ST_INSTALL[$i]}"; [ -n "${ST_INSTALL_T[$i]}" ] && ic="${ic} ${ST_INSTALL_T[$i]}"
      bc="${ST_BUILD[$i]}";   [ -n "${ST_BUILD_T[$i]}" ]   && bc="${bc} ${ST_BUILD_T[$i]}"
      res="${ST_RESULT[$i]}"
      [ -n "${ST_NOTE[$i]}" ] && res="${res} — ${ST_NOTE[$i]}"
      printf '| %d | %s | %s | %s | %s | %s |\n' \
        "$((i + 1))" "${REFS[$i]%/}" "${ST_TARGET[$i]}" "$ic" "$bc" "$res"
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
    if [ "$fail" -gt 0 ]; then
      echo
      echo "## Failures"
      echo
      for ((i = 0; i < COUNT; i++)); do
        case "${ST_RESULT[$i]}" in
          FAIL*)
            printf -- '- **%s** (`%s`) — %s' "${REFS[$i]%/}" "${ST_TARGET[$i]}" "${ST_RESULT[$i]}"
            [ -n "${ST_REASON[$i]}" ] && printf ': `%s`' "${ST_REASON[$i]}"
            echo
            ;;
        esac
      done
    fi
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
  local dt st
  # default_target, if concrete
  dt="$(sed -n 's/^default_target:[[:space:]]*//p' avocado.yaml | tr -d '"' | head -1)"
  if [ -n "$dt" ] && [ "$dt" != "*" ]; then printf '%s' "$dt"; return; fi
  # First concrete supported_targets entry — handles both block (`- x`) and
  # flow (`[a, b]`) YAML sequences.
  st="$(awk '
    /^supported_targets:.*\[/ { l=$0; sub(/.*\[/,"",l); sub(/\].*/,"",l); gsub(/[,"]/," ",l); print l; exit }
    /^supported_targets:/     { blk=1; next }
    blk && /^[[:space:]]*-/   { sub(/^[[:space:]]*-[[:space:]]*/,""); gsub(/"/,""); print; exit }
    blk && /^[^[:space:]-]/   { exit }
  ' avocado.yaml | tr ' ' '\n' | tr -d '"' | grep -vE '^\*?$' | head -1)"
  if [ -n "$st" ]; then printf '%s' "$st"; return; fi
  echo "    ⚠️  no concrete target for ${ref:-$(basename "$PWD")}; defaulting to qemuarm64" >&2
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
  local ref="$1" log="$2" target="$3"
  echo "    -- teardown --"
  avocado connect clean               >>"$log" 2>&1 || true
  avocado clean -f                    >>"$log" 2>&1 || true
  avocado unlock --no-tui -t "$target" >>"$log" 2>&1 || true
  rm -f avocado.lock
  # -X (ignored-only): strip gitignored build state but never touch untracked
  # WIP files. Anything untracked-and-not-ignored is surfaced by the residual
  # check below instead of being silently deleted.
  git -C "$REPO_ROOT" clean -fdX -- "$ref" >>"$log" 2>&1 || true
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

  status="PASS"; failed_step=""; t0=0

  avocado clean -f                     >>"$log" 2>&1 || true
  avocado unlock --no-tui -t "$target" >>"$log" 2>&1 || true

  t0=$SECONDS
  if step "install" "$log" --target "$target" install -f --no-tui; then
    ST_INSTALL[$i]="✅"; ST_INSTALL_T[$i]="$(fmt_dur $((SECONDS - t0)))"; ST_BUILD[$i]="⏳"; render_report
    t0=$SECONDS
    if step "build" "$log" --target "$target" build --no-tui; then
      ST_BUILD[$i]="✅"; ST_BUILD_T[$i]="$(fmt_dur $((SECONDS - t0)))"
    else
      ST_BUILD[$i]="❌"; ST_BUILD_T[$i]="$(fmt_dur $((SECONDS - t0)))"; status="FAIL"; failed_step="build"
      ST_REASON[$i]="$(fail_reason "$log")"
    fi
  else
    ST_INSTALL[$i]="❌"; ST_INSTALL_T[$i]="$(fmt_dur $((SECONDS - t0)))"; ST_BUILD[$i]="–"; status="FAIL"; failed_step="install"
    ST_REASON[$i]="$(fail_reason "$log")"
  fi
  render_report

  teardown "$ref" "$log" "$target"
  cd "$REPO_ROOT"

  # Verify the working tree for this ref is clean apart from the avocado.yaml edit.
  dirty="$(git status --porcelain -- "$ref" | grep -vE '^[ M][ M] .*/avocado.yaml$' || true)"
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
    PASS*) pass=$((pass + 1)); printf 'PASS  %s (%s) install=%s build=%s\n' \
             "${REFS[$i]%/}" "${ST_TARGET[$i]}" "${ST_INSTALL_T[$i]:-?}" "${ST_BUILD_T[$i]:-?}";;
    FAIL*) fail=$((fail + 1)); printf 'FAIL  %s (%s) %s%s\n' \
             "${REFS[$i]%/}" "${ST_TARGET[$i]}" "${ST_RESULT[$i]}" "${ST_REASON[$i]:+ — ${ST_REASON[$i]}}";;
    *)     printf 'SKIP  %s\n' "${REFS[$i]%/}";;
  esac
done > "$LOG_DIR/summary.txt"
cat "$LOG_DIR/summary.txt"
echo
echo "PASS: $pass   FAIL: $fail   ·   total $(fmt_dur $((SECONDS - SWEEP_T0)))   (logs: $LOG_DIR)"
exit $overall_rc
