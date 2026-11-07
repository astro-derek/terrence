"""Authenticated, local-only communication with the directory's worker."""
import json
import subprocess
import sys
import time
import threading
from multiprocessing.connection import Client
from pathlib import Path


def request(root, message, start=True):
    directory = Path(root) / '.terrence'
    def connect():
        endpoint = json.loads((directory / 'endpoint.json').read_text())
        with Client(('127.0.0.1', endpoint['port']), authkey=bytes.fromhex(endpoint['key'])) as connection:
            connection.send_bytes(json.dumps(message).encode())
            if not connection.poll(30):
                raise TimeoutError('Background client did not respond within 30 seconds')
            reply = json.loads(connection.recv_bytes())
        if 'error' in reply:
            raise ValueError(reply['error'])
        return reply['result']
    try:
        return connect()
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
        except (OSError, EOFError, json.JSONDecodeError):
            pass
    raise ValueError(f'Could not start client; see {directory / "worker.log"}')
