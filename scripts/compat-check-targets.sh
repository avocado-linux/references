#!/usr/bin/env bash
#
# compat-check-targets.sh
# ---------------------------------------------------------------------------
# Target x release/channel compatibility sweep for the `dev` reference.
#
# For every (target, board) each feed publishes, in every release/channel
# combo, it copies dev/ to a scratch dir, rewrites the distro block, and runs:
#
#     avocado install -f      (fresh scratch dir — nothing to reset first)
#     light reset             (exited containers only; stamps/volume stay)
#     avocado build
#     full reset + verify     (volume/state/lock gone, or the cell is RESET-FAIL)
#
# Where the lists come from (all dynamic — nothing is hardcoded here):
#   targets  <repo>/<release>/<channel>/targets.json
#   boards   avocado-bsp-<board> packages in <repo>/<release>/<channel>/target/<target>-ext
#            (dev's BSP extension is avocado-bsp-{{ avocado.target.board }}; a
#            target with several boards — jetson-orin-nx: icam-540, mic-712-ox-16gb,
#            … — needs each board built; a target whose -ext repo has no BSP is
#            run once as itself so the failure is caught, not skipped)
#   docs     the support matrix (docs.peridio.com/hardware/support-matrix) is
#            what we SAY we support; the report lists the feed's published
#            target/boards per combo so the two can be compared.
#
# The tracked repo tree is never touched. Each cell writes ONE one-line result
# file to $LOG_DIR/cells/ and the markdown matrix report is re-rendered after
# every cell, so a multi-hour run is watchable — and CI legs can each run one
# cell and be aggregated by --report.
#
# Modes:
#   (default)   run the matrix, render report
#   --plan      preflight only: SDK image check + feed discovery. Prints the
#               runnable cells as "target board release channel" lines (CI
#               turns these into a matrix); nothing is built.
#   --report    render the report from whatever is in $LOG_DIR/cells
#
# Environment:
#   CELLS            explicit cells, "target board release channel" per line;
#                    skips feed discovery (this is how a CI leg runs ONE cell)
#   TARGETS          narrow discovery to these targets (all their boards)
#   COMBOS           space-separated release/channel (default: all four)
#   LOG_DIR          per-cell logs + cells/ result dir (default: mktemp)
#   REPORT_FILE      markdown report (default: scripts/compat-report.md)
#   SCRATCH_ROOT     where per-cell copies of dev/ live (default: .compat-scratch/,
#                    gitignored; must be a path the docker daemon can mount)
#   KEEP_GOING       1 = continue past failures (default); 0 = stop
#   PRUNE_LEVEL      scoped (default) | images | all   (see lib/common.sh)
#
# Exit status is 0 only when every cell passed. There is deliberately no
# skip-list: a published target that cannot install or build goes red every
# run until it is fixed. Red is the signal.
# ---------------------------------------------------------------------------
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/common.sh
. "$REPO_ROOT/scripts/lib/common.sh"

DEFAULT_COMBOS="2024/next 2024/edge 2026/next 2026/edge"

ONLY_TARGETS="${TARGETS:-}"
CELLS_OVERRIDE="${CELLS:-}"
COMBOS="${COMBOS:-$DEFAULT_COMBOS}"
LOG_DIR="${LOG_DIR:-$(mktemp -d -t avocado-compat-XXXXXX)}"
CELLS="$LOG_DIR/cells"
REPORT_FILE="${REPORT_FILE:-$REPO_ROOT/scripts/compat-report.md}"
SCRATCH_ROOT="${SCRATCH_ROOT:-$REPO_ROOT/.compat-scratch}"
KEEP_GOING="${KEEP_GOING:-1}"
MODE="${1:-run}"
mkdir -p "$CELLS"

SWEEP_T0=$SECONDS
AVOCADO_VERSION="$(avocado --version 2>/dev/null | head -1)"

# --- cell result files ------------------------------------------------------
# One file per cell, one '|'-separated line ('|' is stripped from reason; a
# tab delimiter would not do — tab is IFS whitespace and `read` collapses
# consecutive tabs, losing empty fields):
#   target|board|release|channel|install|install_t|build|build_t|reset_t|result|reason
cell_file() { printf '%s/%s__%s__%s-%s.cell' "$CELLS" "$1" "$2" "$3" "$4"; }

