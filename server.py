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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_DEVICE = "192.168.x.x"  # placeholder: your device's IP (or enter it in the page and press Connect)
PORT = 8765

ROW_RE = re.compile(
    r"<a href='([^']+)'>([^<]*)</a></td><td>(\d+)</td>", re.S
)


def device_request(device, path, method="GET", data=None, headers=None):
    url = f"http://{device}{path}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, dict(resp.getheaders()), resp.read()


def parse_filelist(html):
    files = []
    for href, name, size in ROW_RE.findall(html):
        files.append({"path": href, "name": name, "kb": int(size)})
    return files


INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>SmallTV-Ultra File Manager</title>
<style>
  :root { color-scheme: light; }
  body {
    font-family: -apple-system, system-ui, sans-serif; background: #fff; color: #222;
    max-width: 760px; margin: 30px auto; padding: 0 16px;
  }
  h1 { font-size: 18px; margin-bottom: 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 20px; }
  .bar { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; flex-wrap: wrap; }
  input[type=text], select {
    padding: 6px 8px; border: 1px solid #999; border-radius: 6px;
    font-size: 14px; background: #fff; color: #222;
  }
  button {
    padding: 6px 12px; border: 1px solid #999; border-radius: 6px;
    background: #f0f0f0; color: #222; cursor: pointer; font-size: 14px;
  }
  button:hover { background: #e0e0e0; }
  button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
  button.danger { background: #dc2626; color: #fff; border-color: #dc2626; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #ddd; font-size: 14px; }
  th { color: #666; font-weight: 600; }
  #drop {
    border: 2px dashed #aaa; border-radius: 10px; padding: 24px; text-align: center;
    color: #888; margin-top: 16px; cursor: pointer;
  }
  #drop.over { background: #eef4ff; border-color: #2563eb; color: #2563eb; }
  #status { font-size: 13px; color: #666; min-height: 18px; margin-top: 8px; }
  #space { font-size: 13px; color: #888; }
  a.dl { color: #2563eb; }
</style>
</head>
<body>
  <h1>SmallTV-Ultra File Manager</h1>
  <div class="sub">Talks to the device's own upload/list/delete endpoints over WiFi &mdash; no firmware changes.</div>

  <div class="bar">
    Device IP: <input type="text" id="device" style="width:130px">
    <button id="connectBtn" class="primary">Connect</button>
    <span id="space"></span>
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

  <div id="status"></div>
  <table id="tbl">
    <thead><tr><th>Name</th><th>Size (KB)</th><th></th><th></th></tr></thead>
    <tbody id="rows"></tbody>
  </table>

<script>
const $ = id => document.getElementById(id);
function loadDevice() { return localStorage.getItem('device') || DEFAULT_DEVICE_PLACEHOLDER; }
$('device').value = loadDevice();
let curDir = '/image/';

function setStatus(msg, isErr) {
  $('status').textContent = msg || '';
  $('status').style.color = isErr ? '#dc2626' : '#666';
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
    $('space').textContent = `Free: ${Math.floor(j.free/1024)}KB / ${Math.floor(j.total/1024)}KB`;
  } catch (e) {
    $('space').textContent = '';
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
      rows.innerHTML = '<tr><td colspan="4" style="color:#999">Empty</td></tr>';
    }
    for (const f of files) {
      const tr = document.createElement('tr');
      const nameTd = document.createElement('td');
      nameTd.textContent = f.name;
      const sizeTd = document.createElement('td');
      sizeTd.textContent = f.kb;
      const dlTd = document.createElement('td');
      const a = document.createElement('a');
      a.href = '/file' + f.path + '?device=' + encodeURIComponent($('device').value.trim());
      a.textContent = 'Download';
      a.className = 'dl';
      dlTd.appendChild(a);
      const delTd = document.createElement('td');
      const btn = document.createElement('button');
      btn.textContent = 'Delete';
      btn.className = 'danger';
      btn.onclick = () => del(f.path);
      delTd.appendChild(btn);
      tr.append(nameTd, sizeTd, dlTd, delTd);
      rows.appendChild(tr);
    }
    setStatus('');
  } catch (e) {
    setStatus('Failed to load ' + dir + ': ' + e.message, true);
  }
  refreshSpace();
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
            # The device's /delete answers with the text "Fail" even when the
            # file was removed, so callers trust the HTTP status and re-list
            # rather than reading the body.
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
                status, headers, body = device_request(device, devpath)
                ctype = headers.get("Content-Type", "application/octet-stream")
                fname = devpath.rsplit("/", 1)[-1] or "download"
                self._send_bytes(
                    body,
                    status=status,
                    content_type=ctype,
                    extra_headers={
                        "Content-Disposition": f'attachment; filename="{fname}"'
                    },
                )
            except Exception as e:
                self._send_bytes(str(e).encode(), status=502)
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
        self._send_bytes(b"Not found", status=404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"SmallTV file manager on http://127.0.0.1:{PORT}")
    server.serve_forever()
