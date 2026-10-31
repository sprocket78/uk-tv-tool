#!/usr/bin/env bash
# Installs everything UK TV Tool needs on Linux. Safe to run again: anything already present is skipped.
#   System packages: Python with Tk, ffmpeg, VLC, a clipboard tool, cron, and the Perl modules get_iplayer uses
#   (apt, dnf or pacman); yt-dlp in a private Python environment (.venv); get_iplayer (latest release from its
#   official GitHub repository) in ~/.local/bin; and a menu shortcut.
# Run from a terminal in this folder:  ./setup.sh
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
HERE="$(pwd)"

step() { printf '\n\033[36m== %s\033[0m\n' "$1"; }
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

# Required packages, then optional ones (installed one at a time, so one missing package doesn't stop the rest).
if command -v apt-get >/dev/null; then
    PM="apt"
    REQUIRED="python3 python3-tk python3-venv ffmpeg curl ca-certificates perl libwww-perl liblwp-protocol-https-perl
              libmojolicious-perl libxml-libxml-perl libcgi-pm-perl"
    OPTIONAL="vlc xclip cron atomicparsley"
    install() { $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"; }
    $SUDO apt-get update
elif command -v dnf >/dev/null; then
    PM="dnf"
    REQUIRED="python3 python3-tkinter ffmpeg-free curl perl perl-libwww-perl perl-LWP-Protocol-https perl-Mojolicious
              perl-XML-LibXML perl-CGI"
    OPTIONAL="vlc xclip cronie AtomicParsley"
    install() { $SUDO dnf install -y "$@"; }
elif command -v pacman >/dev/null; then
    PM="pacman"
    REQUIRED="python tk ffmpeg curl perl perl-libwww perl-lwp-protocol-https perl-mojolicious perl-xml-libxml perl-cgi"
    OPTIONAL="vlc xclip cronie atomicparsley"
    install() { $SUDO pacman -S --needed --noconfirm "$@"; }
else
    PM=""
fi

step "System packages"
if [ -n "$PM" ]; then
    # shellcheck disable=SC2086
    install $REQUIRED
    for pkg in $OPTIONAL; do
        install "$pkg" >/dev/null 2>&1 && echo "$pkg: ok" || echo "$pkg: skipped (not available here)"
    done
else
    echo "No apt, dnf or pacman found. Install these yourself, then run this again:"
    echo "  Python 3 with Tk (tkinter) and venv, ffmpeg, curl, Perl with LWP, LWP::Protocol::https, Mojolicious,"
    echo "  XML::LibXML and CGI; optionally VLC, xclip and cron."
    python3 -c "import tkinter" 2>/dev/null || exit 1
fi

step "Python and yt-dlp (in this folder's .venv)"
# yt-dlp needs Python 3.11 or newer with Tk. Older systems (Ubuntu 22.04 and earlier, for example) get a private
# Python 3.12 in .tools instead, installed with uv from its official GitHub release, checksum verified.
new_enough() { "$1" -c 'import sys, tkinter; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }
private_python() {
    local arch uv="$HERE/.tools/uv" url
    arch="$(uname -m)"
    url="https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-unknown-linux-gnu.tar.gz"
    if [ ! -x "$uv" ]; then
        mkdir -p .tools
        curl -fsSL "$url" -o .tools/uv.tar.gz
        [ "$(curl -fsSL "$url.sha256" | cut -d' ' -f1)" = "$(sha256sum .tools/uv.tar.gz | cut -d' ' -f1)" ] ||
            { echo "uv download failed its checksum"; rm -f .tools/uv.tar.gz; exit 1; }
        tar -xzf .tools/uv.tar.gz -C .tools --strip-components=1
        rm .tools/uv.tar.gz
    fi
    export UV_PYTHON_INSTALL_DIR="$HERE/.tools/python"
    "$uv" python install 3.12
    "$uv" venv --seed --python 3.12 .venv
}
if [ -x .venv/bin/python ] && ! new_enough .venv/bin/python; then
    echo "replacing .venv: its Python is too old for yt-dlp"
    rm -rf .venv
fi
if [ ! -x .venv/bin/python ]; then
    if new_enough python3; then
        python3 -m venv .venv
    else
        echo "this system's Python is older than 3.11, which yt-dlp needs, so downloading a private Python 3.12"
        private_python
    fi
fi
.venv/bin/python -m pip install --upgrade --disable-pip-version-check --quiet -r requirements.txt
.venv/bin/python -c "import yt_dlp, tkinter; print('yt-dlp', yt_dlp.version.__version__)"

step "get_iplayer (for 1080p)"
if command -v get_iplayer >/dev/null || [ -x "$HOME/.local/bin/get_iplayer" ]; then
    echo "already installed"
else
    tag="$(curl -fsSL https://api.github.com/repos/get-iplayer/get_iplayer/releases/latest |
           sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)"
    [ -n "$tag" ] || { echo "couldn't find the latest get_iplayer release"; exit 1; }
    mkdir -p "$HOME/.local/bin"
    echo "downloading get_iplayer $tag"
    curl -fsSL "https://raw.githubusercontent.com/get-iplayer/get_iplayer/$tag/get_iplayer" -o "$HOME/.local/bin/get_iplayer"
    chmod +x "$HOME/.local/bin/get_iplayer"
fi
GIP="$(command -v get_iplayer || echo "$HOME/.local/bin/get_iplayer")"
"$GIP" --help >/dev/null && echo "get_iplayer works: $GIP"

step "Menu shortcut"
chmod +x uk-tv-tool.sh
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/uk-tv-tool.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=UK TV Tool
Comment=BBC iPlayer downloads and free live TV
Exec="$HERE/uk-tv-tool.sh"
Path=$HERE
Icon=video-display
Terminal=false
Categories=AudioVideo;Video;TV;
EOF
echo "added UK TV Tool to your applications menu"

step "Done"
echo "Start the app from your applications menu, or with ./uk-tv-tool.sh"