write_cell() { # target board release channel install install_t build build_t reset_t result reason
  local reason="${11//[$'\t\n|']/ }"
  printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
    "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "$reason" > "$(cell_file "$1" "$2" "$3" "$4")"
}

# "target" when the board is the target itself, else "target · board".
row_label() { if [ "$1" = "$2" ]; then printf '%s' "$1"; else printf '%s · %s' "$1" "$2"; fi; }

# --- report -----------------------------------------------------------------
# rc 0 iff every cell file is PASS.
all_passed() {
  local f res
  for f in "$CELLS"/*.cell; do
    [ -f "$f" ] || continue
    IFS='|' read -r _ _ _ _ _ _ _ _ _ res _ < "$f"
    [ "$res" = "PASS" ] || return 1
  done
  return 0
}

render_report() {
  local now t b combo r c ic it bc bt rt res cell f pass=0 fail=0 rfail=0 pend=0 reason
  now="$(date '+%Y-%m-%d %H:%M:%S %Z')"
  {
    echo "# Avocado References — Target Compatibility (\`dev\`)"
    echo
    echo "- **Reference:** \`dev/\` (\`supported_targets: '*'\`)"
    echo "- **Last run:** ${now}"
    echo "- **CLI:** \`${AVOCADO_VERSION}\`"
    echo
    echo "Legend: ✅ pass · ❌ fail · ⚠ reset failed · – not published in this feed (or not part of this run) · … pending"
    echo "Row: \`target\` or \`target · board\`. Cell: \`install / build\` with durations; reset time is tracked separately."
    echo
    # Columns are always the full combo set so the table shape never depends
    # on how a run was narrowed.
    printf '| Target · Board |'; for combo in $DEFAULT_COMBOS; do printf ' %s |' "$combo"; done; echo
    printf '|----------------|'; for combo in $DEFAULT_COMBOS; do printf ':---:|'; done; echo
    while read -r t b; do
      [ -n "$t" ] || continue
      printf '| %s |' "$(row_label "$t" "$b")"
      for combo in $DEFAULT_COMBOS; do
        r="${combo%/*}"; c="${combo#*/}"
        if [ -f "$(cell_file "$t" "$b" "$r" "$c")" ]; then
          IFS='|' read -r _ _ _ _ ic it bc bt rt res _ < "$(cell_file "$t" "$b" "$r" "$c")"
          case "$res" in
            RESET-FAIL) cell="⚠ reset" ;;
            *)          cell="$ic${it:+ $it} / $bc${bt:+ $bt}" ;;
          esac
        elif printf '%s\n' "${PLANNED:-}" | grep -qx "$t $b $r $c"; then
          cell="…"
        else
          cell="–"
        fi
        printf ' %s |' "$cell"
      done
      echo
    done <<< "$(all_rows)"
    echo
    for f in "$CELLS"/*.cell; do
      [ -f "$f" ] || continue
      IFS='|' read -r _ _ _ _ _ _ _ _ _ res _ < "$f"
      case "$res" in
        PASS)       pass=$((pass + 1)) ;;
        FAIL*)      fail=$((fail + 1)) ;;
        RESET-FAIL) rfail=$((rfail + 1)) ;;
        *)          pend=$((pend + 1)) ;;
      esac
    done
    echo "**Totals:** ${pass} ✅ passed · ${fail} ❌ failed · ${rfail} ⚠ reset-failed · ${pend} ⏳ pending/running"
    echo
    echo "## Published per feed"
    echo
    echo "What the feed actually ships (\`targets.json\`, boards from \`avocado-bsp-*\`). Compare against the [support matrix](https://docs.peridio.com/hardware/support-matrix) to catch anything we say we support but do not ship, or ship but do not list."
    echo
    for combo in $DEFAULT_COMBOS; do
      r="${combo%/*}"; c="${combo#*/}"
      printf -- '- **%s:** %s\n' "$combo" "$(printf '%s\n' "${PLANNED:-}" | awk -v r="$r" -v c="$c" '
        $3==r && $4==c { if ($1==$2) x=$1; else x=$1 "(" $2 ")"; printf "%s%s", (n++?", ":""), x }')"
    done
    if [ $((fail + rfail)) -gt 0 ]; then
      echo
      echo "## Failures"
      echo
      for f in "$CELLS"/*.cell; do
        [ -f "$f" ] || continue
        IFS='|' read -r t b r c _ _ _ _ rt res reason < "$f"
        case "$res" in
          FAIL*|RESET-FAIL)
            printf -- '- **%s** (%s/%s) — %s' "$(row_label "$t" "$b")" "$r" "$c" "$res"
            [ -n "$reason" ] && printf ': `%s`' "$reason"
            echo ;;
        esac
      done
    fi
  } > "$REPORT_FILE.tmp" && mv "$REPORT_FILE.tmp" "$REPORT_FILE"
}

# --- preflight --------------------------------------------------------------
# Runnable cells as "target board release channel", one per line. CELLS, if
# set, is used verbatim (no feed calls). Otherwise: targets.json per combo,
# then avocado-bsp-* per target (narrowed by TARGETS). A combo with no SDK
# image or no targets.json contributes nothing and is reported on stderr.
plan() {
  if [ -n "$CELLS_OVERRIDE" ]; then printf '%s\n' "$CELLS_OVERRIDE" | awk 'NF==4'; return; fi
  local combo r c t b list boards
  for combo in $COMBOS; do
    r="${combo%/*}"; c="${combo#*/}"
    if ! sdk_image_exists "$r"; then echo "    – sdk:$r image missing; skipping $combo" >&2; continue; fi
    # A fetch/parse error is NOT "nothing published": abort rather than run a
    # partial matrix that would go green.
    list="$(feed_targets "$r" "$c")" || { echo "    ❌ cannot determine targets for $combo — aborting" >&2; return 1; }
    if [ -z "$list" ]; then echo "    – no targets.json for $combo; skipping" >&2; continue; fi
    for t in $list; do
      if [ -n "$ONLY_TARGETS" ] && ! printf '%s\n' $ONLY_TARGETS | grep -qx "$t"; then continue; fi
      boards="$(feed_boards "$r" "$c" "$t")" || { echo "    ❌ cannot determine boards for $t @ $combo — aborting" >&2; return 1; }
      for b in $boards; do echo "$t $b $r $c"; done
    done
  done
}

