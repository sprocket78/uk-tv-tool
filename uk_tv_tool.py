"""UK TV Tool - a Windows app for UK free-to-air TV.

* BBC iPlayer downloads: search, tick episodes, download up to 1080p
  (get_iplayer for 1080p, yt-dlp for the rest), copy manifest links.
* Search all channels: BBC iPlayer, ITVX, Channel 4, My5, STV Player and U.
  Only BBC programmes can be downloaded; the others open on their own sites.
* Live BBC TV: now/next, watch in a browser or VLC, record, copy manifest
  links, save a VLC playlist.
* A tab per country of free live channels from the iptv-org lists, with the
  same watch, record, copy and playlist tools. Add countries with the + tab.

BBC iPlayer streams are not DRM-protected; this tool only fetches what the
public iPlayer site serves. It does not decrypt DRM-protected services.
iPlayer is UK-only and needs a TV licence.
"""

import atexit
import collections
import faulthandler
import json
import os
import sys
import time
from pathlib import Path

# Kept as "iplayer-dl" so settings from earlier versions carry over.
CONFIG_PATH = Path(os.environ.get("APPDATA", Path.home())) / "iplayer-dl" / "config.json"
LOG_PATH = CONFIG_PATH.parent / "app.log"
LOG_MAX_BYTES = 1_000_000

# pythonw has no console: send all output, tracebacks and hard crashes to app.log.
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
try:
    if LOG_PATH.stat().st_size > LOG_MAX_BYTES:
        LOG_PATH.replace(LOG_PATH.with_suffix(".old.log"))
except OSError:
    pass
_log_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = _log_file
faulthandler.enable(_log_file)


def trace(msg):
    _log_file.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


trace(f"starting: {sys.executable} {sys.version.split()[0]} cwd={os.getcwd()}")
atexit.register(lambda: trace("exited"))

import glob  # noqa: E402
import ipaddress  # noqa: E402
import itertools  # noqa: E402
import queue  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import tkinter as tk  # noqa: E402
import urllib.error  # noqa: E402
import urllib.parse  # noqa: E402
import urllib.request  # noqa: E402
import webbrowser  # noqa: E402
import zlib  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

APP_NAME = "UK TV Tool"

try:
    import yt_dlp
    from yt_dlp.utils import sanitize_filename
except ImportError:
    trace(f"yt-dlp import failed, sys.path={sys.path}")
    tk.Tk().withdraw()
    messagebox.showerror(APP_NAME,
                         "yt-dlp is not installed for this Python.\n\nRun setup.ps1, or open a command prompt "
                         "and run:\n"
                         f'"{sys.executable.replace("pythonw", "python")}" -s -m pip install yt-dlp')
    raise

IBL = "https://ibl.api.bbci.co.uk/ibl/v1"
# 1080p comes from get_iplayer; yt-dlp only sees iPlayer's 720p stream lists.
QUALITIES = {
    "1080p": 1080,
    "720p": 720,
    "540p": 540,
    "396p": 396,
    "288p": 288,
}
# e.g. " 35.2% of ~536.62 MB @  79.6 Mb/s ETA: 00:00:34 (dashfhd1/bi) [video]"
GIP_PROGRESS_RE = re.compile(r"([\d.]+)% of \S+ \S+ @\s*(\S+) Mb/s ETA: (\S+) \((\S+)\) \[(\w+)\]")
# BBC programme ids: 8 chars, starting b/m/p/w, always containing a digit.
PID_RE = re.compile(r"\b([bmpw](?=[0-9a-z]*\d)[0-9a-z]{7})\b")


# ---------------------------------------------------------------- iPlayer API

def ibl_get(path, **params):
    params.setdefault("rights", "web")
    params.setdefault("lang", "en")
    url = f"{IBL}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def search_programmes(query):
    data = ibl_get("new-search", q=query)
    results = []
    for item in data.get("new_search", {}).get("results", []):
        results.append({
            "id": item["id"],
            "type": item.get("type"),
            "title": item.get("title", "?"),
            "subtitle": item.get("subtitle", ""),
            "synopsis": item.get("synopses", {}).get("small", ""),
            "channel": item.get("master_brand", {}).get("titles", {}).get("small", ""),
        })
    return results


def _episode_from_element(el, fallback_title=""):
    version = (el.get("versions") or [{}])[0]
    return {
        "id": el["id"],
        "title": el.get("title") or fallback_title,
        "subtitle": el.get("subtitle", ""),
        "synopsis": el.get("synopses", {}).get("small", ""),
        "duration": version.get("duration", {}).get("text", ""),
        "availability": version.get("availability", {}).get("remaining", {}).get("text", ""),
    }


def list_episodes(pid):
    """Return all available episodes of a programme (brand/series) or a single episode."""
    episodes, page = [], 1
    while True:
        data = ibl_get(f"programmes/{pid}/episodes", availability="available",
                       per_page=200, page=page)
        block = data.get("programme_episodes", {})
        elements = block.get("elements", [])
        episodes += [_episode_from_element(el) for el in elements if el.get("type") == "episode"]
        if not elements or len(episodes) >= block.get("count", 0):
            break
        page += 1
    if episodes:
        return episodes
    # Not a programme with episodes - maybe the pid is an episode itself.
    data = ibl_get(f"episodes/{pid}")
    return [_episode_from_element(el) for el in data.get("episodes", [])]


def episode_url(pid):
    return f"https://www.bbc.co.uk/iplayer/episode/{pid}"


def episode_manifests(pid):
    """HLS and DASH manifest links for an episode. They are signed, so they stop working after some hours."""
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noprogress": True}) as ydl:
        info = ydl.extract_info(episode_url(pid), download=False)
    # Several manifests are offered (website, TV-set...) with different top qualities; keep the best of each type.
    best = {}
    for f in info.get("formats", []):
        kind = {"m3u8_native": "hls", "m3u8": "hls", "http_dash_segments": "dash"}.get(f.get("protocol"))
        url = f.get("manifest_url")
        height = f.get("height") or 0
        if kind and url and url.startswith("https") and height > best.get(kind, (0, None))[0]:
            best[kind] = (height, url)
    return {kind: url for kind, (_, url) in best.items()}


def find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    # winget installs add ffmpeg to PATH only for shells started afterwards.
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet"
    candidates = [winget / "Links" / "ffmpeg.exe", *winget.glob("Packages/Gyan.FFmpeg*/*/bin/ffmpeg.exe")]
    return next((str(p) for p in candidates if p.exists()), None)


def find_get_iplayer():
    """Return the get_iplayer install folder (holding perl\\bin and get_iplayer.pl), or None."""
    candidates = [Path(os.environ.get(var, "")) / "get_iplayer"
                  for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    found = shutil.which("get_iplayer")
    if found:
        candidates.insert(0, Path(found).parent)
    return next((p for p in candidates if (p / "get_iplayer.pl").exists()
                 and (p / "perl" / "bin" / "perl.exe").exists()), None)


def safe_name(text):
    # Episode subtitles are often dates like 29/10/2026; keep them readable.
    return sanitize_filename(text.replace("/", "-").replace(":", " -"))


# ---------------------------------------------------------------- other channels (search + links only)
# ITVX, Channel 4, My5, STV and U use DRM, so the app only finds programmes and opens their pages.

BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
                   "Accept": "application/json"}
ITV_FEATURES = "clearkey,outband-webvtt,hls,aes,playready,widevine,fairplay,bbts,progressive,hd,rtmpe"


def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    return json.loads(body) if body.strip() else None


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _result(service, title, url, about="", episodes="", pid=None):
    return {"service": service, "title": title, "url": url, "about": about,
            "episodes": str(episodes or ""), "pid": pid}


def search_bbc(q):
    return [_result("BBC iPlayer", p["title"],
                    f"https://www.bbc.co.uk/iplayer/{'episodes' if p['type'] == 'programme' else 'episode'}/{p['id']}",
                    p["synopsis"], pid=p["id"])
            for p in search_programmes(q)]


def search_itvx(q):
    data = get_json("https://textsearch.prd.oasvc.itv.com/search?" + urllib.parse.urlencode({
        "broadcaster": "itv", "featureSet": ITV_FEATURES, "onlyFree": "false", "platform": "dotcom", "query": q}))
    out = []
    for r in (data or {}).get("results", []):
        d = r.get("data", {})
        title = d.get("programmeTitle") or d.get("filmTitle") or d.get("specialTitle")
        ccid = d.get("programmeCCId") or d.get("filmCCId") or d.get("specialCCId")
        if title and ccid:
            out.append(_result("ITVX", title, f"https://www.itv.com/watch/{slugify(title)}/{ccid}",
                               d.get("synopsis", ""), d.get("totalAvailableEpisodes", "")))
    return out


def search_channel4(q):
    data = get_json("https://all4nav.channel4.com/v1/api/search?" + urllib.parse.urlencode(
        {"expand": "default", "q": q, "limit": 30, "offset": 0}))
    results = (data or {}).get("results", [])
    if not isinstance(results, list):  # "No Matches" comes back as a message object
        return []
    brands = (r.get("brand") for r in results if isinstance(r, dict))
    return [_result("Channel 4", b["title"], b["href"], b.get("description", "")) for b in brands if b and b.get("href")]


def search_my5(q):
    data = get_json("https://corona.channel5.com/shows/search.json?" + urllib.parse.urlencode(
        {"platform": "my5desktop", "friendly": 1, "query": q}))
    return [_result("My5", s["title"], f"https://www.channel5.com/show/{s['f_name']}", s.get("s_desc", ""))
            for s in (data or {}).get("shows", [])]


_stv_catalogue = []


def search_stv(q):
    # STV's API ignores search terms, so fetch the whole catalogue once and filter it here.
    if not _stv_catalogue:
        found, offset = [], 0
        while True:
            data = get_json(f"https://player.api.stv.tv/v1/programmes/?limit=300&offset={offset}", timeout=30)
            found += data.get("results", [])
            offset += 300
            if not data.get("results") or offset >= data.get("totalResults", 0):
                break
        _stv_catalogue[:] = found
    words = q.lower().split()
    return [_result("STV Player", p["name"], p.get("_permalink") or f"https://player.stv.tv/summary/{p['guid']}/",
                    p.get("shortDescription", ""), p.get("availableEpisodes", ""))
            for p in _stv_catalogue if all(w in p["name"].lower() for w in words)]


