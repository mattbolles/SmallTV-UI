# SmallTVUI

A local web UI for managing the files on a GeekMagic SmallTV-Ultra, a small ESP8266-based Wi-Fi display.

## How it works

The SmallTV-Ultra's own web page restricts uploads to JPG/GIF files, one folder per page, with no rename, no resolution info and no way to prepare media for the screen. Reading that page's source showed the restrictions live in its JavaScript, not on the device: the firmware's file handlers (`/filelist`, `/doUpload`, `/delete`, `/space.json`) are generic. SmallTVUI talks to those endpoints directly.

The device sends no CORS headers, so a web page can't call it from another origin. `server.py` is a small standard-library Python proxy: the browser talks to it on `localhost`, and it talks to the device server-side. Everything (the proxy and the single-page UI it serves) lives in that one file.

## Features

- Browse the device's picture and weather-GIF folders; upload (drag and drop or file picker), download and delete files
- Free-space readout

## Running

```
python3 server.py
```

Then open <http://127.0.0.1:8765>, enter the device's IP address and press Connect (it's remembered in the browser), or change `DEFAULT_DEVICE` at the top of `server.py`.

Python 3 is the only requirement (standard library only).

## Device quirks worth knowing

- Listing a folder without a `dir` parameter returns links that are missing the folder prefix (they 404), so `dir` is always passed explicitly.
- `/delete` replies with the text "Fail" even when the file was removed, so the HTTP status is trusted instead of the body.

## Status

Developed against a single device (firmware `Ultra-V9.0.51`). This is an unofficial project and is not affiliated with GeekMagic.
