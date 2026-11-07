import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.connection import Listener
from multiprocessing import AuthenticationError
from urllib.parse import urlparse
from urllib.request import urlopen

import libtorrent as lt
from .settings import DEFAULTS, read_settings, validate, validate_copy_to


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


class Engine:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = self.root / '.terrence'
        self.directory.mkdir(exist_ok=True)
        self.path = self.directory / 'state.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            'next_id': 1, 'settings': {'seed_completed': False}, 'torrents': []}
        self.settings_path = self.root / 'terrence.json'
        if not self.settings_path.exists():
            write_json(self.settings_path, validate(self.state.get('settings', {}), self.root))
        self.settings = read_settings(self.root)
        self.state.pop('settings', None)
        self.session = lt.session({'listen_interfaces': '0.0.0.0:0', 'enable_dht': True})
        self.apply_settings()
        self.handles = {}
        self.io_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='terrence-files')
        self.io_jobs = {}
        self.lock = threading.RLock()
        self.running = True
        (self.root / self.settings['download_directory']).mkdir(parents=True, exist_ok=True)
        for row in self.state['torrents']:
            row.setdefault('save_path', str((self.root / 'downloads' / str(row['id'])).resolve()))
            if row['status'] != 'stopped':
                try:
                    self.attach(row)
                except Exception as error:
                    row['error'] = str(error)
        self.save()

    def apply_settings(self):
        self.session.apply_settings({key: self.settings[key] for key in
                                     ('download_rate_limit', 'upload_rate_limit', 'enable_dht')})

    def download_path(self, row):
        return Path(row.get('save_path', self.root / 'downloads' / str(row['id'])))

    def save(self):
        write_json(self.path, self.state)

    def params(self, row):
        if row['kind'] == 'magnet':
            params = lt.parse_magnet_uri(row['source'])
            cached = self.directory / f"{row['id']}.torrent"
            if cached.exists():
                params.ti = lt.torrent_info(str(cached))
        else:
            params = lt.add_torrent_params()
            params.ti = lt.torrent_info(str(self.directory / f"{row['id']}.torrent"))
        params.save_path = str(self.download_path(row))
        params.flags &= ~lt.torrent_flags.auto_managed
        params.flags &= ~lt.torrent_flags.paused
        return params

    def attach(self, row):
        handle = self.session.add_torrent(self.params(row))
        self.handles[row['id']] = handle
        if row['status'] in ('paused', 'completed'):
            handle.pause()
        row.pop('error', None)

    def find(self, target):
        for row in self.state['torrents']:
            if str(row['id']) == target or row['alias'] == target:
                return row
        raise ValueError(f'Unknown torrent: {target}')

    def validate_alias(self, name, current=None):
        if name is not None:
            if not name.strip() or name.isdecimal():
                raise ValueError('Alias must be nonempty and cannot be numeric')
            if any(r['alias'] == name and r['id'] != current for r in self.state['torrents']):
                raise ValueError('Alias is already in use')

    def copy_destination(self, value, source):
        validate_copy_to(value)
        if value is None:
            return None
        target = (self.root / value).resolve()
        source = Path(source).resolve()
        if target.is_relative_to(source) or source.is_relative_to(target):
            raise ValueError('copy_to must not overlap the torrent download directory')
        if any(target.is_relative_to(self.root.resolve() / name) for name in ('.terrence', '.git')):
            raise ValueError('copy_to must be outside .terrence and .git')
        return str(target)

    def copy_completed(self, row, handle):
        target = self.copy_destination(row.get('copy_to') or self.settings['copy_to'],
                                       self.download_path(row))
        source = self.download_path(row).resolve()
        storage = handle.torrent_file().files()
        # Copy only torrent files, preserving the torrent's own directory layout.
        for index in range(storage.num_files()):
            if storage.file_flags(index) & lt.file_storage.flag_pad_file:
                continue
            relative = Path(storage.file_path(index))
            original = (source / relative).resolve()
            destination = (Path(target) / relative).resolve()
            if not original.is_relative_to(source) or not destination.is_relative_to(Path(target)):
                raise ValueError('Torrent file path escapes the copy or download directory')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination)
        row['copied_to'] = target
        row.pop('copy_error', None)

    def file_job(self, key, operation, background):
        if not background:
            return True, operation()
        future = self.io_jobs.get(key)
        if future is None:
            self.io_jobs[key] = self.io_pool.submit(operation)
            return False, None
        if not future.done():
            return False, None
        del self.io_jobs[key]
        return True, future.result()

    def cleanup_folder(self, folder):
        path = Path(folder)
        self.validate_removal_path(path)
        if path.exists():
            shutil.rmtree(path)

    def copy_snapshot(self, row, handle):
        self.copy_completed(row, handle)
        return row

    def tick(self, background=False):
        changed = False
        for folder in list(self.state.get('pending_folder_cleanup', [])):
            try:
                done, _ = self.file_job(('delete', folder),
                                        lambda folder=folder: self.cleanup_folder(folder), background)
                if not done:
                    continue
            except (OSError, ValueError):
                continue
            self.state['pending_folder_cleanup'].remove(folder)
            changed = True
        for row in self.state['torrents']:
            handle = self.handles.get(row['id'])
            if handle is None:
                continue
            status = handle.status()
            if row['kind'] == 'magnet' and status.has_metadata:
                cached = self.directory / f"{row['id']}.torrent"
                if not cached.exists():
                    try:
                        metadata = handle.torrent_file()
                        data = lt.bencode(lt.create_torrent(metadata).generate())
                        temporary = cached.with_suffix('.torrent.tmp')
                        temporary.write_bytes(data)
                        temporary.replace(cached)
                        row.pop('metadata_cache_error', None)
                    except (OSError, RuntimeError) as error:
                        row['metadata_cache_error'] = str(error)
                    changed = True
            row.update(name=status.name, progress=status.progress,
                       download_rate=status.download_rate, upload_rate=status.upload_rate,
                       eta=round(max(0, status.total_wanted-status.total_wanted_done)/status.download_rate)
                       if status.download_rate else None)
            if status.errc.value():
                row['error'] = status.errc.message()
            if (('copy', row['id']) in self.io_jobs or
                    (status.is_seeding and (row.get('copy_to') or self.settings['copy_to'])
                     and not row.get('copied_to'))):
                try:
                    snapshot = dict(row)
                    # Resolve the default now; file threads do not read mutable settings.
                    snapshot['copy_to'] = row.get('copy_to') or self.settings['copy_to']
                    done, copied = self.file_job(('copy', row['id']),
                                                lambda snapshot=snapshot, handle=handle:
                                                self.copy_snapshot(snapshot, handle), background)
                    if done:
                        if copied.get('copied_to'):
                            row['copied_to'] = copied['copied_to']
                        row.pop('copy_error', None)
                        changed = True
                except (OSError, ValueError) as error:
                    if row.get('copy_error') != str(error):
                        row['copy_error'] = str(error)
                        changed = True
            if status.is_seeding and row['status'] == 'running' and not self.settings['seed_completed']:
                handle.pause()
                row['status'] = 'completed'
                changed = True
        self.session.pop_alerts()
        if changed:
            self.save()

    def validate_removal_path(self, folder):
        root = self.root.resolve()
        resolved = folder.resolve()
        if (folder.is_symlink() or not resolved.is_relative_to(root)
                or resolved == root or resolved.is_relative_to(root / '.terrence')
                or resolved.is_relative_to(root / '.git')
                or not folder.name.isdecimal()):
            raise ValueError('Refusing to remove an unsafe torrent download directory')

    def dispatch(self, message):
        with self.lock:
            if message['command'] != 'shutdown':
                self.settings = read_settings(self.root)
                self.apply_settings()
            return self.command(message)

    def info(self, row):
        self.tick(background=True)
        result = dict(row)
        handle = self.handles.get(row['id'])
        result.update(save_path=str(self.download_path(row)),
                      live=handle is not None, connected_peers=0, connected_seeds=0,
                      connected_leechers=0, known_peers=None, known_seeds=None,
                      tracker_seeds=None, tracker_leechers=None,
                      total_size=None, downloaded_bytes=None, uploaded_bytes=None,
                      files=[], trackers=[], web_seeds=[])
        metadata = None
        if handle is not None:
            status = handle.status()
            result.update(
                engine_state=str(status.state), has_metadata=status.has_metadata,
                connected_peers=status.num_peers, connected_seeds=status.num_seeds,
                connected_leechers=max(0, status.num_peers - status.num_seeds),
                known_peers=status.list_peers, known_seeds=status.list_seeds,
                tracker_seeds=status.num_complete if status.num_complete >= 0 else None,
                tracker_leechers=status.num_incomplete if status.num_incomplete >= 0 else None,
                downloaded_bytes=status.all_time_download, uploaded_bytes=status.all_time_upload,
                completed_bytes=status.total_wanted_done if status.has_metadata else None,
                distributed_copies=status.distributed_copies,
                current_tracker=status.current_tracker or None)
            result['trackers'] = [dict(url=t['url'], tier=t['tier']) for t in handle.trackers()]
            metadata = handle.torrent_file()
        else:
            result.update(download_rate=0, upload_rate=0, eta=None)
            params = self.params(row)
            metadata = params.ti
            result['trackers'] = [dict(url=url) for url in params.trackers]
        if metadata is not None:
            storage = metadata.files()
            progress = handle.file_progress() if handle is not None else None
            result.update(name=metadata.name(), has_metadata=True,
                          total_size=metadata.total_size(), piece_count=metadata.num_pieces(),
                          piece_size=metadata.piece_length(), private=metadata.priv())
            result['files'] = [dict(path=storage.file_path(i), size=storage.file_size(i),
                                    completed_bytes=progress[i] if progress is not None else None)
                               for i in range(storage.num_files())]
            if not result['trackers']:
                result['trackers'] = [dict(url=t.url, tier=t.tier) for t in metadata.trackers()]
            result['web_seeds'] = [dict(seed) for seed in metadata.web_seeds()]
        else:
            result['has_metadata'] = False
        return result

    def command(self, message):
        command = message['command']
        if command == 'info':
            return self.info(self.find(message['target']))
        if command == 'list':
            self.tick(background=True)
            rows = []
            for row in self.state['torrents']:
                item = dict(row)
                if row['id'] in self.handles and row['status'] == 'running':
                    status = self.handles[row['id']].status()
                    item['status'] = 'seeding' if status.is_seeding else str(status.state)
                if row['status'] in ('stopped', 'paused', 'completed'):
                    item.update(download_rate=0, upload_rate=0, eta=None)
                rows.append(item)
            return rows
        if command == 'shutdown':
            self.save()
            self.running = False
            return 'Background client stopped'
        if command == 'settings':
            updates = {key: message[key] for key in DEFAULTS if message.get(key) is not None}
            if updates.get('copy_to') == '':
                updates['copy_to'] = None
            for key in ('seed_completed', 'auto_start', 'enable_dht'):
                if key in updates and isinstance(updates[key], str):
                    if updates[key] not in ('true', 'false'):
                        raise ValueError(f'{key} must be true or false')
                    updates[key] = updates[key] == 'true'
            settings = validate({**self.settings, **updates}, self.root)
            if updates:
                write_json(self.settings_path, settings)
                self.settings = settings
                self.apply_settings()
            return settings
        if command == 'add':
            self.validate_alias(message.get('alias'))
            number = self.state['next_id']
            source = message['source']
            auto_start = message.get('start')
            if auto_start is None:
                auto_start = self.settings['auto_start']
            row = dict(id=number, alias=message.get('alias'), kind=message['kind'], source=source,
                       status='running' if auto_start else 'stopped',
                       save_path=str((self.root / self.settings['download_directory'] / str(number)).resolve()))
            row['copy_to'] = self.copy_destination(
                message.get('copy_to'),
                row['save_path'])
            if row['kind'] == 'torrent':
                if urlparse(source).scheme in ('http', 'https'):
                    with urlopen(source, timeout=15) as response:
                        data = response.read(16 * 1024 * 1024 + 1)
                    if len(data) > 16 * 1024 * 1024:
                        raise ValueError('Torrent metadata exceeds 16 MiB')
                else:
                    data = Path(source).read_bytes()
                lt.torrent_info(lt.bdecode(data))
                (self.directory / f'{number}.torrent').write_bytes(data)
            params = self.params(row)
            hashes = params.ti.info_hashes() if params.ti else params.info_hashes
            fingerprint = [str(hashes.v1), str(hashes.v2)]
            if any(r.get('fingerprint') == fingerprint for r in self.state['torrents']):
                if row['kind'] == 'torrent':
                    (self.directory / f'{number}.torrent').unlink(missing_ok=True)
                raise ValueError('Torrent is already managed')
            row['fingerprint'] = fingerprint
            if auto_start:
                self.attach(row)
            self.state['torrents'].append(row)
            self.state['next_id'] += 1
            self.save()
            return row
        row = self.find(message['target'])
        number = row['id']
        if command == 'alias':
            self.validate_alias(message.get('name'), number)
            row['alias'] = message.get('name')
        elif command == 'remove':
            job = self.io_jobs.get(('copy', number))
            if job is not None:
                raise ValueError('Completion copy is still pending; retry remove after it finishes')
            folder = self.download_path(row)
            self.validate_removal_path(folder)
            if number in self.handles:
                handle = self.handles.pop(number)
                self.session.remove_torrent(handle, lt.options_t.delete_files if message.get('delete_files') else 0)
                if message.get('delete_files'):
                    # Retry after libtorrent releases Windows file handles; survive worker restarts.
                    self.state.setdefault('pending_folder_cleanup', []).append(str(folder))
            elif message.get('delete_files') and folder.exists():
                shutil.rmtree(folder)
            if not message.get('delete_files'):
                try:
                    folder.rmdir()
                except OSError:
                    pass  # Keep nonempty folders because their files were not requested for deletion.
            self.state['torrents'].remove(row)
            (self.directory / f'{number}.torrent').unlink(missing_ok=True)
        elif command == 'stop':
            if ('copy', number) in self.io_jobs:
                raise ValueError('Completion copy is still pending; retry stop after it finishes')
            if number in self.handles:
                self.session.remove_torrent(self.handles.pop(number))
            row['status'] = 'stopped'
        elif command == 'pause':
            if number not in self.handles:
                raise ValueError('Start the stopped torrent before pausing it')
            self.handles[number].pause()
            row['status'] = 'paused'
        elif command in ('start', 'resume'):
            if command == 'resume' and row['status'] != 'paused':
                raise ValueError('Only paused torrents can be resumed; use start')
            if number not in self.handles:
                row['status'] = 'running'
                self.attach(row)
            else:
                self.handles[number].resume()
            row['status'] = 'running'
        else:
            raise ValueError('Unknown command')
        self.save()
        return row


