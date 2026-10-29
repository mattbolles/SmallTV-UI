#!/usr/bin/env python3
"""Local proxy + UI for the GeekMagic SmallTV-Ultra's built-in (but hidden)
generic file endpoints, so arbitrary files can be listed/uploaded/downloaded/
deleted over WiFi without touching the device firmware.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_DEVICE = "192.168.x.x"  # placeholder: your device's IP (or enter it in the page and press Connect)
PORT = 8765
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp")

ROW_RE = re.compile(
    r"<a href='([^']+)'>([^<]*)</a></td><td>(\d+)</td>", re.S
)


def device_request(device, path, method="GET", data=None, headers=None, timeout=10):
    url = f"http://{device}{path}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, dict(resp.getheaders()), resp.read()


def build_multipart(field_name, filename, data):
    # Builds the same shape of multipart/form-data body the browser's own
    # FormData would produce for a file input — used to re-upload a file
    # server-side (for rename) without round-tripping it through the
    # browser. The device's /doUpload handler expects the file under the
    # field name "image" specifically (confirmed by the existing /api/upload
    # passthrough, which just forwards whatever the browser's FormData sent).
    boundary = "----smalltvui" + uuid.uuid4().hex
    pre = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    post = f"\r\n--{boundary}--\r\n".encode()
    return pre + data + post, f"multipart/form-data; boundary={boundary}"


def parse_filelist(html):
    files = []
    for href, name, size in ROW_RE.findall(html):
        files.append({"path": href, "name": name, "kb": int(size)})
    return files


def image_dimensions(data):
    """Return (width, height) parsed from raw PNG/GIF/JPEG bytes, or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w = int.from_bytes(data[16:20], "big")
        h = int.from_bytes(data[20:24], "big")
        return w, h

    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        w = int.from_bytes(data[6:8], "little")
        h = int.from_bytes(data[8:10], "little")
        return w, h

    if data[:2] == b"\xff\xd8":
        i, n = 2, len(data)
        sof_markers = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        while i < n - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in sof_markers:
                h = int.from_bytes(data[i + 5 : i + 7], "big")
                w = int.from_bytes(data[i + 7 : i + 9], "big")
                return w, h
            if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
            i += 2 + seg_len
        return None

    return None


def fetch_prefix(device, path, max_bytes=16384):
    # The device ignores Range headers and always streams the whole file,
    # and it's slow (a few hundred KB can take 15-20+ seconds). But reading
    # only a small prefix from the response and closing the connection early
    # is nearly instant, since the bottleneck is transfer time, not latency.
    url = f"http://{device}{path}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read(max_bytes)


_res_cache = {}


def fetch_resolution(device, path, kb):
    # Keyed on size too, so a file replaced by a same-named upload of a
    # different size doesn't serve a stale cached resolution.
    key = (device, path, kb)
    if key in _res_cache:
        return _res_cache[key]
    try:
        data = fetch_prefix(device, path)
        dims = image_dimensions(data)
    except Exception:
        dims = None
    res = f"{dims[0]}×{dims[1]}" if dims else None
    _res_cache[key] = res
    return res