def search_u(q):
    data = get_json("https://vschedules.uktv.co.uk/vod/search/?" + urllib.parse.urlencode({"q": q}))
    return [_result("U", s["name"], f"https://u.co.uk/shows/{s['slug']}", s.get("synopsis", ""), s.get("ep_count", ""))
            for s in data or []]


SEARCHERS = [("BBC iPlayer", search_bbc), ("ITVX", search_itvx), ("Channel 4", search_channel4),
             ("My5", search_my5), ("STV Player", search_stv), ("U", search_u)]


def search_everywhere(q):
    """Search every service at once. Returns (results, errors); one failing service doesn't stop the rest."""
    results, errors = [], []
    with ThreadPoolExecutor(len(SEARCHERS)) as pool:
        futures = [(name, pool.submit(fn, q)) for name, fn in SEARCHERS]
        for name, fut in futures:
            try:
                results += fut.result()
            except Exception as exc:
                errors.append(f"{name} search failed: {exc}")
    return results, errors


# ---------------------------------------------------------------- live BBC channels

# iPlayer live page names that differ from the channel id.
LIVE_PAGES = {"bbc_one_london": "bbcone", "bbc_two_england": "bbctwo", "bbc_news24": "bbcnews", "s4cpbs": "s4c"}
MEDIASELECTOR = "https://open.live.bbc.co.uk/mediaselector/6/select/version/2.0/mediaset/{}/vpid/{}/format/json"


def live_page_url(channel_id):
    return f"https://www.bbc.co.uk/iplayer/live/{LIVE_PAGES.get(channel_id, channel_id.replace('_', ''))}"


def _when(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _broadcast_label(b):
    ep = b.get("episode", {})
    title = ep.get("title", "")
    if ep.get("subtitle"):
        title += f" - {ep['subtitle']}"
    return f"{_when(b['scheduled_start']).astimezone().strftime('%H:%M')}  {title}", title


def load_live_channels():
    """BBC TV channels with what's on now and next."""
    channels = [{"id": c["id"], "title": c["title"]}
                for c in ibl_get("channels").get("channels", []) if "radio" not in c["id"]]

    def fill(ch):
        ch.update(now="", next="", now_title="")
        try:
            items = ibl_get(f"channels/{ch['id']}/broadcasts", per_page=4).get("broadcasts", {}).get("elements", [])
        except Exception:
            return
        now = datetime.now(timezone.utc)
        for i, b in enumerate(items):
            if _when(b["scheduled_start"]) <= now < _when(b["scheduled_end"]):
                ch["now"], ch["now_title"] = _broadcast_label(b)
                if i + 1 < len(items):
                    ch["next"] = _broadcast_label(items[i + 1])[0]
                break

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(fill, channels))
    return channels


def _m3u8_attrs(line):
    return {k: v.strip('"') for k, v in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line.split(":", 1)[1])}


def _live_manifest(channel_id, mediaset, transfer):
    sel = get_json(MEDIASELECTOR.format(mediaset, channel_id))
    hrefs = [c["href"] for m in (sel or {}).get("media", []) if m.get("kind") == "video"
             for c in m.get("connection", []) if c.get("transferFormat") == transfer]
    hrefs.sort(key=lambda h: not h.startswith("https"))
    if not hrefs:
        raise RuntimeError("no live stream offered - iPlayer live TV only works from a UK connection")
    return hrefs[0]


def live_dash_url(channel_id):
    # The "pc" mediaset only offers HLS for live TV; the TV-set one has DASH.
    return _live_manifest(channel_id, "iptv-all", "dash")