# Report rows ("target board"): every pair seen in a planned cell or a result.
all_rows() {
  { printf '%s\n' "${PLANNED:-}" | awk 'NF==4 {print $1, $2}'
    for f in "$CELLS"/*.cell; do [ -f "$f" ] && awk -F'|' '{print $1, $2}' "$f"; done; } | grep . | sort -u
}

# --- one cell ---------------------------------------------------------------
run_cell() {
  local t="$1" b="$2" r="$3" c="$4" log scratch vol t0 rt=0 rt0
  local ic="⏳" it="" bc="…" bt="" res="RUNNING" reason=""
  log="$LOG_DIR/${t}__${b}__$r-$c.log"; : >"$log"
  echo
  echo "-----------------------------------------------------------"
  echo "[$(row_label "$t" "$b") @ $r/$c]"
  write_cell "$t" "$b" "$r" "$c" "$ic" "" "$bc" "" "" "$res" ""; render_report

  # Fresh scratch copy of dev/ with the distro block rewritten. The SDK image
  # template reads distro.release from the FILE, not the env, so env alone
  # would install the 2024 SDK against a 2026 feed. Belt and braces: both.
  # Under the repo, not $TMPDIR: the docker daemon (avocado-vm on macOS) can
  # only bind-mount paths it shares, and /var/folders/... is not one of them.
  mkdir -p "$SCRATCH_ROOT"
  scratch="$(mktemp -d "$SCRATCH_ROOT/${t}__${b}__$r-$c.XXXXXX")"
  cp -a "$REPO_ROOT/dev/." "$scratch"
  rm -rf "$scratch/.avocado" "$scratch/.avocado-state" "$scratch/avocado.lock"   # never inherit a local dev/ build
  sed -e "s/^\([[:space:]]*release:\).*/\1 $r/" -e "s/^\([[:space:]]*channel:\).*/\1 $c/" \
      "$scratch/avocado.yaml" > "$scratch/avocado.yaml.new" && mv "$scratch/avocado.yaml.new" "$scratch/avocado.yaml"
  export AVOCADO_DISTRO_RELEASE="$r" AVOCADO_DISTRO_CHANNEL="$c"
  cd "$scratch"
  if ! grep -qE "^[[:space:]]*release: $r$" avocado.yaml || ! grep -qE "^[[:space:]]*channel: $c$" avocado.yaml; then
    echo "    ❌ distro rewrite failed" | tee -a "$log"
    res="RESET-FAIL"; reason="distro rewrite failed"
  elif ! verify_clean "" 2>>"$log"; then
    res="RESET-FAIL"; reason="scratch dir not pristine"
  else
    # --target-board drives {{ avocado.target.board }} -> avocado-bsp-<board>.
    t0=$SECONDS
    if step "install" "$log" --target "$t" install -f --no-tui --target-board "$b"; then
      ic="✅"; it="$(fmt_dur $((SECONDS - t0)))"; bc="⏳"
      write_cell "$t" "$b" "$r" "$c" "$ic" "$it" "$bc" "" "" "$res" ""; render_report
      rt0=$SECONDS; avocado_light_reset; rt=$((rt + SECONDS - rt0))
      t0=$SECONDS
      if step "build" "$log" --target "$t" build --no-tui --target-board "$b"; then
        bc="✅"; bt="$(fmt_dur $((SECONDS - t0)))"; res="PASS"
      else
        bc="❌"; bt="$(fmt_dur $((SECONDS - t0)))"; res="FAIL @ build"; reason="$(fail_reason "$log")"
      fi
    else
      ic="❌"; it="$(fmt_dur $((SECONDS - t0)))"; bc="–"; res="FAIL @ install"; reason="$(fail_reason "$log")"
    fi
  fi

  # Full reset + gate. A dirty run scored PASS is worse than no run.
  echo "    -- reset --"
  vol="$(state_volume .)"
  rt0=$SECONDS; avocado_full_reset "$t"; rt=$((rt + SECONDS - rt0))
  if ! verify_clean "$vol" 2>>"$log"; then
    res="RESET-FAIL"; reason="${reason:+$reason; }leftover state after reset (see log)"
  fi
  unset AVOCADO_DISTRO_RELEASE AVOCADO_DISTRO_CHANNEL
  cd "$REPO_ROOT"; rm -rf "$scratch"

  write_cell "$t" "$b" "$r" "$c" "$ic" "$it" "$bc" "$bt" "$(fmt_dur $rt)" "$res" "$reason"
  render_report
  case "$res" in
    PASS) echo "    RESULT: ✅ PASS  (reset $(fmt_dur $rt))" ;;
    RESET-FAIL) echo "    RESULT: ⚠ RESET-FAIL  (see $log)" ;;
    *) echo "    RESULT: ❌ $res  (see $log)" ;;
  esac
  [ "$res" = "PASS" ]
}