def annotate_resolutions(device, files):
    # The device is an ESP8266 with a tiny web server that can't handle more
    # than a couple of concurrent connections — fetching dimensions in
    # parallel causes it to silently drop requests, so this stays sequential.
    for f in files:
        if f["name"].lower().endswith(IMAGE_EXTS):
            f["res"] = fetch_resolution(device, f["path"], f["kb"])
        else:
            f["res"] = None
    return files


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>SmallTVUI</title>
<style>
  :root {
    color-scheme: light;
    --ink: #2b2117;
    --paper: #ede1c4;
    --panel: #faf5e6;
    --gold: #a3813f;
    --gold-dark: #7c611f;
    --green: #3c5c4c;
    --green-dark: #1f3327;
    --green-navy: #0c3324;
    --oxblood: #7d3644;
    --oxblood-dark: #4f1e28;
    --muted: #6b5d47;
    --line: #cbb98a;
  }
  * { box-sizing: border-box; }
  body {
    font-family: Georgia, 'Iowan Old Style', 'Palatino Linotype', 'Book Antiqua', serif;
    background: var(--paper);
    color: var(--ink);
    width: 92%;
    max-width: 1000px;
    margin: 40px auto 60px;
    padding: 0 20px;
  }
  .sheet {
    background: var(--panel);
    border: 1px solid var(--line);
    box-shadow: 0 1px 4px rgba(43,33,23,0.18);
    padding: 32px 36px 36px;
  }
  header.masthead { text-align: center; border-bottom: 3px double var(--gold-dark); padding-bottom: 22px; margin-bottom: 26px; }
  h1 {
    font-size: 48px;
    font-weight: normal;
    letter-spacing: 0.05em;
    margin: 0;
    color: var(--green-navy);
    text-shadow: 1px 1px 0 rgba(163,129,63,0.3), 0 1px 0 rgba(255,253,247,0.7);
    cursor: default;
    transition: text-shadow 0.3s ease;
  }
  h1:hover {
    background-image: linear-gradient(
      100deg,
      var(--green-navy) 0%,
      var(--green-navy) 30%,
      var(--gold) 42%,
      #fff9e6 48%,
      var(--oxblood) 54%,
      var(--green-navy) 66%,
      var(--green-navy) 100%
    );
    background-size: 250% 100%;
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    color: transparent;
    text-shadow: none;
    animation: shimmer 2.4s linear infinite;
  }
  @keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -50% 0; }
  }
  .bar { display: flex; gap: 10px; margin-bottom: 14px; align-items: center; flex-wrap: wrap; font-size: 14px; }
  input[type=text], select {
    font-family: inherit; font-size: 14px; padding: 6px 9px;
    border: 1px solid var(--line); border-radius: 2px;
    background: #fffdf7; color: var(--ink);
  }
  input[type=text]:focus, select:focus { outline: 1px solid var(--gold-dark); }
  button {
    font-family: inherit; font-size: 13px; padding: 7px 14px;
    border: 1px solid var(--gold-dark); border-radius: 2px;
    background: linear-gradient(#fdf8ea, #e8dcb8); color: var(--ink);
    cursor: pointer; box-shadow: inset 0 1px 0 rgba(255,255,255,0.7);
  }
  button:hover { background: linear-gradient(#f7efd8, #ddcfa2); }
  button:active { box-shadow: inset 0 1px 3px rgba(0,0,0,0.25); }
  button.primary { background: linear-gradient(#4a6d5b, var(--green-dark)); color: #f2e8d3; border-color: var(--green-dark); }
  button.primary:hover { background: linear-gradient(#557965, var(--green)); }
  button.danger { background: linear-gradient(#8c4250, var(--oxblood-dark)); color: #f2e8d3; border-color: var(--oxblood-dark); }
  button.danger:hover { background: linear-gradient(#9a4a58, var(--oxblood)); }
  table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 14px; }
  thead th {
    background: var(--green-dark); color: #f2e8d3; font-weight: normal; font-style: italic;
    text-align: left; padding: 9px 10px; letter-spacing: 0.04em; font-size: 11px; text-transform: uppercase;
  }
  tbody td { padding: 8px 10px; border-bottom: 1px solid var(--line); }
  tbody tr:nth-child(even) { background: rgba(163,129,63,0.09); }
  tbody tr:hover { background: rgba(163,129,63,0.18); }
  tr.preview-row td { background: rgba(31,51,39,0.05); padding: 16px 10px; border-bottom: 1px solid var(--line); }
  tr.preview-row img { display: block; max-width: 100%; max-height: 320px; margin: 0 auto; border: 1px solid var(--line); background: #fff; }
  button.view { background: linear-gradient(#e9eee6, #cdd8c6); border-color: var(--green-dark); }
  button.view:hover { background: linear-gradient(#dfe6da, #c0cdb8); }
  .loader { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 14px 0; }
  .spinner {
    width: 26px; height: 26px; border: 3px solid var(--line);
    border-top-color: var(--green-dark); border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .prog-text { font-size: 12px; color: var(--muted); font-style: italic; }
  .prog-bar-outer {
    width: 200px; height: 6px; border: 1px solid var(--line); border-radius: 3px;
    background: rgba(163,129,63,0.18); overflow: hidden;
  }
  .prog-bar-inner { height: 100%; width: 0%; background: var(--green-dark); transition: width 0.15s ease; }
  .load-error { color: var(--oxblood-dark); font-style: italic; font-size: 13px; }
  #drop {
    border: 2px dashed var(--line); border-radius: 2px; padding: 22px; text-align: center;
    color: var(--muted); font-style: italic; margin-top: 18px; cursor: pointer;
    background: rgba(255,253,247,0.5);
    transition: border-color 0.25s ease, background-color 0.25s ease, color 0.25s ease;
  }
  #drop:hover {
    border-color: var(--gold-dark); color: var(--gold-dark); background: rgba(163,129,63,0.1);
  }
  #drop.over { border-color: var(--green-dark); color: var(--green-dark); background: rgba(47,74,60,0.07); }
  .hint { font-size: 12px; color: var(--muted); font-style: italic; margin: 8px 4px 0; line-height: 1.5; }
  #status { font-size: 13px; color: var(--muted); min-height: 18px; margin-top: 10px; font-style: italic; }
  #space { font-size: 13px; color: var(--muted); }
  .space-bar {
    display: inline-block; vertical-align: middle; width: 90px; height: 9px;
    border: 1px solid var(--line); border-radius: 3px; overflow: hidden;
    background: rgba(163,129,63,0.15);
  }
  .space-bar-fill {
    display: block; height: 100%; width: 0%; background: var(--green-dark);
    transition: width 0.3s ease, background-color 0.3s ease;
  }
  a.dl { color: var(--green-dark); text-decoration: underline; }
  a.dl:hover { color: var(--oxblood-dark); }
  .colophon { text-align: center; margin-top: 22px; }
  .colophon a {
    font-size: 12px; color: var(--muted); text-decoration: none;
    letter-spacing: 0.04em; border-bottom: 1px solid transparent;
  }
  .colophon a:hover { color: var(--gold-dark); border-bottom-color: var(--gold-dark); }
</style>
</head>
<body>
<div class="sheet">
  <header class="masthead">
    <h1>SmallTVUI</h1>
  </header>

  <div class="bar">
    Device IP: <input type="text" id="device" style="width:130px">
    <button id="connectBtn" class="primary">Connect</button>
    <span id="spaceBar" class="space-bar"><span id="spaceBarFill" class="space-bar-fill"></span></span>
    <span id="space" class="hint" style="margin:0"></span>
  </div>

  <div class="bar">
    <label for="folderPreset">Folder</label>
    <select id="folderPreset" style="width:180px">
      <option value="/image/">Pictures</option>
      <option value="/gif/">Weather GIF</option>
    </select>
    <button id="refreshBtn">Refresh</button>
  </div>

  <div id="drop">Drag files here to upload, or click to choose</div>
  <input type="file" id="fileInput" multiple style="display:none">
  <p class="hint">The device's screen measures 240&times;240px &mdash; JPG and GIF images at that size display natively in its slideshow; other sizes are stored as-is, unscaled. Other file types may be uploaded and stored too, but won't appear as pictures. Upload size is limited only by the free space shown above.</p>

  <div id="status"></div>
  <table id="tbl">
    <thead><tr><th>Name</th><th>Resolution</th><th>Size (KB)</th><th></th><th></th><th></th><th></th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</div>

<footer class="colophon">
  <a href="https://mattbolles.com" target="_blank" rel="noopener">2026 Matt Bolles</a>
</footer>

<script>
const $ = id => document.getElementById(id);
function loadDevice() { return localStorage.getItem('device') || DEFAULT_DEVICE_PLACEHOLDER; }
$('device').value = loadDevice();
let curDir = '/image/';

function setStatus(msg, isErr) {
  $('status').textContent = msg || '';
  $('status').style.color = isErr ? '#7d3644' : '#6b5d47';
}

async function api(path, opts) {
  const device = $('device').value.trim();
  const url = path + (path.includes('?') ? '&' : '?') + 'device=' + encodeURIComponent(device);
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res;
}

async function refreshSpace() {
  try {
    const res = await api('/api/space');
    const j = await res.json();
    const freePct = j.total > 0 ? Math.round((j.free / j.total) * 100) : 0;
    $('space').textContent = `Free: ${Math.floor(j.free/1024)}KB / ${Math.floor(j.total/1024)}KB (${freePct}%)`;
    const usedPct = 100 - freePct;
    $('spaceBarFill').style.width = usedPct + '%';
    $('spaceBarFill').style.backgroundColor = usedPct >= 85 ? '#7d3644' : '';
  } catch (e) {
    $('space').textContent = '';
    $('spaceBarFill').style.width = '0%';
  }
}

async function list(dir) {
  setStatus('Loading ' + dir + ' ...');
  try {
    const res = await api('/api/list?dir=' + encodeURIComponent(dir));
    const files = await res.json();
    curDir = dir;
    $('folderPreset').value = dir;
    const rows = $('rows');
    rows.innerHTML = '';
    if (files.length === 0) {
      rows.innerHTML = '<tr><td colspan="7" style="color:#9c8a68;font-style:italic">Empty</td></tr>';
    }
    for (const f of files) {
      const tr = document.createElement('tr');
      const nameTd = document.createElement('td');
      nameTd.textContent = f.name;
      const resTd = document.createElement('td');
      resTd.textContent = f.res || '—';
      const sizeTd = document.createElement('td');
      sizeTd.textContent = f.kb;
      const dlTd = document.createElement('td');
      const a = document.createElement('a');
      a.href = '/file' + f.path + '?device=' + encodeURIComponent($('device').value.trim());
      a.textContent = 'Download';
      a.className = 'dl';
      dlTd.appendChild(a);
      const viewTd = document.createElement('td');
      if (f.res) {
        const viewBtn = document.createElement('button');
        viewBtn.textContent = 'View';
        viewBtn.className = 'view';
        viewBtn.onclick = () => toggleView(viewBtn, f.path, tr);
        viewTd.appendChild(viewBtn);
      }
      const renameTd = document.createElement('td');
      const renameBtn = document.createElement('button');
      renameBtn.textContent = 'Rename';
      renameBtn.className = 'view';
      renameBtn.onclick = () => renameFile(f, files.map(x => x.name), renameBtn);
      renameTd.appendChild(renameBtn);
      const delTd = document.createElement('td');
      const btn = document.createElement('button');
      btn.textContent = 'Delete';
      btn.className = 'danger';
      btn.onclick = () => del(f.path);
      delTd.appendChild(btn);
      tr.append(nameTd, resTd, sizeTd, dlTd, viewTd, renameTd, delTd);
      rows.appendChild(tr);
    }
    setStatus('');
  } catch (e) {
    setStatus('Failed to load ' + dir + ': ' + e.message, true);
  }
  refreshSpace();
}

async function toggleView(btn, path, tr) {
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains('preview-row')) {
    const img = existing.querySelector('img');
    if (img && img.dataset.blobUrl) URL.revokeObjectURL(img.dataset.blobUrl);
    existing.remove();
    btn.textContent = 'View';
    return;
  }

  const previewTr = document.createElement('tr');
  previewTr.className = 'preview-row';
  const td = document.createElement('td');
  td.colSpan = 7;
  const spinner = document.createElement('div');
  spinner.className = 'spinner';
  const progText = document.createElement('div');
  progText.className = 'prog-text';
  progText.textContent = 'Loading…';
  const progBarOuter = document.createElement('div');
  progBarOuter.className = 'prog-bar-outer';
  const progBarInner = document.createElement('div');
  progBarInner.className = 'prog-bar-inner';
  progBarOuter.appendChild(progBarInner);
  const loader = document.createElement('div');
  loader.className = 'loader';
  loader.append(spinner, progText, progBarOuter);
  td.appendChild(loader);
  previewTr.appendChild(td);
  tr.after(previewTr);
  btn.textContent = 'Hide';

  const url = '/file' + path + '?device=' + encodeURIComponent($('device').value.trim());
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const total = parseInt(res.headers.get('Content-Length') || '0', 10);
    const reader = res.body.getReader();
    const chunks = [];
    let loaded = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      loaded += value.length;
      if (total > 0) {
        const pct = Math.min(100, Math.round(loaded / total * 100));
        progText.textContent = 'Loading… ' + pct + '%';
        progBarInner.style.width = pct + '%';
      } else {
        progText.textContent = 'Loading… ' + Math.round(loaded / 1024) + 'KB';
      }
    }
    const blob = new Blob(chunks);
    const objUrl = URL.createObjectURL(blob);
    const img = document.createElement('img');
    img.dataset.blobUrl = objUrl;
    img.src = objUrl;
    td.innerHTML = '';
    td.appendChild(img);
  } catch (e) {
    td.innerHTML = '';
    const err = document.createElement('div');
    err.className = 'load-error';
    err.textContent = 'Failed to load: ' + e.message;
    td.appendChild(err);
  }
}

async function del(path) {
  if (!confirm('Delete ' + path + '?')) return;
  setStatus('Deleting ' + path + ' ...');
  try {
    await api('/api/delete?file=' + encodeURIComponent(path));
    setStatus('Deleted ' + path);
  } catch (e) {
    setStatus('Delete failed: ' + e.message, true);
  }
  list(curDir);
}

function splitExt(name) {
  const i = name.lastIndexOf('.');
  if (i <= 0) return [name, ''];
  return [name.substring(0, i), name.substring(i)];
}

async function renameFile(f, existingNames, btn) {
  const [base, ext] = splitExt(f.name);
  const newBase = prompt('Rename "' + f.name + '" to (extension "' + ext + '" is kept):', base);
  if (newBase === null) return;
  const trimmed = newBase.trim();
  if (!trimmed || trimmed === base) return;
  const newName = trimmed + ext;
  if (newName !== f.name && existingNames.includes(newName)) {
    if (!confirm('A file named "' + newName + '" already exists here. Overwrite it?')) return;
  }
  // This is slow for big files — it downloads the whole thing from the
  // device and re-uploads it under the new name (see the /api/rename
  // comment in server.py for why), so it's worth a status message rather
  // than looking like it hung.
  btn.disabled = true;
  setStatus('Renaming ' + f.name + ' to ' + newName + ' ... this can take a while for large files');
  try {
    await api(
      '/api/rename?dir=' + encodeURIComponent(curDir) +
      '&old=' + encodeURIComponent(f.path) +
      '&new=' + encodeURIComponent(newName),
      { method: 'POST' }
    );
    setStatus('Renamed to ' + newName);
  } catch (e) {
    setStatus('Rename failed: ' + e.message, true);
  }
  list(curDir);
}

async function upload(files) {
  for (const file of files) {
    setStatus('Uploading ' + file.name + ' ...');
    const fd = new FormData();
    fd.append('image', file, file.name);
    try {
      await api('/api/upload?dir=' + encodeURIComponent(curDir), { method: 'POST', body: fd });
      setStatus('Uploaded ' + file.name);
    } catch (e) {
      setStatus('Upload failed for ' + file.name + ': ' + e.message, true);
    }
  }
  list(curDir);
}

$('connectBtn').onclick = () => { localStorage.setItem('device', $('device').value.trim()); list('/image/'); };
$('folderPreset').onchange = () => list($('folderPreset').value);
$('refreshBtn').onclick = () => list(curDir);
$('drop').onclick = () => $('fileInput').click();
$('fileInput').onchange = e => upload(e.target.files);
$('drop').addEventListener('dragover', e => { e.preventDefault(); $('drop').classList.add('over'); });
$('drop').addEventListener('dragleave', () => $('drop').classList.remove('over'));
$('drop').addEventListener('drop', e => {
  e.preventDefault();
  $('drop').classList.remove('over');
  upload(e.dataTransfer.files);
});

list('/image/');
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _device_and_query(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        device = qs.get("device", [DEFAULT_DEVICE])[0]
        return parsed, qs, device

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, status=200, content_type="text/plain", extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _stream_file(self, device, devpath):
        # Relays bytes as they arrive from the device instead of buffering
        # the whole file first. The device is slow (a large GIF can take
        # 15-20+ seconds to fully transfer), so streaming lets the browser
        # start receiving data immediately and report real progress, rather
        # than appearing to hang until the entire file has landed on us.
        url = f"http://{device}{devpath}"
        with urllib.request.urlopen(url, timeout=30) as resp:
            ctype = resp.headers.get("Content-Type", "application/octet-stream")
            clen = resp.headers.get("Content-Length")
            fname = devpath.rsplit("/", 1)[-1] or "download"
            self.send_response(resp.status)
            self.send_header("Content-Type", ctype)
            if clen is not None:
                self.send_header("Content-Length", clen)
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.end_headers()
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()

    def do_GET(self):
        parsed, qs, device = self._device_and_query()

        if parsed.path == "/":
            html = INDEX_HTML.replace(
                "DEFAULT_DEVICE_PLACEHOLDER", json.dumps(DEFAULT_DEVICE)
            )
            self._send_bytes(html.encode(), content_type="text/html")
            return

        if parsed.path == "/api/list":
            d = qs.get("dir", ["/"])[0]
            try:
                # Always pass `dir` explicitly. Omitting it makes the device
                # fall back to listing /image/'s contents but with the
                # "/image/" prefix stripped from each link, producing hrefs
                # that 404 on download. True root genuinely has no files of
                # its own (everything lives in named subfolders), so this
                # correctly shows "Empty" there instead of broken links.
                device_path = "/filelist?dir=" + urllib.parse.quote(d, safe="/")
                status, _, body = device_request(device, device_path)
                files = parse_filelist(body.decode("utf-8", "replace"))
                files = annotate_resolutions(device, files)
                self._send_json(files)
            except Exception as e:
                self._send_json({"error": str(e)}, status=502)
            return

        if parsed.path == "/api/space":
            try:
                status, _, body = device_request(device, "/space.json")
                self._send_bytes(body, content_type="application/json")
            except Exception as e:
                self._send_json({"error": str(e)}, status=502)
            return

        if parsed.path == "/api/delete":
            f = qs.get("file", [""])[0]
            try:
                status, _, body = device_request(
                    device, "/delete?file=" + urllib.parse.quote(f, safe="")
                )
                self._send_bytes(body, status=status)
            except Exception as e:
                self._send_json({"error": str(e)}, status=502)
            return

        if parsed.path.startswith("/file/"):
            devpath = parsed.path[len("/file"):]
            try:
                self._stream_file(device, devpath)
            except Exception as e:
                try:
                    self._send_bytes(str(e).encode(), status=502)
                except Exception:
                    pass
            return

        self._send_bytes(b"Not found", status=404)

    def do_POST(self):
        parsed, qs, device = self._device_and_query()
        if parsed.path == "/api/upload":
            d = qs.get("dir", ["/"])[0]
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            ctype = self.headers.get("Content-Type", "")
            try:
                status, _, resp_body = device_request(
                    device,
                    "/doUpload?dir=" + urllib.parse.quote(d, safe="/"),
                    method="POST",
                    data=body,
                    headers={"Content-Type": ctype, "Content-Length": str(len(body))},
                )
                self._send_bytes(resp_body, status=status)
            except Exception as e:
                self._send_json({"error": str(e)}, status=502)
            return

        if parsed.path == "/api/rename":
            # The device has no rename/move endpoint at all, so this is
            # implemented as download-then-reupload-then-delete: pull the
            # file's bytes off the device, push them back up under the new
            # name, and only delete the original once that upload has
            # actually succeeded. If anything fails partway, the original
            # is left untouched rather than risking data loss — worst case
            # after a failed step is two copies sitting there, never zero.
            d = qs.get("dir", ["/"])[0]
            old_path = qs.get("old", [""])[0]
            new_name = qs.get("new", [""])[0]
            if not old_path or not new_name:
                self._send_json({"error": "missing old/new filename"}, status=400)
                return
            try:
                _, _, data = device_request(device, old_path, timeout=30)
            except Exception as e:
                self._send_json({"error": f"couldn't read original file: {e}"}, status=502)
                return
            body, ctype = build_multipart("image", new_name, data)
            try:
                status, _, resp = device_request(
                    device,
                    "/doUpload?dir=" + urllib.parse.quote(d, safe="/"),
                    method="POST",
                    data=body,
                    headers={"Content-Type": ctype, "Content-Length": str(len(body))},
                    timeout=30,
                )
            except Exception as e:
                self._send_json({"error": f"upload of renamed copy failed: {e}"}, status=502)
                return
            try:
                device_request(
                    device, "/delete?file=" + urllib.parse.quote(old_path, safe=""), timeout=10
                )
            except Exception:
                pass  # renamed copy exists regardless; the old one just lingers
            self._send_json({"ok": True})
            return

        self._send_bytes(b"Not found", status=404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"SmallTV file manager on http://127.0.0.1:{PORT}")
    server.serve_forever()
