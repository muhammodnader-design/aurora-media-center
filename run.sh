#!/usr/bin/env bash
# Aurora launcher (Linux / macOS).
# Reuses any working python3/python with PySide6; only installs what's missing.
cd "$(dirname "$0")" || exit 1

has() { command -v "$1" >/dev/null 2>&1; }
imports_pyside() { "$1" -c "import PySide6" >/dev/null 2>&1; }

install_python() {
    if has apt-get; then
        SUDO=""
        [ "$(id -u)" -ne 0 ] && SUDO="sudo"
        $SUDO apt-get update && $SUDO apt-get install -y python3 python3-pip python3-venv
    elif has dnf; then
        sudo dnf install -y python3 python3-pip
    elif has pacman; then
        sudo pacman -S --needed --noconfirm python python-pip
    elif has zypper; then
        sudo zypper --non-interactive install python3 python3-pip
    elif has brew; then
        brew install python
    else
        echo "No supported package manager found. Install Python 3.11+ manually." >&2
        return 1
    fi
}

# ---- 1. prefer an interpreter that already has PySide6 ----
PY=""
for cand in python3 python; do
    if has "$cand" && imports_pyside "$cand"; then
        PY="$cand"
        break
    fi
done

# ---- 2. otherwise any Python will do ----
if [ -z "$PY" ]; then
    for cand in python3 python; do
        if has "$cand"; then
            PY="$cand"
            break
        fi
    done
fi

# ---- 3. no Python at all: ask before installing ----
if [ -z "$PY" ]; then
    echo "Python 3.11+ was not found on this system."
    read -r -p "Install Python now? [y/N] " answer
    case "$answer" in
        [yY]*)
            install_python || exit 1
            ;;
        *)
            echo "Python 3.11+ is required to run Aurora. Exiting." >&2
            exit 1
            ;;
    esac
    for cand in python3 python; do
        if has "$cand"; then PY="$cand"; break; fi
    done
    if [ -z "$PY" ]; then
        echo "Python installation did not complete. Install Python 3.11+ manually and retry." >&2
        exit 1
    fi
fi

# ---- 4. PySide6: install only if the chosen interpreter lacks it ----
if ! imports_pyside "$PY"; then
    echo "PySide6 is missing for '$PY' - installing..."
    if "$PY" -m pip install --user -r requirements.txt; then
        :
    elif "$PY" -m venv .venv && .venv/bin/pip install -r requirements.txt; then
        PY=.venv/bin/python
    elif "$PY" -m pip install --user --break-system-packages -r requirements.txt; then
        :
    else
        echo "" >&2
        echo "Could not install PySide6 automatically." >&2
        echo "Install it manually, for example:" >&2
        echo "  $PY -m pip install --user PySide6" >&2
        echo "or install your distro's python3-pyside6 package." >&2
        exit 1
    fi
fi

exec "$PY" main.py "$@"