def main():
    root = Path(sys.argv[1]).resolve()
    directory = root / '.terrence'
    directory.mkdir(exist_ok=True)
    # OS-backed file lock is released even after a crash; only one worker owns state.
    with (directory / 'worker.lock').open('a+b') as lock:
        try:
            if os.name == 'nt':
                import msvcrt
                lock.write(b'0')
                lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return
        engine = Engine(root)
        key = secrets.token_bytes(32)
        with Listener(('127.0.0.1', 0), authkey=key) as listener:
            endpoint = directory / 'endpoint.json'
            write_json(endpoint, {'port': listener.address[1], 'key': key.hex()})
            if os.name != 'nt':
                endpoint.chmod(0o600)
            # A timeout lets completion handling run even when no CLI is connected.
            listener._listener._socket.settimeout(.5)
            try:
                while engine.running:
                    try:
                        connection = listener.accept()
                    except (socket.timeout, AuthenticationError, EOFError, OSError):
                        with engine.lock:
                            engine.tick(background=True)
                        continue
                    with connection:
                        try:
                            if not connection.poll(5):
                                continue
                            result = engine.dispatch(json.loads(connection.recv_bytes(1024 * 1024)))
                            reply = {'result': result}
                        except Exception as error:
                            reply = {'error': str(error)}
                        try:
                            connection.send_bytes(json.dumps(reply).encode())
                        except (OSError, EOFError):
                            pass  # A timed-out/disconnected CLI must not terminate the worker.
            finally:
                engine.save()
                endpoint.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