def stream_parts(master):
    """Return (master, best video playlist, main audio playlist or None) for an HLS master playlist.
    Anything else (a DASH manifest, a single-quality playlist) comes back as the master itself."""
    req = urllib.request.Request(master, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        base = resp.geturl()  # some lists link through a redirect
        lines = resp.read(2_000_000).decode("utf-8", "replace").splitlines()
    audio, best = {}, None
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-MEDIA:") and "TYPE=AUDIO" in line and "URI=" in line:
            a = _m3u8_attrs(line)
            if "describes-video" in a.get("CHARACTERISTICS", ""):  # skip audio description
                continue
            if a.get("DEFAULT") == "YES" or a.get("GROUP-ID") not in audio:
                audio[a.get("GROUP-ID")] = urllib.parse.urljoin(base, a["URI"])
        elif line.startswith("#EXT-X-STREAM-INF:") and i + 1 < len(lines):
            a = _m3u8_attrs(line)
            bw = int(a.get("BANDWIDTH", 0) or 0)
            if best is None or bw > best[0]:
                best = (bw, urllib.parse.urljoin(base, lines[i + 1].strip()), a.get("AUDIO"))
    if not best:
        return master, master, None
    return master, best[1], audio.get(best[2])


def live_stream_urls(channel_id):
    """Return (master playlist, best video playlist, main audio playlist or None) for a live BBC channel."""
    return stream_parts(_live_manifest(channel_id, "pc", "hls"))


# ---------------------------------------------------------------- free channels by country
# Channel lists come from the iptv-org project, which collects publicly available streams by country.

IPTV_ORG = "https://iptv-org.github.io"
DEFAULT_COUNTRIES = [["UK", "UK"], ["IE", "Ireland"], ["FR", "France"], ["DE", "Germany"], ["US", "USA"]]
# Sites that rebroadcast paid or DRM-protected channels without permission. Their streams are left out,
# as are streams served from a bare IP address or that need a faked referrer or browser identity.
UNOFFICIAL_HOSTS = {
    "aynascope.net", "aynaott.com", "anixa.tv", "antik.sk", "cammonitorplus.net", "etvhosts.site",
    "filegear-sg.me", "freeott.top", "githubusercontent.com", "hopslan.com", "iptvnetwork.net",
    "mcquack.net", "stmify.com", "team-tv.co",
}
EXTINF_RE = re.compile(r'#EXTINF:-?[\d.]+((?:\s+[\w-]+="[^"]*")*)\s*,(.*)')
CHANNEL_NAME_RE = re.compile(r"(.*?)(?:\s*\((\d+[pi])\))?((?:\s*\[[^\]]+\])*)\s*$")


def load_countries():
    """{code: name} for every country iptv-org has a list for."""
    return {c["code"]: c["name"] for c in get_json(f"{IPTV_ORG}/api/countries.json")}


def _unofficial(url, options):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return bool(options) or any(host == h or host.endswith("." + h) for h in UNOFFICIAL_HOSTS)


def load_country_channels(code):
    """Return (channels, number left out as unofficial) for one country."""
    return _parse_channel_list(f"{IPTV_ORG}/iptv/countries/{code.lower()}.m3u", code)


def _parse_channel_list(url, code):
    with _open(url, timeout=30) as resp:
        lines = resp.read().decode("utf-8", "replace").splitlines()
    channels, skipped, info, options, seen = [], 0, None, [], set()
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF"):
            info, options = EXTINF_RE.match(line), []
        elif line.startswith("#EXTVLCOPT"):
            options.append(line)
        elif line and not line.startswith("#") and info:
            if _unofficial(line, options):
                skipped += 1
            elif line not in seen:
                seen.add(line)
                attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', info.group(1)))
                title, quality, notes = CHANNEL_NAME_RE.match(info.group(2).strip()).groups()
                group = attrs.get("group-title", "")
                channels.append({
                    # Keyed by stream so a refresh doesn't mix up recordings in progress.
                    "id": f"{code}:{zlib.crc32(line.encode()):08x}", "title": title or info.group(2), "url": line,
                    "group": "Other" if group in ("", "Undefined") else group.replace(";", ", "),
                    "quality": quality or "", "notes": ", ".join(re.findall(r"\[([^\]]+)\]", notes)),
                    "tvg_id": attrs.get("tvg-id", ""), "now_title": "",
                })
            info = None
    channels.sort(key=lambda ch: ch["title"].lower())
    return channels, skipped


def _open(url, timeout=10, **headers):
    req = urllib.request.Request(url, headers={**BROWSER_HEADERS, "Accept": "*/*", **headers})
    return urllib.request.urlopen(req, timeout=timeout)


def check_stream(url, flagged_geo):
    """Try a stream from this connection, down to its first bytes of video.
    Returns "ok", "geo" (region-locked), "blocked" (refused, reason unknown) or "offline"."""
    try:
        for _ in range(3):  # master playlist -> media playlist -> segment
            with _open(url) as resp:
                base, text = resp.geturl(), resp.read(2_000_000).decode("utf-8", "replace")
            if "#EXTM3U" not in text[:300]:
                return "ok" if "<MPD" in text[:2000] else "offline"  # DASH: the manifest loads
            uris = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
            if not uris:
                return "offline"
            if "#EXT-X-STREAM-INF" in text:
                url = urllib.parse.urljoin(base, uris[0])
                continue
            with _open(urllib.parse.urljoin(base, uris[-1]), Range="bytes=0-4095") as resp:
                # Some services answer outside their country with empty video.
                return "ok" if resp.read(4096) else "geo"
        return "offline"
    except urllib.error.HTTPError as exc:
        if exc.code == 451 or (exc.code in (401, 403) and flagged_geo):
            return "geo"
        return "blocked" if exc.code in (401, 403) else "offline"
    except Exception:
        return "geo" if flagged_geo else "offline"


CHECKED = ("ok", "geo", "blocked", "offline")


def in_parallel(items, fn, stop, workers=12):
    """Run fn(item) for every item on background threads until done or stop is set."""
    todo = queue.Queue()
    for item in items:
        todo.put(item)

    def work():
        while not stop.is_set():
            try:
                item = todo.get_nowait()
            except queue.Empty:
                return
            fn(item)
    for _ in range(workers):  # daemon threads, so quitting never waits for them
        threading.Thread(target=work, daemon=True).start()


def check_streams(channels, report, stop):
    """Check every channel's stream in the background, calling report(channel id, result) as each finishes."""
    in_parallel(channels, lambda ch: report(ch["id"], check_stream(ch["url"], "Geo-blocked" in ch["notes"])), stop)


def check_all(channels):
    """Check channels and wait for the results: {channel id: result}."""
    results, finished = {}, threading.Event()

    def report(cid, result):
        results[cid] = result
        if len(results) == len(channels):
            finished.set()
    if channels:
        check_streams(channels, report, threading.Event())
        finished.wait()
    return results


_every_stream, _every_stream_lock = None, threading.Lock()


def find_new_link(ch):
    """Look through every country's list for another link to the same channel that plays here."""
    global _every_stream
    with _every_stream_lock:
        if _every_stream is None:
            _every_stream = _parse_channel_list(f"{IPTV_ORG}/iptv/index.m3u", "ALL")[0]
    key, title = ch["tvg_id"].split("@")[0].lower(), ch["title"].lower()
    tried = {ch["url"], ch.get("orig_url")}
    for other in _every_stream:
        same = (key and other["tvg_id"].split("@")[0].lower() == key) or other["title"].lower() == title
        if same and other["url"] not in tried:
            tried.add(other["url"])
            if check_stream(other["url"], False) == "ok":
                return other["url"]
    # The list itself may have been updated since it was loaded.
    return ch["url"] if check_stream(ch["url"], False) == "ok" else None


def build_country_playlist(countries, only_playable, replaced, bbc_channels=None):
    """An .m3u of several countries' channels, grouped by country. countries is a list of
    (code, name, channels or None to download them, set of categories or None for all).
    Returns (playlist text, channel count)."""
    lines = ["#EXTM3U"]
    if bbc_channels is not None:
        lines += build_live_playlist(bbc_channels or load_live_channels())[0].splitlines()[1:]
    for code, name, channels, categories in countries:
        if channels is None:
            channels = load_country_channels(code)[0]
        for ch in channels:
            ch["url"] = replaced.get(ch["url"], ch["url"])
        if categories is not None:
            channels = [ch for ch in channels if categories & {g.strip() for g in ch["group"].split(",")}]
        if only_playable:
            results = check_all([ch for ch in channels if ch.get("status") not in CHECKED])
            channels = [ch for ch in channels if results.get(ch["id"], ch.get("status")) == "ok"]
        for ch in channels:
            lines += [f'#EXTINF:-1 group-title="{name}",{ch["title"]}', ch["url"]]
    text = "\n".join(lines) + "\n"
    return text, text.count("#EXTINF")


def copy_to_windows_clipboard(text):
    """Put text on the Windows clipboard so it stays there after the app closes. Returns False if it can't."""
    try:
        import ctypes
        from ctypes import wintypes
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        data = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(data)
        handle = kernel32.GlobalAlloc(0x0002, size)  # GMEM_MOVEABLE
        ctypes.memmove(kernel32.GlobalLock(handle), data, size)
        kernel32.GlobalUnlock(handle)
        for _ in range(10):  # another app may have the clipboard open for a moment
            if user32.OpenClipboard(None):
                break
            time.sleep(0.05)
        else:
            return False
        try:
            user32.EmptyClipboard()
            return bool(user32.SetClipboardData(13, handle))  # CF_UNICODETEXT
        finally:
            user32.CloseClipboard()
    except Exception:
        return False


def build_live_playlist(channels):
    """An .m3u playlist of every live BBC channel's HLS manifest, for VLC and IPTV players."""
    def entry(ch):
        try:
            return ch, _live_manifest(ch["id"], "pc", "hls")
        except Exception:
            return ch, None
    with ThreadPoolExecutor(8) as pool:
        found = list(pool.map(entry, channels))
    lines = ["#EXTM3U"]
    for ch, url in found:
        if url:
            lines += [f'#EXTINF:-1 tvg-id="{ch["id"]}" group-title="BBC",{ch["title"]}', url]
    missing = [ch["title"] for ch, url in found if not url]
    return "\n".join(lines) + "\n", missing


def find_vlc():
    for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        exe = Path(base) / "VideoLAN" / "VLC" / "vlc.exe"
        if exe.exists():
            return str(exe)
    return shutil.which("vlc")


def find_any_ffmpeg():
    if find_ffmpeg():
        return find_ffmpeg()
    gip = find_get_iplayer()
    bundled = gip / "utils" / "bin" / "ffmpeg.exe" if gip else None
    return str(bundled) if bundled and bundled.exists() else None


class LiveRecorder(threading.Thread):
    """Record one live channel with ffmpeg until stopped or for a set number of minutes."""

    def __init__(self, channel, minutes, save_dir, events):
        super().__init__(daemon=True)
        self.channel, self.minutes, self.save_dir, self.events = channel, minutes, save_dir, events
        self.stop_event = threading.Event()

    def emit(self, kind, *args):
        self.events.put((kind, *args))

    def run(self):
        cid, name = self.channel["id"], self.channel["title"]
        try:
            ffmpeg = find_any_ffmpeg()
            if not ffmpeg:
                raise RuntimeError("ffmpeg not found")
            if "url" in self.channel:
                # Many free channels tie their playlists to one session, so ffmpeg picks the best
                # video and audio from the original link itself.
                video, audio = self.channel["url"], None
            else:
                _, video, audio = live_stream_urls(cid)
            folder = Path(self.save_dir) / "Live"
            folder.mkdir(parents=True, exist_ok=True)
            label = f"{name} {time.strftime('%Y-%m-%d %H%M')}"
            if self.channel.get("now_title"):
                label += f" - {self.channel['now_title']}"
            base = str(folder / safe_name(label))
            ts, mp4 = base + ".ts", base + ".mp4"
            # .ts survives an abrupt stop; it is turned into .mp4 afterwards.
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", video]
            if audio:
                cmd += ["-i", audio, "-map", "0:v:0", "-map", "1:a:0"]
            cmd += ["-c", "copy"]
            if self.minutes:
                cmd += ["-t", str(int(self.minutes * 60))]
            cmd += ["-f", "mpegts", ts]
            err_path = CONFIG_PATH.parent / f"ffmpeg-{cid.replace(':', '-')}.log"
            no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            with open(err_path, "wb") as err:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err,
                                        creationflags=no_window)
                start = time.time()
                while proc.poll() is None:
                    if self.stop_event.wait(1):
                        try:  # ask ffmpeg to finish; .ts is fine to cut off if it doesn't listen
                            proc.stdin.write(b"q\n")
                            proc.stdin.flush()
                        except OSError:
                            pass
                        try:
                            proc.wait(3)
                        except subprocess.TimeoutExpired:
                            proc.terminate()
                        break
                    secs = int(time.time() - start)
                    limit = f" / {self.minutes} min" if self.minutes else ""
                    self.emit("rec", cid, f"● REC {secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}{limit}")
                proc.wait()  # Windows only reports the real file size once ffmpeg has closed it
            elapsed = int(time.time() - start)
            if not os.path.exists(ts) or os.path.getsize(ts) == 0:
                problem = err_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
                raise RuntimeError(" / ".join(problem) or "nothing was recorded")
            self.emit("rec", cid, "Saving...")
            r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", ts, "-c", "copy",
                                "-movflags", "+faststart", mp4], capture_output=True, creationflags=no_window)
            saved = ts
            if r.returncode == 0 and os.path.exists(mp4):
                os.remove(ts)
                saved = mp4
            self.emit("rec_done", cid, f"Recorded {elapsed // 60}:{elapsed % 60:02d} of {name}: {saved}")
        except Exception as exc:
            hint = " (the stream may be offline or blocked outside its country)" if "url" in self.channel else ""
            self.emit("rec_done", cid, f"Recording {name} failed{hint}: {exc}")


# ---------------------------------------------------------------- config

def load_config():
    defaults = {
        "save_dir": str(Path.home() / "Videos" / "iPlayer"),
        "quality": "1080p",
        "subtitles": True,
        "countries": DEFAULT_COUNTRIES,
        "replaced_links": {},  # expired stream link -> working one found by "Find new links"
    }
    try:
        defaults.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if defaults["quality"] not in QUALITIES:  # e.g. the old "Best available"
        defaults["quality"] = "1080p"
    return defaults


def save_config(cfg):
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- download worker

class Cancelled(Exception):
    pass


