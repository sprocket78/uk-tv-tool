# UK TV Tool

A desktop app for UK free-to-air TV, for Windows and Linux:

- **BBC iPlayer downloads.** Search iPlayer, tick episodes and download them in up to 1080p with subtitles.
- **Search all channels.** One search across BBC iPlayer, ITVX, Channel 4, My5, STV Player and U.
- **Live BBC TV.** See what's on now and next on 11 BBC channels. Watch in a browser or VLC, record, copy stream links, or save a VLC playlist.
- **Country tabs.** Free live channels for the UK, Ireland, France, Germany and the USA, each in its own tab. Add any of 250 countries with the **+** tab.

It only downloads and records content that is not DRM-protected: BBC iPlayer and free, unencrypted live streams. Other broadcasters' programmes are found and linked to, never decrypted.

## Requirements

- Windows 10 or 11, or Linux: Ubuntu 18.04 or later (tested on 18.04, 20.04, 22.04, 24.04, 25.04, 25.10 and 26.04), Debian 12 and 13, Linux Mint 22, Fedora 43 and Arch
- A UK internet connection (iPlayer is UK-only)
- A TV licence, which you need to watch or download iPlayer, including live TV
- Python 3 with Tk, yt-dlp, ffmpeg and, for 1080p, get_iplayer. The setup scripts install all of them.
- VLC (optional), for **Watch in VLC** and the playlist

## Setup on Windows

In this folder, open PowerShell and run:

```bash
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

The script installs whatever is missing and skips anything already there:
- Python 3.12, yt-dlp and ffmpeg, through winget and pip.
- get_iplayer, from its official GitHub release with the checksum verified. Windows asks for permission for this one.

Then double-click **UK TV Tool.bat**.

<details>
<summary>Manual setup</summary>

```bash
winget install Python.Python.3.12
```

```bash
python -s -m pip install -r requirements.txt
```

```bash
winget install Gyan.FFmpeg
```

For 1080p, install get_iplayer from <https://github.com/get-iplayer/get_iplayer_win32/releases>. The app looks for it in `C:\Program Files\get_iplayer`.

Install yt-dlp with `-s` and **not** with `--user`. A per-user copy isn't visible when the app is double-clicked, and the app then closes immediately.
</details>

## Setup on Linux

In this folder, open a terminal and run:

```bash
./setup.sh
```

It works with apt (Ubuntu, Debian, Mint), dnf (Fedora) and pacman (Arch), and asks for your password to install system packages. It installs whatever is missing and skips anything already there:
- **System packages:** Python with Tk, ffmpeg, the Perl modules get_iplayer needs, and (if available) VLC, xclip and cron.
- **yt-dlp:** into a private Python environment in this folder (`.venv`), so it doesn't touch your system Python. yt-dlp needs Python 3.11 or newer; on older systems such as Ubuntu 22.04 and earlier, the script downloads a private Python 3.12 into `.tools` with [uv](https://github.com/astral-sh/uv) (official release, checksum verified). Running it again after a system upgrade is safe: it rebuilds `.venv` only if its Python is too old.
- **get_iplayer:** the latest release from its official GitHub repository, into `~/.local/bin`.
- **A menu shortcut:** **UK TV Tool** in your applications menu.

Then start **UK TV Tool** from the menu, or run `./uk-tv-tool.sh`.

Differences from Windows:
- Settings and `app.log` are in `~/.config/uk-tv-tool`.
- **Copy link** uses `wl-copy` (Wayland), `xclip` or `xsel`, so copied links stay on the clipboard after the app closes.
- **Daily update...** adds a line to your crontab, marked `# UK TV Tool - TV guide update`; the app only ever changes that line. Unlike Windows, cron doesn't catch up on a run missed while the computer was off, so pick a time it's usually on.
- On Fedora, `ffmpeg-free` is installed.
- On Arch, the Mojolicious Perl module isn't in the official repositories, so setup installs it from CPAN with `cpanm`.

## Using it

### BBC iPlayer downloads

- Search by name, or paste an iPlayer link (series or episode) or a programme id such as `m002d3lr`.
- Every available episode across all series is listed, with its length and how long it stays on iPlayer.
- Tick episodes (click, or press Space; or use **All** / **None**). Choose a quality and save folder, then press **Download ticked episodes**.
- Files are saved as `<save folder>\Doctor Who\Doctor Who - Season 2 - 8. The Reality War.mp4`. Subtitles are saved alongside as `.srt` if ticked.
- **Quality:**
  - **1080p** uses get_iplayer and takes the best the BBC offers for each episode: 1080p50 where it exists, otherwise 720p. That's about 4 GB per hour.
  - **720p and below** use yt-dlp.
- **Copy links ▾** (or right-click an episode) copies the episode's HLS (`.m3u8`) or DASH (`.mpd`) manifest, or its iPlayer page link. **Copy all links for ticked episodes** copies a list covering every ticked episode. Episode manifests are signed and stop working after a few hours.

### Search all channels

Double-click a result:
- **BBC iPlayer** results open in the downloads tab, ready to download.
- **Other channels** open on the broadcaster's website. Those services use Widevine DRM, so the app doesn't download them.

### Live BBC TV

- Channels: BBC One, Two, Three, Four, CBBC, CBeebies, BBC Scotland, BBC News, BBC Parliament, BBC ALBA and S4C, with now and next. Press **Refresh** to update.
- **Watch in browser** opens iPlayer's live page. **Watch in VLC**, or double-clicking a channel, plays it in VLC.
- **Copy link ▾** (or right-click) copies the HLS manifest, the DASH manifest or the iPlayer page link. Live links don't expire.
- **Save VLC playlist** writes an `.m3u` of every channel for VLC (show it with Ctrl+L), Kodi (PVR IPTV Simple Client) or IPTV apps.
- **● Record** records the selected channel in 720p50:
  - Set minutes for a timed recording, or leave 0 and press **■ Stop recording** when you're done.
  - Several channels can record at once.
  - Files go into a `Live` folder inside the save folder.
  - Quitting the app finishes and saves any recordings in progress.

