#!/bin/bash
# check_nfs_mounts - Nagios NRPE plugin
#
# Compares NFS mounts across three sources:
#   1. /etc/fstab              (what SHOULD be mounted)
#   2. /proc/mounts            (what IS mounted)
#   3. nrpe.cfg check_disk -p  (what is being MONITORED)
#
# Reports mismatches as WARNING or CRITICAL per Nagios plugin API.

readonly OK=0
readonly WARNING=1
readonly CRITICAL=2
readonly UNKNOWN=3

NRPE_CFG="/etc/nagios/nrpe.cfg"
NRPE_D_DIR="/etc/nagios/nrpe.d"
FSTAB="/etc/fstab"
PROC_MOUNTS="/proc/mounts"
VERBOSE=0

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Nagios NRPE plugin that compares NFS mounts across /etc/fstab,
nrpe.cfg check_disk commands, and active /proc/mounts entries.

OPTIONS:
  -c FILE   Path to nrpe.cfg          (default: /etc/nagios/nrpe.cfg)
  -d DIR    Path to nrpe.d directory  (default: /etc/nagios/nrpe.d)
  -f FILE   Path to fstab             (default: /etc/fstab)
  -v        Verbose: also list OK mounts
  -h        Show this help

EXIT CODES:
  0 OK       All NFS mounts consistent across fstab, active, and nrpe
  1 WARNING  Mount exists in some sources but not all (monitoring gap or
             ephemeral mount)
  2 CRITICAL A configured mount is not active, or nrpe monitors a
             non-existent mount
  3 UNKNOWN  Cannot read a required file

SEVERITY LOGIC:
  CRITICAL  fstab entry not mounted (non-noauto)
  CRITICAL  fstab + nrpe check_disk entry but mount is not active
  CRITICAL  nrpe check_disk entry with no fstab entry and not mounted
  WARNING   fstab(noauto) entry not mounted and not in nrpe
  WARNING   Mounted per fstab but no nrpe check_disk entry
  WARNING   Mounted ad-hoc (not in fstab) and not in nrpe
  WARNING   Mounted and in nrpe but missing from fstab (won't survive reboot)
EOF
}

while getopts "c:d:f:vh" opt; do
    case $opt in
        c) NRPE_CFG="$OPTARG" ;;
        d) NRPE_D_DIR="$OPTARG" ;;
        f) FSTAB="$OPTARG" ;;
        v) VERBOSE=1 ;;
        h) usage; exit $OK ;;
        ?) usage >&2; exit $UNKNOWN ;;
    esac
done

# ---------------------------------------------------------------------------
# Gather NFS entries from fstab
# ---------------------------------------------------------------------------
declare -A fstab_mounts   # [mountpoint]="device"
declare -A fstab_noauto   # [mountpoint]=1 when options include noauto

if [[ ! -r "$FSTAB" ]]; then
    echo "UNKNOWN: Cannot read $FSTAB"
    exit $UNKNOWN
fi

while IFS= read -r line; do
    line="${line%%#*}"   # strip inline comments
    read -r device mountpoint fstype options _ <<< "$line"
    [[ -z "$device" || -z "$mountpoint" ]] && continue
    if [[ "$fstype" == "nfs" || "$fstype" == "nfs4" ]]; then
        fstab_mounts["$mountpoint"]="$device"
        [[ "$options" == *noauto* ]] && fstab_noauto["$mountpoint"]=1
    fi
done < "$FSTAB"

# ---------------------------------------------------------------------------
# Gather active NFS mounts from /proc/mounts
# ---------------------------------------------------------------------------
declare -A active_mounts  # [mountpoint]="device"

if [[ ! -r "$PROC_MOUNTS" ]]; then
    echo "UNKNOWN: Cannot read $PROC_MOUNTS"
    exit $UNKNOWN
fi

while read -r device mountpoint fstype _rest; do
    if [[ "$fstype" == "nfs" || "$fstype" == "nfs4" ]]; then
        active_mounts["$mountpoint"]="$device"
    fi
done < "$PROC_MOUNTS"

# ---------------------------------------------------------------------------
# Gather check_disk -p paths from nrpe.cfg and nrpe.d/*.cfg
# ---------------------------------------------------------------------------
declare -A nrpe_paths     # [mountpoint]="command_name"

