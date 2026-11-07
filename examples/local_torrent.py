"""Generate a test torrent; optionally serve its payload over loopback HTTP."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import libtorrent as lt


DIRECTORY = Path(__file__).resolve().parent / 'local-test'
PAYLOAD = (b'Terrence local download test. This is safe, generated sample data.\n' * 4096)
PORT = 8765


def generate():
    DIRECTORY.mkdir(exist_ok=True)
    (DIRECTORY / 'sample.txt').write_bytes(PAYLOAD)
    piece_size = 16384
    metadata = {
        b'comment': b'Local Terrence test torrent with a loopback web seed',
        b'url-list': [f'http://127.0.0.1:{PORT}/sample.txt'.encode()],
        b'info': {
            b'name': b'sample.txt', b'length': len(PAYLOAD), b'piece length': piece_size,
            b'pieces': b''.join(hashlib.sha1(PAYLOAD[i:i + piece_size]).digest()
                               for i in range(0, len(PAYLOAD), piece_size)),
        },
    }
    path = DIRECTORY / 'sample.torrent'
    path.write_bytes(lt.bencode(metadata))
    print(f'Created {path} ({len(PAYLOAD):,} payload bytes)', flush=True)
    return path


class SeedHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond()

    def do_HEAD(self):
        self.respond(head=True)

    def respond(self, head=False):
        if self.path != '/sample.txt':
            self.send_error(404)
            return
        start, end = 0, len(PAYLOAD) - 1
        partial = self.headers.get('Range')
        if partial:
            try:
                unit, interval = partial.split('=')
                first, last = interval.split('-')
                if unit != 'bytes' or not first:
                    raise ValueError
                start = int(first)
                end = min(int(last), end) if last else end
                if not 0 <= start <= end:
                    raise ValueError
            except ValueError:
                self.send_error(416)
                return
        self.send_response(206 if partial else 200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{len(PAYLOAD)}')
        self.end_headers()
        if not head:
            self.wfile.write(PAYLOAD[start:end + 1])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true', help='Serve the sample for real local downloads')
    args = parser.parse_args()
    generate()
    if args.serve:
        print(f'Local web seed: http://127.0.0.1:{PORT}/sample.txt (Ctrl+C to stop)', flush=True)
        with ThreadingHTTPServer(('127.0.0.1', PORT), SeedHandler) as server:
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