class Downloader(threading.Thread):
    def __init__(self, jobs, cfg, events):
        super().__init__(daemon=True)
        self.jobs, self.cfg, self.events = jobs, cfg, events
        self.cancel = threading.Event()

    def emit(self, kind, *args):
        self.events.put((kind, *args))

    def _hook(self, job_index):
        def hook(d):
            if self.cancel.is_set():
                raise Cancelled()
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                pct = d["downloaded_bytes"] * 100 / total if total else 0
                speed = d.get("_speed_str", "").strip()
                eta = d.get("_eta_str", "").strip()
                self.emit("progress", job_index, pct, f"{pct:5.1f}%  {speed}  ETA {eta}")
            elif d["status"] == "finished":
                self.emit("progress", job_index, 100, "Merging...")
        return hook

    @staticmethod
    def _paths(ep, save_dir):
        folder = Path(save_dir) / safe_name(ep["title"])
        name = safe_name(f"{ep['title']} - {ep['subtitle']}" if ep["subtitle"] else ep["title"])
        return folder, name

    def _options(self, ep, job_index):
        height = QUALITIES.get(self.cfg["quality"])
        h = f"[height<={height}]" if height and height < 1080 else ""
        folder, name = self._paths(ep, self.cfg["save_dir"])
        opts = {
            "format": f"bv*{h}+ba/b{h}/b",
            "outtmpl": str(folder / f"{name}.%(ext)s"),
            "merge_output_format": "mp4",
            "progress_hooks": [self._hook(job_index)],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _QueueLogger(self.emit),
        }
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        if self.cfg["subtitles"]:
            opts.update({
                "writesubtitles": True,
                "subtitleslangs": ["en.*", "en"],
                "postprocessors": [{"key": "FFmpegSubtitlesConvertor", "format": "srt"}],
            })
        return opts

    def _get_iplayer(self, gip, ep, job_index):
        """Download one episode with get_iplayer, best quality first (1080p, then 720p...)."""
        folder, name = self._paths(ep, self.cfg["save_dir"])
        folder.mkdir(parents=True, exist_ok=True)
        # Same environment get_iplayer.cmd sets up: its own perl and its bundled ffmpeg.
        env = dict(os.environ, PATH=f"{gip / 'perl' / 'bin'};{gip / 'utils' / 'bin'};{os.environ.get('PATH', '')}",
                   PERL5LIB="")
        cmd = [str(gip / "perl" / "bin" / "perl.exe"), str(gip / "get_iplayer.pl"),
               "--pid", ep["id"], "--type=tv", "--tv-quality=fhd,hd,sd,web,mobile",
               "--output", str(folder), "--file-prefix", name, "--whitespace",
               "--force", "--overwrite", "--log-progress"]
        if self.cfg["subtitles"]:
            cmd.append("--subtitles")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tail, buf = [], b""
        while True:
            if self.cancel.is_set():
                # get_iplayer runs ffmpeg as a child; stop the whole tree.
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                proc.wait()
                # Remove the half-finished pieces (.dash.m4a, .video.m4v, ...).
                for part in folder.glob(glob.escape(name) + ".*"):
                    try:
                        part.unlink()
                    except OSError:
                        pass
                raise Cancelled()
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            buf += chunk
            *lines, buf = re.split(rb"[\r\n]", buf)
            for raw in lines:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                m = GIP_PROGRESS_RE.match(line)
                if m:
                    pct, speed, eta, stream, part = m.groups()
                    shown = float(pct) if part == "video" else 0
                    self.emit("progress", job_index, shown,
                              f"{float(pct):5.1f}% {part}  {speed} Mb/s  ETA {eta}  ({stream.split('/')[0]})")
                    continue
                tail = (tail + [line])[-6:]
                trace(f"get_iplayer: {line}")
                if line.startswith(("INFO: Converting", "INFO: Tagging")):
                    self.emit("progress", job_index, 100, line[6:])
                elif line.startswith("ERROR"):
                    self.emit("log", line)
        if proc.wait() != 0:
            raise RuntimeError(" / ".join(tail[-3:]) or f"get_iplayer exit code {proc.returncode}")

    def run(self):
        gip = find_get_iplayer() if QUALITIES.get(self.cfg["quality"]) == 1080 else None
        if QUALITIES.get(self.cfg["quality"]) == 1080 and not gip:
            self.emit("log", "get_iplayer is not installed, so 1080p is unavailable - using 720p.")
        for i, ep in enumerate(self.jobs):
            if self.cancel.is_set():
                self.emit("status", i, "Cancelled")
                continue
            self.emit("status", i, "Starting...")
            try:
                if gip:
                    self._get_iplayer(gip, ep, i)
                else:
                    with yt_dlp.YoutubeDL(self._options(ep, i)) as ydl:
                        ydl.download([episode_url(ep["id"])])
                self.emit("status", i, "Done")
                self.emit("log", f"Saved: {ep['title']} - {ep['subtitle']}")
            except Cancelled:
                self.emit("status", i, "Cancelled")
            except Exception as exc:  # yt-dlp raises DownloadError and friends
                if self.cancel.is_set():
                    self.emit("status", i, "Cancelled")
                else:
                    self.emit("status", i, "Failed")
                    self.emit("log", f"Failed: {ep['subtitle'] or ep['title']}: {exc}")
        self.emit("finished")


class _QueueLogger:
    def __init__(self, emit):
        self.emit = emit

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        if "style information loss" not in msg:  # expected when converting TTML subs to SRT
            self.emit("log", f"Warning: {msg}")

    def error(self, msg):
        self.emit("log", msg)


# ---------------------------------------------------------------- UI

LIST_LOADS = itertools.count(1)  # tells results for a reloaded or reopened tab from stale ones

# How each stream check shows: (dot colour, text).
STATUS = {
    None: ("amber", "Checking..."),
    "searching": ("amber", "Finding a new link..."),
    "ok": ("green", "Plays here"),
    "geo": ("red", "Region-locked - needs VPN"),
    "blocked": ("red", "Blocked here"),
    "offline": ("grey", "Offline"),
}


