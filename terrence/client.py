"""Authenticated, local-only communication with the directory's worker."""
import json
import subprocess
import sys
import time
import threading
import socket
from multiprocessing.connection import Connection, answer_challenge, deliver_challenge
from pathlib import Path


def connect_worker(address, key, timeout=5):
    deadline = time.monotonic() + timeout
    with socket.create_connection(address, timeout=timeout) as sock:
        sock.setblocking(True)
        connection = Connection(sock.detach())

    class Handshake:
        def send_bytes(self, data):
            connection.send_bytes(data)

        def recv_bytes(self, maxlength=None):
            if not connection.poll(max(0, deadline - time.monotonic())):
                raise TimeoutError('Background worker is busy or unresponsive during connection setup; retry shortly')
            return connection.recv_bytes(maxlength)

    try:
        handshake = Handshake()
        answer_challenge(handshake, key)
        deliver_challenge(handshake, key)
        return connection
    except BaseException:
        connection.close()
        raise


def request(root, message, start=True):
    if message['command'] != 'shutdown' and (Path(root) / 'terrence.json').exists():
        from .settings import read_settings
        read_settings(root)
    directory = Path(root) / '.terrence'
    def connect():
        endpoint = json.loads((directory / 'endpoint.json').read_text())
        with connect_worker(('127.0.0.1', endpoint['port']), bytes.fromhex(endpoint['key'])) as connection:
            connection.send_bytes(json.dumps(message).encode())
            if not connection.poll(30):
                raise TimeoutError('Background client did not respond within 30 seconds')
            reply = json.loads(connection.recv_bytes())
        if 'error' in reply:
            raise ValueError(reply['error'])
        return reply['result']
    try:
        return connect()
    except TimeoutError:
        raise  # Never spawn another worker or replay a command after an ambiguous timeout.
    except (OSError, EOFError, json.JSONDecodeError):
        if not start:
            raise ValueError('No background client is running in this directory')
    directory.mkdir(exist_ok=True)
    options = {'cwd': str(root), 'stdin': subprocess.DEVNULL}
    if sys.platform == 'win32':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    else:
        options['start_new_session'] = True
    # Also supports execution from an uninstalled source checkout.
    import os
    environment = os.environ.copy()
    environment['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent) + os.pathsep + environment.get('PYTHONPATH', '')
    with (directory / 'worker.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, '-m', 'terrence.worker', str(root)],
                                   stdout=log, stderr=log, env=environment, **options)
        threading.Thread(target=process.wait, daemon=True).start()
    for _ in range(100):
        time.sleep(.1)
        try:
            return connect()
        except TimeoutError:
            raise
        except (OSError, EOFError, json.JSONDecodeError):
            pass
    raise ValueError(f'Could not start client; see {directory / "worker.log"}')
