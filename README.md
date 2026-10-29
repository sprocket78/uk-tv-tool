# UK TV Tool

A Windows desktop app for UK free-to-air TV:

- **BBC iPlayer downloads.** Search iPlayer, tick episodes and download them in up to 1080p with subtitles.
- **Search all channels.** One search across BBC iPlayer, ITVX, Channel 4, My5, STV Player and U.
- **Live BBC TV.** See what's on now and next on 11 BBC channels. Watch in a browser or VLC, record, copy stream links, or save a VLC playlist.
- **Country tabs.** Free live channels for the UK, Ireland, France, Germany and the USA, each in its own tab. Add any of 250 countries with the **+** tab.

It only downloads and records content that is not DRM-protected: BBC iPlayer and free, unencrypted live streams. Other broadcasters' programmes are found and linked to, never decrypted.

## Requirements

- Windows 10 or 11 and a UK internet connection (iPlayer is UK-only)
- A TV licence, which you need to watch or download iPlayer, including live TV
- Python 3.12, yt-dlp, ffmpeg and, for 1080p, get_iplayer. `setup.ps1` installs all of them.
- VLC (optional), for **Watch in VLC** and the playlist

## Setup

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

- Each country tab lists the free live channels from the [iptv-org](https://github.com/iptv-org/iptv) project, loaded fresh when you first open the tab. **Refresh** reloads it.
- Type in **Filter** to find a channel by name, or pick a category.
- **Watch in VLC** (or double-click), **Copy link**, **● Record** / **■ Stop** and **Save VLC playlist** work as on the BBC tab. A playlist holds the channels currently shown, so filter first to save just those.
- **Adding a country:** click the **+** tab, type a country's name, then double-click it. **Removing one:** right-click its tab and choose **Close**. Your tabs are remembered.
- **Unofficial streams are left out.** These are rebroadcasts of paid or DRM-protected channels on third-party servers. The app recognises them by:
  - server: known rebroadcast sites, and streams served from a bare IP address;
  - headers: streams that need a faked referrer or browser identity.

  The note under the list says how many were left out.
- **Not every stream will play.** Streams come and go. Those marked *Geo-blocked* only play from inside their own country. Some entries are another country's version of a channel and won't play from the UK either.

## Troubleshooting

- **Downloads start failing.** The BBC changes iPlayer from time to time. Update yt-dlp first:

  ```bash
  python -s -m pip install --upgrade yt-dlp
  ```

- **The app closes straight away.** Run **UK TV Tool (debug).bat** to see the error, or read `%APPDATA%\iplayer-dl\app.log`. The log records every start, error and exit.
- **Settings** are stored in `%APPDATA%\iplayer-dl\config.json`.

## Limits

- 1080p needs get_iplayer. Without it, the app falls back to 720p and says so in the log.
- No audio-described versions.
- Only programmes currently on iPlayer can be listed or downloaded.
- Live ITV, Channel 4 and Channel 5 aren't included, including in the UK tab, because their online streams use DRM. A Freeview network tuner (e.g. HDHomeRun) would be the way to add them later.
