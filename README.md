# SmallTVUI

A local web UI for the GeekMagic SmallTV-Ultra, a small ESP8266-based Wi-Fi display. It manages the files stored on the device, converts video clips into GIFs sized for its screen, and covers the settings on the device's own web page.

## How it works

The SmallTV-Ultra's own web page restricts uploads to JPG/GIF files, one folder per page, with no rename, no resolution info and no way to prepare media for the screen. Reading that page's source showed the restrictions live in its JavaScript, not on the device: the firmware's file handlers (`/filelist`, `/doUpload`, `/delete`, `/space.json`) are generic. SmallTVUI talks to those endpoints directly.

The device sends no CORS headers, so a web page can't call it from another origin. `server.py` is a small standard-library Python proxy: the browser talks to it on `localhost`, and it talks to the device server-side. Everything (the proxy and the single-page UI it serves) lives in that one file.

## Features

- Browse the device's picture and weather-GIF folders; upload (drag and drop or file picker), download and delete files
- Free-space readout
- Image preview, streamed from the device with a live progress bar
- Resolution column, read from the first few KB of each image and cached
- Rename. The device has no rename endpoint, so this copies the file under the new name and only then deletes the original; a failure partway never loses data
- Storage meter that turns red as the device fills up
- Network, Weather, Time and Settings tabs mirroring the official page: Wi-Fi scan and credentials, startup delay, city, units, update interval, API keys, time zone, clock colors, 12/24-hour format, date format, colon blink, clock font, NTP server, themes and auto-switching, brightness, night mode, reboot, factory reset and firmware update
- Each tab loads lazily, in a single browser request; the proxy then queries the device one endpoint at a time, since it can't cope with overlapping connections
- Video to GIF: drop in a clip, trim it, zoom and drag it inside a square preview of the 240x240 screen (zooming out pads with black), then convert with ffmpeg and upload the result
- Size controls for a device with very little free flash: frame rate, palette size (8 to 256 colors), dithering and an option that only re-encodes the parts of each frame that change
- Shows the source video's resolution, length and frame rate
- Upload progress bar, measured on the proxy-to-device leg where the time is actually spent
- Uploaded filenames are sanitized (see below)

## Running

```
python3 server.py
```

Then open <http://127.0.0.1:8765>, enter the device's IP address and press Connect (it's remembered in the browser), or change `DEFAULT_DEVICE` at the top of `server.py`.

Python 3 is the only requirement (standard library only), except that video conversion needs `ffmpeg` and `ffprobe` on your `PATH`, for example `brew install ffmpeg`.

## Device quirks worth knowing

- Listing a folder without a `dir` parameter returns links that are missing the folder prefix (they 404), so `dir` is always passed explicitly.
- `/delete` replies with the text "Fail" even when the file was removed, so the HTTP status is trusted instead of the body.
- The device ignores `Range` and serves files slowly (a few hundred KB can take 10 to 20 seconds). Reading just the first bytes of a response and closing the connection is near-instant, which is how image resolutions are read.
- It drops requests when connections overlap, so anything that touches several files runs sequentially.
- Settings that were never saved return 404 rather than a default, which is treated as "leave the field at its default".
- The official page pre-fills the Wi-Fi password field with the masked value `****`, which would overwrite the real password if saved unedited. This UI always leaves that field blank.
- A file whose name contains a space is listed as 0 KB (the file itself is intact), so uploads are restricted to letters, digits, underscores and hyphens.

## Status

Developed against a single device (firmware `Ultra-V9.0.51`). This is an unofficial project and is not affiliated with GeekMagic.

Reboot, factory reset, saving Wi-Fi credentials and firmware update are wired to send the same requests as the official page, but have not been exercised against a real device. Treat them with care.
