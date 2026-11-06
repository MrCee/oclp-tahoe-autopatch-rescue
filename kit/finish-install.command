#!/bin/bash
set -e -o pipefail

finish_machine_model() { /usr/sbin/sysctl -n hw.model; }
finish_macos_version() { /usr/bin/sw_vers -productVersion; }
finish_darwin_version() { /usr/bin/uname -r; }

find_finish_python() {
    local candidate finish_path_python
    finish_path_python="$(command -v python3 || true)"
    for candidate in "$finish_path_python" /usr/local/bin/python3 /opt/homebrew/bin/python3 /Library/Developer/CommandLineTools/usr/bin/python3 /usr/bin/python3; do
        [[ -n "$candidate" && -x "$candidate" ]] || continue
        # Apple's launcher can request an interactive tools installation itself.
        if [[ "$candidate" == /usr/bin/python3 ]] && ! /usr/bin/xcode-select -p >/dev/null 2>&1; then
            continue
        fi
        if "$candidate" -I -c 'import sys; raise SystemExit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

select_clt_label() {
    # Pick one exact stable CLT label; never pass an OS upgrade to softwareupdate.
    /usr/bin/awk '
    /Label:/ {
        label = $0
        sub(/^.*Label:[[:space:]]*/, "", label)
        sub(/[[:space:]]*$/, "", label)
        if (label !~ /^Command Line Tools for Xcode[- ]/ || tolower(label) ~ /beta|preview|release candidate|[ -]rc([ -]|$)/) next
        if (!match(label, /[0-9]+([.][0-9]+)*/)) next
        split(substr(label, RSTART, RLENGTH), v, ".")
        score = v[1] * 1000000 + v[2] * 1000 + v[3]
        if (best == "" || score > highest) { best = label; highest = score }
    }
    END { if (best != "") print best }'
}

cleanup_finish_marker() {
    if [[ "${finish_marker_created:-0}" == 1 ]]; then
        /bin/rm -f -- "$finish_marker"
        finish_marker_created=0
    fi
}

install_finish_tools() {
    local listing label
    finish_marker=/tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress
    finish_marker_created=0
    if [[ ! -e "$finish_marker" && ! -L "$finish_marker" ]]; then
        (set -o noclobber; : > "$finish_marker")
        finish_marker_created=1
    fi
    trap cleanup_finish_marker EXIT
    echo 'Python 3.9+ is unavailable. Checking Apple for compatible Command Line Tools.'
    if ! listing="$(/usr/sbin/softwareupdate --list 2>&1)"; then
        printf '%s\n' "$listing"
        echo 'STOP: Apple update discovery failed. Internal EFI was not changed. Check internet access and rerun.'
        return 1
    fi
    printf '%s\n' "$listing"
    label="$(printf '%s\n' "$listing" | select_clt_label)"
    if [[ -z "$label" ]]; then
        echo 'STOP: Apple offered no stable Command Line Tools package. No macOS update was selected.'
        echo 'Install compatible tools from developer.apple.com/download/all/ or Python from python.org, then rerun.'
        return 1
    fi
    echo 'Installing only this exact Apple package:' "$label"
    if ! /usr/sbin/softwareupdate --install "$label" --verbose; then
        echo 'STOP: Apple Command Line Tools installation failed. Internal EFI was not changed.'
        echo 'Keep this setup log, check internet access/free space and rerun.'
        return 1
    fi
    cleanup_finish_marker
}

verify_finish_bundle() {
    "$finish_python" -I - "$finish_bundle_dir" <<'PY'
import hashlib, json, pathlib, sys
folder = pathlib.Path(sys.argv[1])
expected = {'finish_install.py', 'finish-install.command', 'READ-ME-FIRST.txt'}
try:
    manifest_path = folder / 'manifest.json'
    if folder.is_symlink() or manifest_path.is_symlink():
        raise ValueError('symlinked bundle or manifest')
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get('format') != 2 or manifest.get('model') != 'MacBookPro11,3'
            or manifest.get('macos_major') != 26 or set(manifest['sha256']) != expected):
        raise ValueError('unexpected manifest')
    for name, digest in manifest['sha256'].items():
        path = folder / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('missing/changed file: ' + name)
except (OSError, ValueError, KeyError, TypeError) as exc:
    raise SystemExit('STOP: USB finishing tools did not verify: ' + str(exc) + '. Rerun USB preparation.')
PY
}

finish_main() {
    local finish_bundle_dir finish_python finish_log finish_arg finish_check=0
    for finish_arg in "$@"; do
        case "$finish_arg" in
            --check) finish_check=1 ;;
            -h|--help) echo 'Usage: finish-install.command [--check]'; return 0 ;;
            *) echo 'STOP: Unknown option:' "$finish_arg"; return 1 ;;
        esac
    done
    if [[ "$(finish_machine_model)" != MacBookPro11,3 || "$(finish_macos_version)" != 26.* || "$(finish_darwin_version)" != 25.* ]]; then
        echo 'STOP: Run this on the installed MacBookPro11,3 Tahoe 26 desktop, not the preparation Mac or Recovery.'
        return 1
    fi
    finish_bundle_dir="$(cd -- "$(dirname -- "$0")" && pwd -P)"
    finish_python="$(find_finish_python || true)"
    if [[ "$finish_check" == 1 ]]; then
        if [[ -z "$finish_python" ]]; then
            echo 'STOP: Check mode needs an existing Python 3.9+. It does not install tools or change internal EFI.'
            return 1
        fi
        verify_finish_bundle
        "$finish_python" -I -B "$finish_bundle_dir/finish_install.py" --check
        return
    fi
    if [[ $EUID != 0 ]]; then
        exec /usr/bin/sudo /bin/bash "$0" "$@"
    fi
    if [[ -L "$finish_bundle_dir/build" || -L "$finish_bundle_dir/build/bootstrap" ]]; then
        echo 'STOP: Refusing a symlinked setup log directory.'
        return 1
    fi
    /bin/mkdir -p "$finish_bundle_dir/build/bootstrap"
    finish_log="$(/usr/bin/mktemp "$finish_bundle_dir/build/bootstrap/setup-XXXXXXXX.log")"
    exec > >(/usr/bin/tee -a "$finish_log") 2>&1
    echo 'Setup log:' "$finish_log"
    if [[ -z "$finish_python" ]]; then
        install_finish_tools
        finish_python="$(find_finish_python || true)"
    fi
    if [[ -z "$finish_python" ]]; then
        echo 'STOP: Tools installation did not provide Python 3.9+. Internal EFI was not changed.'
        return 1
    fi
    verify_finish_bundle
    echo 'Using Python:' "$finish_python"
    echo 'OCLP must already be installed to the internal EFI. Only its DataHub model settings will be completed.'
    "$finish_python" -I -B "$finish_bundle_dir/finish_install.py"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    finish_main "$@"
fi