class CountryTab(ttk.Frame):
    """One country's free live channels: check, filter, watch in VLC, copy links, record, fix dead links."""
    ALL = "All categories"

    def __init__(self, app, code, name):
        super().__init__(app.tabs)
        self.app, self.code, self.name = app, code, name
        self.channels, self.by_id, self.loaded, self.skipped = [], {}, False, 0
        self.gen, self.stop = 0, threading.Event()  # a new generation each time the list loads
        self.searching = 0
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Filter:").pack(side="left")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.show())
        ttk.Entry(top, textvariable=self.filter, width=22).pack(side="left", padx=4)
        self.category = tk.StringVar(value=self.ALL)
        self.category_box = ttk.Combobox(top, textvariable=self.category, values=[self.ALL], width=18,
                                         state="readonly")
        self.category_box.pack(side="left", padx=4)
        self.category_box.bind("<<ComboboxSelected>>", lambda e: self.show())
        self.playable_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Only ones that play here", variable=self.playable_only,
                        command=self.show).pack(side="left", padx=8)
        ttk.Button(top, text="Update links", command=self.load).pack(side="left", padx=(8, 0))
        self.fix_btn = ttk.Button(top, text="Find new links", command=self.find_new_links)
        self.fix_btn.pack(side="left", padx=4)
        self.progress = ttk.Label(top, foreground="#555")
        self.progress.pack(side="right")

        acts = ttk.Frame(self)
        acts.pack(fill="x", **pad)
        ttk.Button(acts, text="Watch in VLC", command=self.watch_in_vlc,
                   state="normal" if find_vlc() else "disabled").pack(side="left")
        ttk.Button(acts, text="Copy link", command=self.copy_link).pack(side="left", padx=4)
        ttk.Button(acts, text="VLC playlist...", command=lambda: app.playlist_dialog(self.code)).pack(side="left", padx=4)
        ttk.Label(acts, text="    Record for").pack(side="left")
        self.rec_minutes = tk.StringVar(value="0")
        ttk.Spinbox(acts, from_=0, to=600, increment=15, width=5, textvariable=self.rec_minutes).pack(side="left", padx=4)
        ttk.Label(acts, text="min (0 = until stopped)").pack(side="left")
        ttk.Button(acts, text="● Record", command=self.start_recording).pack(side="left", padx=(12, 0))
        ttk.Button(acts, text="■ Stop", command=self.stop_recording).pack(side="left", padx=4)

        cols = ("channel", "category", "quality", "notes", "rec")
        self.tree = ttk.Treeview(self, columns=cols, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Plays here?")
        self.tree.column("#0", width=200, stretch=False)
        for col, text, width, stretch in (("channel", "Channel", 300, True), ("category", "Category", 170, False),
                                          ("quality", "Quality", 65, False), ("notes", "Notes", 120, False),
                                          ("rec", "Recording", 140, False)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=stretch)
        self.tree.pack(fill="both", expand=True, **pad)
        self.tree.bind("<Double-1>", lambda e: self.watch_in_vlc() if find_vlc() else self.copy_link())

        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Watch in VLC", command=self.watch_in_vlc, state="normal" if find_vlc() else "disabled")
        menu.add_command(label="Copy stream link", command=self.copy_link)
        menu.add_command(label="Find a new link", command=self.find_new_link)
        menu.add_separator()
        menu.add_command(label="Record", command=self.start_recording)
        menu.add_command(label="Stop recording", command=self.stop_recording)

        def popup(event):
            row = self.tree.identify_row(event.y)
            if row:
                self.tree.selection_set(row)
                menu.tk_popup(event.x_root, event.y_root)
        self.tree.bind("<Button-3>", popup)

        self.note = ttk.Label(self, foreground="#555", wraplength=1000, justify="left")
        self.note.pack(anchor="w", **pad)

    def _send(self, method, *args):
        """Hand a background result to the UI thread."""
        self.app.events.put(("country", self.code, method, args))

    # -- loading and checking
    def load(self):
        self.loaded = True
        self.app.run_bg(lambda: load_country_channels(self.code), self._loaded,
                        f"Loading {self.name} channels...")

    def _loaded(self, outcome):
        self.channels, self.skipped = outcome
        replaced = self.app.cfg.get("replaced_links", {})
        for ch in self.channels:
            if ch["url"] in replaced:
                ch["orig_url"], ch["url"] = ch["url"], replaced[ch["url"]]
        self.by_id = {ch["id"]: ch for ch in self.channels}
        groups = sorted({g.strip() for ch in self.channels for g in ch["group"].split(",")})
        self.category_box.configure(values=[self.ALL] + groups)
        if self.category.get() not in groups:
            self.category.set(self.ALL)
        self.app.status.configure(text=f"{len(self.channels)} {self.name} channels")
        self.note.configure(text=(
            f"{len(self.channels)} free channels listed by the iptv-org project (github.com/iptv-org/iptv)"
            + (f"; {self.skipped} unofficial rebroadcasts left out" if self.skipped else "")
            + ". Each stream is tried from your connection: green plays here, red is blocked outside its "
            "country (a VPN set to that country may help), grey is offline. \"Find new links\" looks for "
            "working replacements. Recordings go in the \"Live\" folder inside your save folder."))
        self.stop.set()  # drop checks still running for the previous list
        self.gen, self.stop, self.searching = next(LIST_LOADS), threading.Event(), 0
        self.fix_btn.configure(state="normal")
        self.show()
        self._show_progress()
        gen = self.gen
        check_streams(self.channels, lambda cid, result: self._send("_checked", gen, cid, result), self.stop)

    def _checked(self, gen, cid, result):
        if gen != self.gen:
            return
        self.by_id[cid]["status"] = result
        self._update_row(self.by_id[cid])
        self._show_progress()

    def _show_progress(self):
        statuses = [ch.get("status") for ch in self.channels]
        done = sum(s in CHECKED for s in statuses)
        if self.searching:
            self.progress.configure(text=f"Finding new links: {self.searching} to go")
        elif done < len(statuses):
            self.progress.configure(text=f"Checking streams {done}/{len(statuses)}")
        else:
            red = statuses.count("geo") + statuses.count("blocked")
            self.progress.configure(text=f"● {statuses.count('ok')} play here   ● {red} blocked   "
                                         f"● {statuses.count('offline')} offline")
            if self.playable_only.get():
                self.show()

    # -- the list
    def show(self):
        selected = self.tree.selection()
        text, category = self.filter.get().strip().lower(), self.category.get()
        self.tree.delete(*self.tree.get_children())
        for ch in self.channels:
            if text and text not in ch["title"].lower():
                continue
            if category != self.ALL and category not in [g.strip() for g in ch["group"].split(",")]:
                continue
            if self.playable_only.get() and ch.get("status") != "ok":
                continue
            colour, label = STATUS[ch.get("status")]
            rec = self.app.recorders.get(ch["id"])
            self.tree.insert("", "end", iid=ch["id"], text=label, image=self.app.dots[colour], values=(
                ch["title"], ch["group"], ch["quality"], ch["notes"], "● REC" if rec and rec.is_alive() else ""))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def _update_row(self, ch):
        if not self.tree.exists(ch["id"]):
            return
        if self.playable_only.get() and ch.get("status") not in ("ok", None, "searching"):
            self.tree.delete(ch["id"])
            return
        colour, label = STATUS[ch.get("status")]
        self.tree.item(ch["id"], text=label, image=self.app.dots[colour])

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Pick a channel first.")
            return None
        return self.by_id[sel[0]]

    # -- fixing dead links
    def find_new_links(self):
        targets = [ch for ch in self.channels if ch.get("status") in ("geo", "blocked", "offline")]
        if not targets:
            messagebox.showinfo(APP_NAME, "Every channel checked so far plays here." if self.channels
                                else "Wait for the channel list to load, then try again.")
            return
        self._relink(targets)

    def find_new_link(self):
        ch = self.selected()
        if ch and ch.get("status") != "searching":
            self._relink([ch])

    def _relink(self, targets):
        gen, stop = self.gen, self.stop
        for ch in targets:
            ch["was"], ch["status"] = ch.get("status"), "searching"
            self._update_row(ch)
        self.searching += len(targets)
        self.fix_btn.configure(state="disabled")
        self._show_progress()
        self.app.log(f"Looking for new links for {len(targets)} {self.name} channel(s)...")

        def one(ch):
            try:
                url = find_new_link(ch)
            except Exception as exc:
                trace(f"find_new_link {ch['title']}: {exc}")
                url = None
            self._send("_relinked", gen, ch["id"], url)
        in_parallel(targets, one, stop, workers=6)

    def _relinked(self, gen, cid, url):
        if gen != self.gen:
            return
        ch = self.by_id[cid]
        self.searching -= 1
        if url:
            if url != ch["url"]:
                orig = ch.setdefault("orig_url", ch["url"])
                ch["url"] = url
                self.app.cfg.setdefault("replaced_links", {})[orig] = url
                self.app._snapshot_cfg()
                self.app.log(f"New link for {ch['title']}: {url}")
            ch["status"] = "ok"
        else:
            ch["status"] = ch.get("was") or "offline"
        self._update_row(ch)
        if not self.searching:
            self.fix_btn.configure(state="normal")
            self.app.log(f"Finished looking for new {self.name} links.")
        self._show_progress()

    # -- actions
    def watch_in_vlc(self):
        ch, vlc = self.selected(), find_vlc()
        if ch and vlc:
            subprocess.Popen([vlc, ch["url"], f":meta-title={ch['title']}"])
            self.app.status.configure(text=f"Opened {ch['title']} in VLC")

    def copy_link(self):
        ch = self.selected()
        if ch:
            self.app._copy(ch["url"], f"{ch['title']} stream link")

    def start_recording(self):
        ch = self.selected()
        if ch:
            self.app.record(ch, self.rec_minutes.get(), self.tree)

    def stop_recording(self):
        ch = self.selected()
        if ch:
            self.app.stop_record(ch, self.tree)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1150x760")
        self.minsize(860, 600)
        self.cfg = load_config()
        self.events = queue.Queue()
        self.programmes, self.episodes = [], []
        self.checked = set()
        self.worker = None
        self.job_rows = []
        self.everywhere_results = []
        self.live = []
        self.recorders = {}
        self.country_tabs = {}
        self.countries = {}  # every country iptv-org lists, loaded when adding a tab
        self.dots = {name: self._dot(colour) for name, colour in (
            ("green", "#2e9d42"), ("red", "#d93025"), ("grey", "#9aa0a6"), ("amber", "#f0ad00"))}

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)
        trace("window ready")
        if not find_ffmpeg():
            self.log("Warning: ffmpeg not found - downloads cannot be merged. Install it with: "
                     "winget install Gyan.FFmpeg")

    # -- layout
    @staticmethod
    def _dot(colour, size=12):
        img = tk.PhotoImage(width=size, height=size)
        r = size / 2
        for y in range(size):
            for x in range(size):
                if (x + 0.5 - r) ** 2 + (y + 0.5 - r) ** 2 <= (r - 1) ** 2:
                    img.put(colour, (x, y))
        return img

    def _build(self):
        pad = {"padx": 8, "pady": 4}

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, **pad)
        self.iplayer_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.iplayer_tab, text="  BBC iPlayer downloads  ")
        everywhere_tab = ttk.Frame(self.tabs)
        self.tabs.add(everywhere_tab, text="  Search all channels  ")
        self.live_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.live_tab, text="  Live BBC TV  ")
        for code, name in self.cfg["countries"]:
            self._add_country_tab(code, name)
        self.add_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.add_tab, text="  +  ")
        self._last_tab = str(self.iplayer_tab)
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        self.tabs.bind("<Button-3>", self._on_tab_right_click)
        self._build_everywhere(everywhere_tab, pad)
        self._build_live(self.live_tab, pad)

        top = ttk.Frame(self.iplayer_tab)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Search or paste an iPlayer link:").pack(side="left")
        self.query = ttk.Entry(top)
        self.query.pack(side="left", fill="x", expand=True, padx=6)
        self.query.bind("<Return>", lambda e: self.search())
        self.search_btn = ttk.Button(top, text="Search", command=self.search)
        self.search_btn.pack(side="left")
        self.query.focus_set()

        panes = ttk.PanedWindow(self.iplayer_tab, orient="horizontal")
        panes.pack(fill="both", expand=True, **pad)

        left = ttk.Frame(panes)
        ttk.Label(left, text="Programmes").pack(anchor="w")
        self.prog_list = ttk.Treeview(left, columns=("title", "channel"), show="headings",
                                      selectmode="browse")
        self.prog_list.heading("title", text="Title")
        self.prog_list.heading("channel", text="Channel")
        self.prog_list.column("title", width=220)
        self.prog_list.column("channel", width=80)
        self.prog_list.pack(fill="both", expand=True)
        self.prog_list.bind("<<TreeviewSelect>>", lambda e: self.load_selected_programme())
        panes.add(left, weight=1)

        right = ttk.Frame(panes)
        head = ttk.Frame(right)
        head.pack(fill="x")
        ttk.Label(head, text="Episodes  (click or press Space to tick)").pack(side="left")
        ttk.Button(head, text="None", width=6, command=lambda: self.tick_all(False)).pack(side="right")
        ttk.Button(head, text="All", width=6, command=lambda: self.tick_all(True)).pack(side="right")
        ep_copy_btn = ttk.Menubutton(head, text="Copy links ▾")
        ep_copy_btn["menu"] = self._episode_copy_menu(ep_copy_btn)
        ep_copy_btn.pack(side="right", padx=8)
        cols = ("tick", "episode", "duration", "available")
        self.ep_list = ttk.Treeview(right, columns=cols, show="headings", selectmode="browse")
        for col, text, width, stretch in (("tick", "", 30, False), ("episode", "Episode", 360, True),
                                          ("duration", "Length", 70, False),
                                          ("available", "Available", 150, False)):
            self.ep_list.heading(col, text=text)
            self.ep_list.column(col, width=width, stretch=stretch, anchor="center" if col == "tick" else "w")
        self.ep_list.pack(fill="both", expand=True)
        self.ep_list.bind("<ButtonRelease-1>", self._on_episode_click)
        self.ep_list.bind("<space>", lambda e: self._toggle(self.ep_list.focus()))
        self.ep_list.bind("<<TreeviewSelect>>", lambda e: self._show_synopsis())
        ep_menu = self._episode_copy_menu(self)

        def ep_popup(event):
            row = self.ep_list.identify_row(event.y)
            if row:
                self.ep_list.selection_set(row)
                ep_menu.tk_popup(event.x_root, event.y_root)
        self.ep_list.bind("<Button-3>", ep_popup)
        self.synopsis = ttk.Label(right, text="", wraplength=600, foreground="#555")
        self.synopsis.pack(fill="x", pady=(4, 0))
        panes.add(right, weight=3)

        opts = ttk.Frame(self)
        opts.pack(fill="x", **pad)
        ttk.Label(opts, text="Save to:").pack(side="left")
        self.save_dir = tk.StringVar(value=self.cfg["save_dir"])
        ttk.Entry(opts, textvariable=self.save_dir, width=45).pack(side="left", padx=4)
        ttk.Button(opts, text="Browse...", command=self.choose_dir).pack(side="left")
        ttk.Label(opts, text="  Quality:").pack(side="left")
        self.quality = tk.StringVar(value=self.cfg["quality"])
        ttk.Combobox(opts, textvariable=self.quality, values=list(QUALITIES), width=14,
                     state="readonly").pack(side="left", padx=4)
        self.subs = tk.BooleanVar(value=self.cfg["subtitles"])
        ttk.Checkbutton(opts, text="Subtitles", variable=self.subs).pack(side="left", padx=6)

        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        self.download_btn = ttk.Button(actions, text="Download ticked episodes", command=self.download)
        self.download_btn.pack(side="left")
        self.cancel_btn = ttk.Button(actions, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)
        self.overall = ttk.Progressbar(actions, mode="determinate")
        self.overall.pack(side="left", fill="x", expand=True, padx=6)
        self.status = ttk.Label(actions, text="", width=58)
        self.status.pack(side="left")

        self.logbox = tk.Text(self, height=6, state="disabled", wrap="word")
        self.logbox.pack(fill="x", **pad)

    def _build_everywhere(self, tab, pad):
        top = ttk.Frame(tab)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Search BBC iPlayer, ITVX, Channel 4, My5, STV Player and U:").pack(side="left")
        self.all_query = ttk.Entry(top)
        self.all_query.pack(side="left", fill="x", expand=True, padx=6)
        self.all_query.bind("<Return>", lambda e: self.search_everywhere())
        self.all_search_btn = ttk.Button(top, text="Search", command=self.search_everywhere)
        self.all_search_btn.pack(side="left")

        cols = ("service", "title", "episodes", "about")
        self.all_list = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        for col, text, width, stretch in (("service", "Channel", 110, False), ("title", "Programme", 260, False),
                                          ("episodes", "Episodes", 70, False), ("about", "About", 500, True)):
            self.all_list.heading(col, text=text)
            self.all_list.column(col, width=width, stretch=stretch)
        self.all_list.pack(fill="both", expand=True, **pad)
        self.all_list.bind("<Double-1>", lambda e: self.open_everywhere_result())
        self.all_list.bind("<Return>", lambda e: self.open_everywhere_result())

        bottom = ttk.Frame(tab)
        bottom.pack(fill="x", **pad)
        ttk.Button(bottom, text="Open", command=self.open_everywhere_result).pack(side="left")
        ttk.Label(bottom, foreground="#555", wraplength=820, justify="left", text=(
            "Double-click a result. BBC iPlayer programmes open in the downloads tab. Other channels open on "
            "their own website: their programmes are DRM-protected, so this app can't download them."
        )).pack(side="left", padx=10)

    def _build_live(self, tab, pad):
        top = ttk.Frame(tab)
        top.pack(fill="x", **pad)
        ttk.Button(top, text="Refresh", command=self.refresh_live).pack(side="left")
        ttk.Button(top, text="Watch in browser", command=self.watch_in_browser).pack(side="left", padx=(12, 0))
        self.vlc_btn = ttk.Button(top, text="Watch in VLC", command=self.watch_in_vlc,
                                  state="normal" if find_vlc() else "disabled")
        self.vlc_btn.pack(side="left", padx=4)
        copy_btn = ttk.Menubutton(top, text="Copy link ▾")
        copy_btn["menu"] = self._live_copy_menu(copy_btn)
        copy_btn.pack(side="left", padx=4)
        ttk.Button(top, text="Save VLC playlist", command=self.save_live_playlist).pack(side="left", padx=4)
        ttk.Label(top, text="    Record for").pack(side="left")
        self.rec_minutes = tk.StringVar(value="0")
        ttk.Spinbox(top, from_=0, to=600, increment=15, width=5, textvariable=self.rec_minutes).pack(side="left", padx=4)
        ttk.Label(top, text="min (0 = until stopped)").pack(side="left")
        ttk.Button(top, text="● Record", command=self.start_recording).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="■ Stop recording", command=self.stop_recording).pack(side="left", padx=4)

        cols = ("channel", "now", "next", "rec")
        self.live_list = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        for col, text, width, stretch in (("channel", "Channel", 130, False), ("now", "On now", 380, True),
                                          ("next", "Next", 330, True), ("rec", "Recording", 150, False)):
            self.live_list.heading(col, text=text)
            self.live_list.column(col, width=width, stretch=stretch)
        self.live_list.pack(fill="both", expand=True, **pad)
        self.live_list.bind("<Double-1>", lambda e: self.watch_in_vlc() if find_vlc() else self.watch_in_browser())

        menu = self._live_copy_menu(self)
        menu.add_separator()
        menu.add_command(label="Watch in browser", command=self.watch_in_browser)
        menu.add_command(label="Watch in VLC", command=self.watch_in_vlc,
                         state="normal" if find_vlc() else "disabled")

        def popup(event):
            row = self.live_list.identify_row(event.y)
            if row:
                self.live_list.selection_set(row)
                menu.tk_popup(event.x_root, event.y_root)
        self.live_list.bind("<Button-3>", popup)

        ttk.Label(tab, foreground="#555", text=(
            "Right-click a channel to copy its links. Recordings are saved in a \"Live\" folder inside your "
            "save folder. Live TV is 720p and only works from a UK connection."
        )).pack(anchor="w", **pad)

    def _live_copy_menu(self, parent):
        menu = tk.Menu(parent, tearoff=False)
        menu.add_command(label="Copy HLS manifest (.m3u8) - for VLC and most players", command=self.copy_stream_link)
        menu.add_command(label="Copy DASH manifest (.mpd)", command=self.copy_dash_link)
        menu.add_command(label="Copy iPlayer page link", command=self.copy_page_link)
        return menu

    def _episode_copy_menu(self, parent):
        menu = tk.Menu(parent, tearoff=False)
        menu.add_command(label="Copy HLS manifest (.m3u8)", command=lambda: self.copy_episode_link("hls"))
        menu.add_command(label="Copy DASH manifest (.mpd)", command=lambda: self.copy_episode_link("dash"))
        menu.add_command(label="Copy iPlayer page link", command=lambda: self.copy_episode_link("page"))
        menu.add_separator()
        menu.add_command(label="Copy all links for ticked episodes", command=self.copy_ticked_links)
        return menu

    def _on_tab_changed(self, _event):
        current = self.tabs.select()
        if current == str(self.live_tab) and not self.live:
            self.refresh_live()
        elif current == str(self.add_tab):
            self.tabs.select(self._last_tab)
            self.after_idle(self.choose_country)
            return
        else:
            tab = next((t for t in self.country_tabs.values() if str(t) == current), None)
            if tab and not tab.loaded:
                tab.load()
        self._last_tab = current

    # -- country tabs
    def _add_country_tab(self, code, name):
        tab = CountryTab(self, code, name)
        self.country_tabs[code] = tab
        if hasattr(self, "add_tab"):
            self.tabs.insert(self.add_tab, tab, text=f"  {name}  ")
        else:
            self.tabs.add(tab, text=f"  {name}  ")
        return tab

    def _save_countries(self):
        self.cfg["countries"] = [[t.code, t.name] for t in self.country_tabs.values()]
        self._snapshot_cfg()

    def choose_country(self):
        if not self.countries:
            def got(countries):
                self.countries = countries
                self.choose_country()
            self.run_bg(load_countries, got, "Loading countries...")
            return
        win = tk.Toplevel(self)
        win.title("Add a country")
        win.transient(self)
        win.geometry("320x420")
        ttk.Label(win, text="Type to search, then double-click a country:").pack(anchor="w", padx=8, pady=(8, 2))
        query = tk.StringVar()
        entry = ttk.Entry(win, textvariable=query)
        entry.pack(fill="x", padx=8)
        box = tk.Listbox(win, activestyle="dotbox")
        box.pack(fill="both", expand=True, padx=8, pady=6)
        choices = []

        def refresh(*_):
            q = query.get().strip().lower()
            choices[:] = sorted((name, code) for code, name in self.countries.items()
                                if code not in self.country_tabs and (q in name.lower() or q == code.lower()))
            box.delete(0, "end")
            for name, _ in choices:
                box.insert("end", name)
            if choices:
                box.selection_set(0)

        def pick(*_):
            sel = box.curselection()
            if not sel:
                return
            name, code = choices[sel[0]]
            win.destroy()
            short = {"United Kingdom": "UK", "United States": "USA"}.get(name, name)
            self.tabs.select(self._add_country_tab(code, short))
            self._save_countries()
        query.trace_add("write", refresh)
        entry.bind("<Return>", pick)
        entry.bind("<Down>", lambda e: box.focus_set())
        box.bind("<Double-1>", pick)
        box.bind("<Return>", pick)
        ttk.Button(win, text="Add tab", command=pick).pack(pady=(0, 8))
        refresh()
        entry.focus_set()

    def _on_tab_right_click(self, event):
        try:
            index = self.tabs.index(f"@{event.x},{event.y}")
        except tk.TclError:
            return
        tab = next((t for t in self.country_tabs.values() if self.tabs.index(t) == index), None)
        if not tab:
            return
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label=f"Close {tab.name} tab", command=lambda: self.close_country(tab))
        menu.add_command(label="Add a country...", command=self.choose_country)
        menu.tk_popup(event.x_root, event.y_root)

    def close_country(self, tab):
        if any(r.is_alive() for cid, r in self.recorders.items() if cid.startswith(tab.code + ":")):
            messagebox.showinfo(APP_NAME, f"Stop the {tab.name} recordings before closing the tab.")
            return
        if self.tabs.select() == str(tab):
            self.tabs.select(self.live_tab)
        tab.stop.set()
        self.tabs.forget(tab)
        del self.country_tabs[tab.code]
        tab.destroy()
        self._save_countries()

    def playlist_dialog(self, preselect=None):
        win = tk.Toplevel(self)
        win.title("Make a VLC playlist")
        win.transient(self)
        win.resizable(False, False)
        left = ttk.Frame(win)
        left.grid(row=0, column=0, sticky="nw", padx=10, pady=10)
        right = ttk.Frame(win)
        right.grid(row=0, column=1, sticky="ns", padx=(6, 10), pady=10)

        ttk.Label(left, text="Countries to include:").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))
        rows = {}
        for i, (code, tab) in enumerate(self.country_tabs.items()):
            rows[code] = r = {"name": tab.name, "pick": tk.BooleanVar(value=code == preselect),
                              "channels": tab.channels or None, "groups": [], "counts": {},
                              "chosen": None,  # None = every category
                              "summary": ttk.Label(left, text="Loading...", foreground="#555", width=24)}
            ttk.Checkbutton(left, text=tab.name, variable=r["pick"]).grid(row=1 + i, column=0, sticky="w",
                                                                         padx=(8, 6), pady=2)
            r["summary"].grid(row=1 + i, column=1, sticky="w")
            ttk.Button(left, text="Categories ›", command=lambda c=code: show_categories(c)).grid(
                row=1 + i, column=2, padx=(6, 0))
        n = len(rows)
        bbc = tk.BooleanVar(value=False)
        ttk.Checkbutton(left, text="BBC live channels (from the Live BBC TV tab)", variable=bbc).grid(
            row=n + 1, column=0, columnspan=3, sticky="w", pady=(12, 2))
        only_ok = tk.BooleanVar(value=True)
        ttk.Checkbutton(left, text="Only channels that play here", variable=only_ok).grid(
            row=n + 2, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(left, foreground="#555", wraplength=380, justify="left", text=(
            "Add more countries with the + tab. Each country shows as its own group in VLC (Ctrl+L).")).grid(
            row=n + 3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        cat_title = ttk.Label(right, text="Categories")
        cat_title.pack(anchor="w")
        lists = ttk.Frame(right)
        lists.pack(fill="both", expand=True, pady=4)
        cat_list = tk.Listbox(lists, selectmode="multiple", exportselection=False, width=34, height=16,
                              activestyle="none")
        scroll = ttk.Scrollbar(lists, orient="vertical", command=cat_list.yview)
        cat_list.configure(yscrollcommand=scroll.set)
        cat_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        cat_buttons = ttk.Frame(right)
        cat_buttons.pack(anchor="w")
        ttk.Label(right, foreground="#555", text="Click categories to tick or untick them.").pack(anchor="w", pady=(4, 0))
        current = [preselect if preselect in rows else next(iter(rows), None)]

        def summary(code):
            r = rows[code]
            chosen, total = r["chosen"], len(r["groups"])
            if chosen is None or len(chosen) == total:
                text = "All categories"
            elif not chosen:
                text = "No categories"
            elif len(chosen) == 1:
                text = next(iter(chosen))
            else:
                text = f"{len(chosen)} of {total} categories"
            r["summary"].configure(text=text)

        def show_categories(code):
            current[0] = code
            r = rows[code]
            cat_title.configure(text=f"{r['name']} categories" + ("" if r["groups"] else " (loading...)"))
            cat_list.delete(0, "end")
            for g in r["groups"]:
                cat_list.insert("end", f"{g} ({r['counts'][g]})")
                if r["chosen"] is None or g in r["chosen"]:
                    cat_list.selection_set("end")

        def on_select(_event=None):
            r = rows[current[0]]
            if not r["groups"]:
                return
            r["chosen"] = {r["groups"][i] for i in cat_list.curselection()}
            if r["chosen"]:
                r["pick"].set(True)
            summary(current[0])

        def select_all(on):
            (cat_list.selection_set if on else cat_list.selection_clear)(0, "end")
            on_select()
        cat_list.bind("<<ListboxSelect>>", on_select)
        ttk.Button(cat_buttons, text="All", width=6, command=lambda: select_all(True)).pack(side="left")
        ttk.Button(cat_buttons, text="None", width=6, command=lambda: select_all(False)).pack(side="left", padx=4)

        def got(code, channels):
            if not win.winfo_exists():
                return
            r = rows[code]
            r["channels"] = channels
            r["counts"] = collections.Counter(g.strip() for ch in channels for g in ch["group"].split(","))
            r["groups"] = sorted(r["counts"])
            summary(code)
            if current[0] == code:
                show_categories(code)
        for code, r in rows.items():
            if r["channels"]:
                got(code, r["channels"])
            else:  # tab not opened yet: fetch its list just for the categories
                self.run_bg(lambda c=code: load_country_channels(c)[0], lambda chs, c=code: got(c, chs),
                            f"Loading {r['name']} categories...")
        if current[0]:
            show_categories(current[0])

        def save():
            chosen = [(code, r) for code, r in rows.items() if r["pick"].get() and r["chosen"] != set()]
            if not chosen and not bbc.get():
                messagebox.showinfo(APP_NAME, "Tick at least one country with at least one category.", parent=win)
                return
            names = [r["name"] for _, r in chosen] + (["BBC"] if bbc.get() else [])
            path = filedialog.asksaveasfilename(
                parent=win, title="Save VLC playlist", initialdir=self.save_dir.get() or str(Path.home()),
                initialfile=(names[0] if len(names) == 1 else "World") + " TV.m3u", defaultextension=".m3u",
                filetypes=[("Playlist", "*.m3u"), ("All files", "*.*")])
            if not path:
                return
            win.destroy()
            countries = [(code, r["name"], r["channels"],
                          None if r["chosen"] is None or len(r["chosen"]) == len(r["groups"]) else set(r["chosen"]))
                         for code, r in chosen]
            bbc_channels = list(self.live) if bbc.get() else None
            replaced, playable = dict(self.cfg.get("replaced_links", {})), only_ok.get()

            def saved(outcome):
                text, count = outcome
                Path(path).write_text(text, encoding="utf-8")
                self.status.configure(text=f"Saved playlist with {count} channels")
                self.log(f"Saved VLC playlist with {count} channels ({', '.join(names)}): {path}")
                vlc = find_vlc()
                if vlc and messagebox.askyesno(APP_NAME, f"Saved {count} channels.\n\nOpen the playlist in VLC now?"):
                    subprocess.Popen([vlc, path])
            self.run_bg(lambda: build_country_playlist(countries, playable, replaced, bbc_channels), saved,
                        "Building playlist" + (" and checking streams..." if playable else "..."))
        ttk.Button(left, text="Save playlist...", command=save).grid(row=n + 4, column=0, columnspan=3, sticky="e",
                                                                    pady=(12, 0))

    def _rec_view(self, cid):
        if ":" in cid:
            tab = self.country_tabs.get(cid.split(":")[0])
            return tab.tree if tab else None
        return self.live_list

    def _on_close(self):
        active = [r for r in self.recorders.values() if r.is_alive()]
        if active:
            if not messagebox.askyesno(APP_NAME, f"Stop {len(active)} recording(s) and quit?"):
                return
            for r in active:
                r.stop_event.set()
            for r in active:
                r.join(30)  # let ffmpeg close the file and convert it to .mp4
        trace("window closed by user")
        self.destroy()

    # -- search all channels
    def search_everywhere(self):
        text = self.all_query.get().strip()
        if not text:
            return
        self.all_search_btn.configure(state="disabled")
        self.run_bg(lambda: search_everywhere(text), self._show_everywhere, "Searching all channels...")

    def _show_everywhere(self, outcome):
        results, errors = outcome
        self.all_search_btn.configure(state="normal")
        for err in errors:
            self.log(err)
        self.everywhere_results = results
        self.all_list.delete(*self.all_list.get_children())
        for i, r in enumerate(results):
            self.all_list.insert("", "end", iid=str(i),
                                 values=(r["service"], r["title"], r["episodes"], r["about"]))
        services = sorted({r["service"] for r in results})
        self.status.configure(text=f"{len(results)} result(s) from {len(services)} channel(s)")

    def open_everywhere_result(self):
        sel = self.all_list.selection()
        if not sel:
            return
        r = self.everywhere_results[int(sel[0])]
        if r["pid"]:
            # BBC: show it in the downloads tab, ready to tick and download.
            self.tabs.select(self.iplayer_tab)
            self.query.delete(0, "end")
            self.query.insert(0, r["url"])
            self.prog_list.delete(*self.prog_list.get_children())
            self.synopsis.configure(text=r["about"])
            self.run_bg(lambda: list_episodes(r["pid"]), self._show_episodes, "Loading episodes...")
        else:
            webbrowser.open(r["url"])

    # -- live TV
    def refresh_live(self):
        self.run_bg(load_live_channels, self._show_live, "Loading live channels...")

    def _show_live(self, channels):
        selected = self.live_list.selection()
        self.live = channels
        self.live_list.delete(*self.live_list.get_children())
        for ch in channels:
            rec = self.recorders.get(ch["id"])
            self.live_list.insert("", "end", iid=ch["id"], values=(
                ch["title"], ch["now"], ch["next"], "● REC" if rec and rec.is_alive() else ""))
        if selected and self.live_list.exists(selected[0]):
            self.live_list.selection_set(selected[0])
        self.status.configure(text=f"{len(channels)} live channels")

    def _selected_channel(self):
        sel = self.live_list.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Pick a channel first.")
            return None
        return next(ch for ch in self.live if ch["id"] == sel[0])

    def watch_in_browser(self):
        ch = self._selected_channel()
        if ch:
            webbrowser.open(live_page_url(ch["id"]))

    def watch_in_vlc(self):
        ch = self._selected_channel()
        vlc = find_vlc()
        if not ch or not vlc:
            return

        def launch():
            master, _, _ = live_stream_urls(ch["id"])
            subprocess.Popen([vlc, master, f":meta-title={ch['title']}"])
        self.run_bg(launch, lambda _: self.status.configure(text=f"Opened {ch['title']} in VLC"),
                    f"Opening {ch['title']}...")

    def _copy(self, text, what):
        # Tk empties the clipboard when the app closes, so use Windows' own clipboard where possible.
        if not copy_to_windows_clipboard(text):
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
        self.status.configure(text=f"Copied {what}")
        self.log(f"Copied {what}: {text}")

    def copy_stream_link(self):
        ch = self._selected_channel()
        if not ch:
            return
        self.run_bg(lambda: live_stream_urls(ch["id"])[0],
                    lambda url: self._copy(url, f"{ch['title']} stream link"),
                    f"Getting {ch['title']} stream link...")

    def copy_dash_link(self):
        ch = self._selected_channel()
        if not ch:
            return
        self.run_bg(lambda: live_dash_url(ch["id"]),
                    lambda url: self._copy(url, f"{ch['title']} DASH manifest"),
                    f"Getting {ch['title']} DASH manifest...")

    def copy_episode_link(self, kind):
        sel = self.ep_list.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Click an episode first.")
            return
        ep = self.episodes[int(sel[0])]
        label = ep["subtitle"] or ep["title"]
        if kind == "page":
            self._copy(episode_url(ep["id"]), f"iPlayer link for {label}")
            return
        name = {"hls": "HLS manifest", "dash": "DASH manifest"}[kind]

        def got(found):
            if kind in found:
                self._copy(found[kind], f"{name} for {label} (signed - works for a few hours)")
            else:
                self.log(f"No {name} offered for {label}.")
        self.run_bg(lambda: episode_manifests(ep["id"]), got, f"Getting {name} for {label}...")

    def copy_ticked_links(self):
        eps = [self.episodes[int(r)] for r in sorted(self.checked, key=int)]
        if not eps:
            messagebox.showinfo(APP_NAME, "Tick at least one episode first.")
            return

        def collect():
            blocks = []
            for ep in eps:
                found = episode_manifests(ep["id"])
                lines = [f"# {ep['title']} - {ep['subtitle']}" if ep["subtitle"] else f"# {ep['title']}",
                         episode_url(ep["id"])]
                lines += [f"{k.upper()}: {found[k]}" for k in ("hls", "dash") if k in found]
                blocks.append("\n".join(lines))
            return "\n\n".join(blocks) + "\n"
        self.run_bg(collect, lambda text: self._copy(text, f"links for {len(eps)} episode(s)"),
                    f"Getting links for {len(eps)} episode(s)...")

    def save_live_playlist(self, path=None):
        if not self.live:
            messagebox.showinfo(APP_NAME, "Wait for the channel list to load, then try again.")
            return
        if path is None:
            path = filedialog.asksaveasfilename(
                title="Save VLC playlist", initialdir=self.save_dir.get() or str(Path.home()),
                initialfile="BBC Live TV.m3u", defaultextension=".m3u",
                filetypes=[("Playlist", "*.m3u"), ("All files", "*.*")])
            if not path:
                return

        def saved(outcome):
            text, missing = outcome
            Path(path).write_text(text, encoding="utf-8")
            count = text.count("#EXTINF")
            self.status.configure(text=f"Saved playlist with {count} channels")
            self.log(f"Saved VLC playlist with {count} channels: {path}")
            if missing:
                self.log("Left out (no stream right now): " + ", ".join(missing))
            vlc = find_vlc()
            if vlc and messagebox.askyesno(APP_NAME, f"Saved {count} channels.\n\nOpen the playlist in VLC now?"):
                subprocess.Popen([vlc, path])
        channels = list(self.live)
        self.run_bg(lambda: build_live_playlist(channels), saved, "Building playlist...")

    def copy_page_link(self):
        ch = self._selected_channel()
        if ch:
            self._copy(live_page_url(ch["id"]), f"{ch['title']} iPlayer page link")

    def start_recording(self):
        ch = self._selected_channel()
        if ch:
            self.record(ch, self.rec_minutes.get(), self.live_list)

    def stop_recording(self):
        ch = self._selected_channel()
        if ch:
            self.stop_record(ch, self.live_list)

    def record(self, ch, minutes_text, view):
        if ch["id"] in self.recorders and self.recorders[ch["id"]].is_alive():
            messagebox.showinfo(APP_NAME, f"{ch['title']} is already recording.")
            return
        try:
            minutes = max(0, int(float(minutes_text or 0)))
        except ValueError:
            minutes = 0
        cfg = self._snapshot_cfg()
        rec = LiveRecorder(ch, minutes, cfg["save_dir"], self.events)
        self.recorders[ch["id"]] = rec
        view.set(ch["id"], "rec", "Starting...")
        self.log(f"Recording {ch['title']}" + (f" for {minutes} min" if minutes else " until you stop it"))
        rec.start()

    def stop_record(self, ch, view):
        rec = self.recorders.get(ch["id"])
        if rec and rec.is_alive():
            rec.stop_event.set()
            view.set(ch["id"], "rec", "Stopping...")
        else:
            messagebox.showinfo(APP_NAME, f"{ch['title']} isn't recording.")

    def report_callback_exception(self, exc, val, tb):
        import traceback
        trace("UI error:\n" + "".join(traceback.format_exception(exc, val, tb)))
        self.log(f"Error: {val}")

    # -- helpers
    def log(self, msg):
        trace(msg)
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def run_bg(self, fn, done, busy_text):
        self.status.configure(text=busy_text)
        self.search_btn.configure(state="disabled")

        def work():
            try:
                result, error = fn(), None
            except Exception as exc:
                result, error = None, exc
            self.events.put(("call", done, result, error))
        threading.Thread(target=work, daemon=True).start()

    def _snapshot_cfg(self):
        self.cfg.update(save_dir=self.save_dir.get().strip(), quality=self.quality.get(),
                        subtitles=self.subs.get())
        save_config(self.cfg)
        return dict(self.cfg)

    # -- search / list
    def search(self):
        text = self.query.get().strip()
        if not text:
            return
        pid_match = PID_RE.search(text) if ("bbc.co.uk" in text or PID_RE.fullmatch(text)) else None
        if pid_match:
            pid = pid_match.group(1)
            self.prog_list.delete(*self.prog_list.get_children())
            self.run_bg(lambda: list_episodes(pid), self._show_episodes, "Loading episodes...")
        else:
            self.run_bg(lambda: search_programmes(text), self._show_programmes, "Searching...")

    def _show_programmes(self, results):
        self.programmes = results
        self.prog_list.delete(*self.prog_list.get_children())
        for i, p in enumerate(results):
            self.prog_list.insert("", "end", iid=str(i), values=(p["title"], p["channel"]))
        self.status.configure(text=f"{len(results)} programme(s) found")
        if not results:
            self.log("No programmes found. iPlayer search only covers programmes available now.")

    def load_selected_programme(self):
        sel = self.prog_list.selection()
        if not sel:
            return
        prog = self.programmes[int(sel[0])]
        self.synopsis.configure(text=prog["synopsis"])
        self.run_bg(lambda: list_episodes(prog["id"]), self._show_episodes, "Loading episodes...")

    def _show_episodes(self, episodes):
        self.episodes = episodes
        self.checked.clear()
        self.ep_list.delete(*self.ep_list.get_children())
        for i, ep in enumerate(episodes):
            self.ep_list.insert("", "end", iid=str(i),
                                values=("☐", ep["subtitle"] or ep["title"], ep["duration"], ep["availability"]))
        self.status.configure(text=f"{len(episodes)} episode(s)")

    def _on_episode_click(self, event):
        row = self.ep_list.identify_row(event.y)
        if row and self.ep_list.identify_region(event.x, event.y) == "cell":
            self._toggle(row)

    def _toggle(self, row, value=None):
        if not row:
            return
        on = (row not in self.checked) if value is None else value
        (self.checked.add if on else self.checked.discard)(row)
        self.ep_list.set(row, "tick", "☑" if on else "☐")

    def tick_all(self, value):
        for row in self.ep_list.get_children():
            self._toggle(row, value)

    def _show_synopsis(self):
        sel = self.ep_list.selection()
        if sel:
            self.synopsis.configure(text=self.episodes[int(sel[0])]["synopsis"])

    def choose_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.save_dir.get() or str(Path.home()))
        if chosen:
            self.save_dir.set(chosen)

    # -- downloading
    def download(self):
        if self.worker and self.worker.is_alive():
            return
        jobs = [self.episodes[int(r)] for r in sorted(self.checked, key=int)]
        if not jobs:
            messagebox.showinfo(APP_NAME, "Tick at least one episode first.")
            return
        cfg = self._snapshot_cfg()
        if not cfg["save_dir"]:
            messagebox.showerror(APP_NAME, "Choose a folder to save to.")
            return
        self.job_rows = [str(self.episodes.index(j)) for j in jobs]
        self.overall.configure(maximum=len(jobs) * 100, value=0)
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.log(f"Downloading {len(jobs)} episode(s) to {cfg['save_dir']}")
        self.worker = Downloader(jobs, cfg, self.events)
        self.worker.start()

    def cancel(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.configure(text="Cancelling...")

    def _poll_events(self):
        try:
            while True:
                kind, *args = self.events.get_nowait()
                if kind == "call":
                    done, result, error = args
                    self.search_btn.configure(state="normal")
                    self.all_search_btn.configure(state="normal")
                    if error:
                        self.status.configure(text="")
                        self.log(f"Error: {error}")
                    else:
                        done(result)
                elif kind == "progress":
                    i, pct, text = args
                    self.overall.configure(value=i * 100 + pct)
                    self.status.configure(text=f"[{i + 1}/{len(self.job_rows)}] {text}")
                elif kind == "status":
                    i, text = args
                    row = self.job_rows[i]
                    self.ep_list.set(row, "available", text)
                    if text in ("Done", "Failed", "Cancelled"):
                        self.overall.configure(value=(i + 1) * 100)
                elif kind == "log":
                    self.log(args[0])
                elif kind == "country":
                    code, method, call_args = args
                    if code in self.country_tabs:
                        getattr(self.country_tabs[code], method)(*call_args)
                elif kind == "rec":
                    cid, text = args
                    view = self._rec_view(cid)
                    if view and view.exists(cid):
                        view.set(cid, "rec", text)
                elif kind == "rec_done":
                    cid, text = args
                    view = self._rec_view(cid)
                    if view and view.exists(cid):
                        view.set(cid, "rec", "")
                    self.log(text)
                elif kind == "finished":
                    self.download_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self.status.configure(text="Finished")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)


def main():
    # Under pythonw there is no console, so record any startup crash where it can be found.
    try:
        App().mainloop()
    except Exception:
        import traceback
        trace("crash:\n" + traceback.format_exc())
        try:
            messagebox.showerror(APP_NAME, f"The app crashed. Details saved to:\n{LOG_PATH}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