### Country tabs

- Each country tab lists the free live channels from the [iptv-org](https://github.com/iptv-org/iptv) project, loaded fresh when you first open the tab.
- **Plays here?** Every stream is tried from your connection, down to the first bytes of video:
  - 🟢 **Plays here**
  - 🔴 **Region-locked – needs VPN**: the stream only plays inside its own country. A VPN set to that country may help.
  - 🔴 **Blocked here**: the stream refused your connection for another reason.
  - ⚪ **Offline**: the link is dead or expired.

  Tick **Only ones that play here** to hide the rest.
- **Dead or expired links:**
  - **Update links** downloads the latest list (iptv-org updates it daily) and checks every stream again.
  - **Find new links** searches iptv-org's worldwide list for other links to each red or grey channel, and swaps in the first that plays here. Right-click a channel and choose **Find a new link** to do just that one.
  - Replacement links are remembered.
- Type in **Filter** to find a channel by name, or pick a category.
- **Watch in VLC** (or double-click), **Copy link** and **● Record** / **■ Stop** work as on the BBC tab.
- **Playlist (VLC / Jellyfin)...** builds one playlist from any of your countries:
  - Tick the countries you want, plus the BBC live channels if you like.
  - To choose categories, press a country's **Categories ›** button. Its categories appear on the right with channel counts; click to tick or untick them (e.g. just News and Kids). Each country remembers its own choice for this playlist.
  - Keep **Only channels that play here** ticked to leave out blocked and offline streams.
  - Each country becomes its own group in VLC's playlist (Ctrl+L).
  - Under **Playlist for**, choose **VLC** or **Jellyfin (M3U tuner)**. A Jellyfin playlist also gives every channel a number, a name, a logo and a unique id. After saving, the app copies the file's location to the clipboard and shows how to add it:
    1. In Jellyfin, open **Dashboard › Live TV › Tuner Devices › +**.
    2. Choose **M3U Tuner**.
    3. Paste the location into **File or URL**, then save.

    4. If you made a TV guide (below), add it under **Live TV › TV Guide Data Providers › + › XMLTV**.

    If Jellyfin runs on another computer, copy the files there first.
  - **Also make a TV guide (XMLTV)** saves a guide next to the playlist, with the same name ending `.xml`, covering the next 3 days. Its channel ids match the playlist, so Jellyfin, Kodi and other IPTV apps line them up automatically. Listings come from:
    - **BBC:** the BBC's own schedules, when BBC live channels are included.
    - **Pluto TV channels** in the UK, Ireland, Australia and USA tabs: Pluto's guide, matched exactly by channel id.
    - **Samsung TV Plus channels** in those tabs: Samsung's guide, matched by name.

    Other channels are listed without programmes. In a typical UK playlist, about 9 in 10 Pluto channels and 7 in 10 Samsung channels get listings.
  - **Update TV guide** (on any country tab) remakes the last playlist and guide with the same choices, so the listings stay current and the links stay fresh. Do it every day or two.
  - **Daily update...** (next to it) updates automatically every day:
    - Tick the box, choose a time, then press **Save**. Untick it to turn the daily update off.
    - On Windows it sets up a Task Scheduler task called *UK TV Tool - TV guide update*, so it runs even when the app is closed. If the computer is off or asleep at that time, it runs as soon as it's back on.
    - On Linux it adds a line to your crontab instead (see *Setup on Linux*).
    - Each run is recorded in `app.log`.

    It runs `uk_tv_tool.py --update-guide`. If you move the folder, open **Daily update...** and save again.
- **Adding a country:** click the **+** tab, type a country's name, then double-click it. **Removing one:** right-click its tab and choose **Close**. Your tabs are remembered.
- **Unofficial streams are left out.** These are rebroadcasts of paid or DRM-protected channels on third-party servers. The app recognises them by:
  - server: known rebroadcast sites, and streams served from a bare IP address;
  - headers: streams that need a faked referrer or browser identity.

  The note under the list says how many were left out.
- **Not every stream will play.** Streams come and go. Those marked *Geo-blocked* only play from inside their own country. Some entries are another country's version of a channel and won't play from the UK either.

## Troubleshooting

- **Downloads start failing.** The BBC changes iPlayer from time to time. Update yt-dlp first. On Windows:

  ```bash
  python -s -m pip install --upgrade yt-dlp
  ```

  On Linux, in this folder:

  ```bash
  .venv/bin/python -m pip install --upgrade yt-dlp
  ```

- **The app closes straight away.** On Windows, run **UK TV Tool (debug).bat** to see the error. On Linux, run `./uk-tv-tool.sh` from a terminal. Either way, the log records every start, error and exit: `%APPDATA%\iplayer-dl\app.log` on Windows, `~/.config/uk-tv-tool/app.log` on Linux.
- **Settings** are stored in `config.json` in the same folder as the log.

## Limits

- 1080p needs get_iplayer. Without it, the app falls back to 720p and says so in the log.
- No audio-described versions.
- Only programmes currently on iPlayer can be listed or downloaded.
- Live ITV, Channel 4 and Channel 5 aren't included, including in the UK tab, because their online streams use DRM. A Freeview network tuner (e.g. HDHomeRun) would be the way to add them later.

## Licence

MIT. See [LICENSE](LICENSE). It covers this app's code only; programmes and streams belong to their broadcasters.