# --- main -------------------------------------------------------------------
case "$MODE" in
  --plan)
    plan || { echo "preflight failed" >&2; exit 1; } ;;
  --report)
    PLANNED="$(plan 2>/dev/null)" || true   # report renders whatever cells exist
    render_report
    cat "$REPORT_FILE"
    all_passed ;;
  run|--run)
    echo "==========================================================="
    echo " Avocado dev-reference target compatibility sweep"
    echo "   logs:    $LOG_DIR"
    echo "   report:  $REPORT_FILE"
    echo "   combos:  $COMBOS"
    [ -n "$ONLY_TARGETS" ] && echo "   targets: $ONLY_TARGETS (narrowed)"
    echo "==========================================================="
    echo "-- preflight (sdk image + feed discovery) --"
    PLANNED="$(plan)" || { echo "preflight failed — not running a partial matrix" >&2; exit 1; }
    render_report
    echo "   cells: $(printf '%s\n' "$PLANNED" | grep -c . || true)"
    stop=0
    # Read the cell list on fd 3: avocado (docker) reads stdin and would eat
    # the remaining cells if the loop fed them on fd 0.
    while read -r -u 3 t b r c; do
      [ -n "$t" ] || continue
      if ! run_cell "$t" "$b" "$r" "$c" && [ "$KEEP_GOING" = "0" ]; then stop=1; break; fi
    done 3<<< "$PLANNED"
    [ "$stop" = "1" ] && echo "KEEP_GOING=0 -> stopping."
    render_report
    echo
    echo "==========================================================="
    echo " SUMMARY  (report: $REPORT_FILE · total $(fmt_dur $((SECONDS - SWEEP_T0))))"
    echo "==========================================================="
    if all_passed; then echo "OK: all cells passed"; else echo "FAIL: see report"; exit 1; fi ;;
  *)
    echo "usage: $0 [--plan | --report]" >&2; exit 2 ;;
esac