parse_nrpe_file() {
    local file="$1"
    [[ -r "$file" ]] || return

    while IFS= read -r line; do
        line="${line%%#*}"           # strip inline comments
        [[ -z "${line// }" ]] && continue

        # Match: command[name]=.../check_disk ...
        [[ "$line" =~ ^[[:space:]]*command\[([^]]+)\][[:space:]]*= ]] || continue
        local cmd_name="${BASH_REMATCH[1]}"
        local cmd_rhs="${line#*=}"
        [[ "$cmd_rhs" == *check_disk* ]] || continue

        # Tokenize the command RHS and extract every -p <path> argument.
        # Handles both "-p /path" (with space) and "-p/path" (no space).
        local -a tokens
        read -ra tokens <<< "$cmd_rhs"
        local i
        for (( i = 0; i < ${#tokens[@]}; i++ )); do
            local tok="${tokens[$i]}"
            if [[ "$tok" == "-p" ]]; then
                local path="${tokens[$((i+1))]}"
                [[ -n "$path" && "$path" == /* ]] && nrpe_paths["$path"]="$cmd_name"
            elif [[ "$tok" == -p/* ]]; then
                nrpe_paths["${tok:2}"]="$cmd_name"
            fi
        done
    done < "$file"
}

# Parse main cfg (optional — may not exist if only nrpe.d is used)
[[ -f "$NRPE_CFG" ]] && parse_nrpe_file "$NRPE_CFG"

# Parse drop-in directory
if [[ -d "$NRPE_D_DIR" ]]; then
    for f in "$NRPE_D_DIR"/*.cfg; do
        [[ -f "$f" ]] && parse_nrpe_file "$f"
    done
fi

# Warn if no nrpe config was found at all (non-fatal — report as warning)
nrpe_found=0
[[ -f "$NRPE_CFG" || -d "$NRPE_D_DIR" ]] && nrpe_found=1

# ---------------------------------------------------------------------------
# Build union of all mount points across the three sources
# ---------------------------------------------------------------------------
declare -A all_mounts
for mp in "${!fstab_mounts[@]}";  do all_mounts["$mp"]=1; done
for mp in "${!active_mounts[@]}"; do all_mounts["$mp"]=1; done
for mp in "${!nrpe_paths[@]}";    do all_mounts["$mp"]=1; done

if [[ ${#all_mounts[@]} -eq 0 ]]; then
    echo "OK: No NFS mounts found in fstab, active mounts, or nrpe check_disk | nfs_ok=0 nfs_warn=0 nfs_crit=0"
    exit $OK
fi

# ---------------------------------------------------------------------------
# Categorise each mount point based on which sources contain it
# ---------------------------------------------------------------------------
crits=()
warns=()
ok_mounts=()

for mp in $(printf '%s\n' "${!all_mounts[@]}" | sort); do
    in_fstab=0; is_mounted=0; in_nrpe=0
    [[ -v "fstab_mounts[$mp]" ]]  && in_fstab=1
    [[ -v "active_mounts[$mp]" ]] && is_mounted=1
    [[ -v "nrpe_paths[$mp]" ]]    && in_nrpe=1

    case "${in_fstab}${is_mounted}${in_nrpe}" in
        111)
            # Perfect: fstab + mounted + monitored
            ok_mounts+=("$mp")
            ;;
        100)
            # fstab only — not mounted, not monitored
            if [[ -v "fstab_noauto[$mp]" ]]; then
                warns+=("$mp: fstab(noauto) — not mounted, not in nrpe check_disk")
            else
                crits+=("$mp: fstab entry not mounted and not in nrpe check_disk")
            fi
            ;;
        010)
            # Mounted only — no fstab entry, not monitored
            warns+=("$mp: mounted ad-hoc (no fstab entry), not in nrpe check_disk")
            ;;
        001)
            # nrpe only — ghost entry: not in fstab, not mounted
            crits+=("$mp: nrpe check_disk entry [${nrpe_paths[$mp]}] — not in fstab and not mounted")
            ;;
        110)
            # fstab + mounted, not in nrpe — unmonitored
            warns+=("$mp: mounted per fstab but missing from nrpe check_disk")
            ;;
        101)
            # fstab + nrpe, not mounted — mount failure
            crits+=("$mp: fstab entry + nrpe check_disk [${nrpe_paths[$mp]}] but NOT mounted")
            ;;
        011)
            # Mounted + nrpe, not in fstab — won't survive reboot
            warns+=("$mp: mounted and in nrpe check_disk [${nrpe_paths[$mp]}] but missing from fstab")
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Determine exit code and emit Nagios-compatible output
# ---------------------------------------------------------------------------
exit_code=$OK
status="OK"

if [[ ${#crits[@]} -gt 0 ]]; then
    exit_code=$CRITICAL
    status="CRITICAL"
elif [[ ${#warns[@]} -gt 0 ]]; then
    exit_code=$WARNING
    status="WARNING"
fi

# Summary line (first line is what Nagios displays in the service status)
printf "NFS_MOUNTS %s: %d OK" "$status" "${#ok_mounts[@]}"
[[ ${#warns[@]} -gt 0 ]] && printf ", %d warning(s)" "${#warns[@]}"
[[ ${#crits[@]} -gt 0 ]] && printf ", %d critical(s)" "${#crits[@]}"
printf " | nfs_ok=%d nfs_warn=%d nfs_crit=%d nfs_fstab=%d nfs_active=%d nfs_nrpe=%d\n" \
    "${#ok_mounts[@]}" "${#warns[@]}" "${#crits[@]}" \
    "${#fstab_mounts[@]}" "${#active_mounts[@]}" "${#nrpe_paths[@]}"

# Detail lines (visible in Nagios long output / check output)
for msg in "${crits[@]}"; do echo "CRITICAL: $msg"; done
for msg in "${warns[@]}";  do echo "WARNING:  $msg"; done

if [[ $VERBOSE -eq 1 && ${#ok_mounts[@]} -gt 0 ]]; then
    for mp in "${ok_mounts[@]}"; do
        echo "OK:       $mp (${fstab_mounts[$mp]:-?} → nrpe:[${nrpe_paths[$mp]}])"
    done
fi

exit $exit_code
