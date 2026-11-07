import tempfile
import unittest
import hashlib
import time
import json
from unittest.mock import Mock, patch
from pathlib import Path

import libtorrent as lt

from terrence.worker import Engine


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'example.torrent'
        self.source.write_bytes(lt.bencode({b'info': {b'name': b'example.txt', b'length': 12,
                                                    b'piece length': 16384, b'pieces': b'x' * 20}}))
        self.engine = Engine(self.root)

    def tearDown(self):
        self.engine.io_pool.shutdown(wait=True)
        self.engine.session.pause()
        self.engine.handles.clear()
        del self.engine
        import gc
        gc.collect()
        self.temp.cleanup()

    def add(self, alias='example'):
        return self.engine.dispatch(dict(command='add', kind='torrent', source=str(self.source), alias=alias))

    def test_lifecycle_and_persistence(self):
        self.assertEqual(self.add()['id'], 1)
        for command, expected in [('pause', 'paused'), ('resume', 'running'), ('stop', 'stopped')]:
            result = self.engine.dispatch(dict(command=command, target='example'))
            self.assertEqual(result['status'], expected)
        with self.assertRaisesRegex(ValueError, 'Only paused'):
            self.engine.dispatch(dict(command='resume', target='1'))
        other = Engine(self.root)
        self.assertEqual(other.state['torrents'][0]['status'], 'stopped')
        self.assertEqual(other.state['next_id'], 2)
        del other
        self.engine.dispatch(dict(command='start', target='1'))
        self.assertIn(1, self.engine.handles)

    def test_duplicate_and_alias_validation(self):
        self.add()
        with self.assertRaisesRegex(ValueError, 'already in use'):
            self.add()
        with self.assertRaisesRegex(ValueError, 'already managed'):
            self.add('different')
        with self.assertRaisesRegex(ValueError, 'numeric'):
            self.engine.dispatch(dict(command='alias', target='1', name='2'))

    def test_magnet_metadata_survives_restart(self):
        metadata = lt.torrent_info(str(self.source))
        row = self.engine.dispatch(dict(command='add', kind='magnet',
                                        source=lt.make_magnet_uri(metadata)))
        handle = self.engine.handles[row['id']]
        handle.set_metadata(metadata.metadata())
        deadline = time.monotonic() + 5
        cached = self.engine.directory / f"{row['id']}.torrent"
        while not cached.exists() and time.monotonic() < deadline:
            self.engine.tick()
            time.sleep(.05)
        self.assertTrue(cached.exists())
        self.assertEqual(lt.torrent_info(str(cached)).info_hashes(), metadata.info_hashes())
        self.engine.dispatch(dict(command='stop', target=str(row['id'])))
        other = Engine(self.root)
        restored = other.state['torrents'][0]
        self.assertIsNotNone(other.params(restored).ti)
        other.dispatch(dict(command='start', target=str(row['id'])))
        self.assertTrue(other.handles[row['id']].status().has_metadata)
        other.session.pause()
        other.handles.clear()

    def test_hybrid_duplicates_match_either_hash_in_both_orders(self):
        (self.root / 'payload').write_bytes(b'hello')
        storage = lt.file_storage()
        storage.add_file('payload', 5)
        torrent = lt.create_torrent(storage)
        lt.set_piece_hashes(torrent, str(self.root))
        self.source.write_bytes(lt.bencode(torrent.generate()))
        hashes = lt.torrent_info(str(self.source)).info_hashes()
        self.assertTrue(hashes.has_v1() and hashes.has_v2())
        magnets = ['magnet:?xt=urn:btih:' + str(hashes.v1),
                   'magnet:?xt=urn:btmh:1220' + str(hashes.v2)]
        for magnet in magnets:
            for magnet_first in (False, True):
                with self.subTest(magnet=magnet, magnet_first=magnet_first):
                    file_add = dict(command='add', kind='torrent', source=str(self.source))
                    magnet_add = dict(command='add', kind='magnet', source=magnet)
                    first, second = (magnet_add, file_add) if magnet_first else (file_add, magnet_add)
                    row = self.engine.dispatch(first)
                    with self.assertRaisesRegex(ValueError, 'already managed'):
                        self.engine.dispatch(second)
                    self.assertEqual(len(self.engine.state['torrents']), 1)
                    self.assertTrue(self.engine.handles[row['id']].is_valid())
                    self.engine.dispatch(dict(command='stop', target=str(row['id'])))
                    with self.assertRaisesRegex(ValueError, 'already managed'):
                        self.engine.dispatch(second)
                    self.engine.dispatch(dict(command='remove', target=str(row['id'])))

    def test_worker_authentication_deadline_and_recovery(self):
        import socket
        import struct
        import threading
        from terrence.client import connect_worker
        from terrence.worker import accept_worker

        for partial in (b'', b'\x00', struct.pack('!i', 100) + b'x'):
            with self.subTest(partial=partial), socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                listener.settimeout(2)
                errors = []
                expired = threading.Event()

                def server():
                    try:
                        with self.assertRaises(TimeoutError):
                            accept_worker(listener, b'test', timeout=.1)
                        expired.set()
                        with accept_worker(listener, b'test') as connection:
                            self.assertEqual(connection.recv_bytes(), b'ping')
                            connection.send_bytes(b'pong')
                    except BaseException as error:
                        errors.append(error)

                thread = threading.Thread(target=server)
                thread.start()
                try:
                    with socket.create_connection(listener.getsockname()) as stalled:
                        stalled.recv(1024)  # Wait until the worker sends its challenge.
                        if partial:
                            stalled.sendall(partial)
                        self.assertTrue(expired.wait(1), 'Authentication did not time out')
                        with connect_worker(listener.getsockname(), b'test', timeout=2) as connection:
                            connection.send_bytes(b'ping')
                            self.assertTrue(connection.poll(2))
                            self.assertEqual(connection.recv_bytes(), b'pong')
                finally:
                    thread.join(3)
                self.assertFalse(thread.is_alive())
                if errors:
                    raise errors[0]

    def test_remove_keeps_files_and_ids_are_not_reused(self):
        self.add()
        self.engine.dispatch(dict(command='stop', target='1'))
        folder = self.root / 'downloads' / '1'
        folder.mkdir(exist_ok=True)
        payload = folder / 'keep.txt'
        payload.write_text('keep')
        self.engine.dispatch(dict(command='remove', target='1'))
        self.assertTrue(payload.exists())
        self.assertEqual(self.add()['id'], 2)

    def test_delete_stopped_files(self):
        self.add()
        self.engine.dispatch(dict(command='stop', target='1'))
        folder = self.root / 'downloads' / '1'
        folder.mkdir(exist_ok=True)
        (folder / 'remove.txt').write_text('remove')
        self.engine.dispatch(dict(command='remove', target='1', delete_files=True))
        self.assertFalse(folder.exists())

    def test_remove_active_deletes_containing_folder(self):
        self.add()
        folder = self.root / 'downloads' / '1'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'extra.txt').write_text('test')
        self.engine.dispatch(dict(command='remove', target='1', delete_files=True))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.engine.tick()
            if not folder.exists() and not self.engine.state.get('pending_folder_cleanup'):
                break
            time.sleep(.05)
        self.assertFalse(folder.exists())
        self.assertFalse(self.engine.state.get('pending_folder_cleanup'))

    def test_remove_empty_folder_without_deleting_files(self):
        self.add()
        self.engine.dispatch(dict(command='stop', target='1'))
        folder = self.root / 'downloads' / '1'
        folder.mkdir(parents=True, exist_ok=True)
        self.engine.dispatch(dict(command='remove', target='1'))
        self.assertFalse(folder.exists())

    def test_settings_persist(self):
        result = self.engine.dispatch(dict(command='settings', seed_completed='true'))
        self.assertTrue(result['seed_completed'])
        other = Engine(self.root)
        self.assertTrue(other.settings['seed_completed'])

    def test_file_defaults_and_live_reload(self):
        path = self.root / 'terrence.json'
        self.assertTrue(path.exists())
        path.write_text(json.dumps({'auto_start': False, 'download_directory': 'incoming',
                                    'download_rate_limit': 1048576, 'enable_dht': False}))
        row = self.add()
        self.assertEqual(row['status'], 'stopped')
        self.assertNotIn(row['id'], self.engine.handles)
        self.assertEqual(Path(row['save_path']), self.root / 'incoming' / '1')
        self.assertEqual(self.engine.session.get_settings()['download_rate_limit'], 1048576)
        self.assertFalse(self.engine.session.get_settings()['enable_dht'])
        self.engine.dispatch(dict(command='settings', download_directory='elsewhere'))
        self.engine.dispatch(dict(command='start', target='1'))
        self.assertEqual(Path(self.engine.handles[1].status().save_path), self.root / 'incoming' / '1')

    def test_invalid_settings_and_cli_updates(self):
        path = self.root / 'terrence.json'
        original = path.read_text()
        for updates in ({'upload_rate_limit': -1}, {'auto_start': 'invalid'},
                        {'download_directory': '../outside'}):
            with self.assertRaises(ValueError):
                self.engine.dispatch(dict(command='settings', **updates))
            self.assertEqual(path.read_text(), original)
        for values in ({'unknown': 1}, {'enable_dht': 'false'}, {'upload_rate_limit': True}, []):
            path.write_text(json.dumps(values))
            with self.assertRaises(ValueError):
                self.engine.dispatch(dict(command='list'))
        path.write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            self.engine.dispatch(dict(command='list'))
        path.write_text(original)

    def test_start_override_and_custom_directory_removal(self):
        self.engine.dispatch(dict(command='settings', auto_start='false', download_directory='incoming'))
        row = self.engine.dispatch(dict(command='add', kind='torrent', source=str(self.source), start=True))
        self.assertEqual(row['status'], 'running')
        self.engine.dispatch(dict(command='stop', target='1'))
        folder = self.root / 'incoming' / '1'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'payload.txt').write_text('test')
        self.engine.dispatch(dict(command='settings', download_directory='elsewhere'))
        self.engine.dispatch(dict(command='remove', target='1', delete_files=True))
        self.assertFalse(folder.exists())
        self.engine.dispatch(dict(command='settings', auto_start='true'))
        row = self.engine.dispatch(dict(command='add', kind='torrent', source=str(self.source), start=False))
        self.assertEqual(row['status'], 'stopped')

    def test_legacy_settings_migration(self):
        isolated = self.root / 'legacy'
        (isolated / '.terrence').mkdir(parents=True)
        (isolated / '.terrence' / 'state.json').write_text(json.dumps({
            'next_id': 1, 'settings': {'seed_completed': True}, 'torrents': []}))
        other = Engine(isolated)
        self.assertTrue(other.settings['seed_completed'])
        self.assertTrue(json.loads((isolated / 'terrence.json').read_text())['seed_completed'])
        self.assertNotIn('settings', other.state)

    def test_copy_destination_defaults_override_and_persistence(self):
        self.engine.dispatch(dict(command='settings', copy_to='finished', auto_start='false'))
        row = self.engine.dispatch(dict(command='add', kind='torrent', source=str(self.source),
                                        copy_to=str(self.root / 'override')))
        self.assertEqual(row['copy_to'], str(self.root / 'override'))
        self.engine.dispatch(dict(command='settings', copy_to='changed'))
        other = Engine(self.root)
        self.assertEqual(other.state['torrents'][0]['copy_to'], row['copy_to'])
        self.assertEqual(other.settings['copy_to'], 'changed')
        self.engine.dispatch(dict(command='remove', target='1'))
        self.assertIsNone(self.add()['copy_to'])
        self.engine.dispatch(dict(command='settings', copy_to=''))
        self.assertIsNone(self.engine.settings['copy_to'])

    def test_copy_validation(self):
        for value in ('', ' ', 123, False):
            with self.assertRaises(ValueError):
                self.engine.dispatch(dict(command='add', kind='torrent', source=str(self.source), copy_to=value))
        for value in ('downloads/1', 'downloads', '.terrence/copies', '.git/copies'):
            with self.assertRaises(ValueError):
                self.engine.dispatch(dict(command='add', kind='torrent', source=str(self.source), copy_to=value))
        with self.assertRaises(ValueError):
            self.engine.dispatch(dict(command='settings', copy_to=123))

    def test_copy_failure_does_not_interrupt_completion_and_retries(self):
        row = self.add()
        row['copy_to'] = str(self.root / 'finished')
        handle = Mock()
        handle.status.return_value = Mock(name='example', progress=1, download_rate=0,
                                          upload_rate=0, is_seeding=True)
        handle.status.return_value.name = 'example'
        handle.status.return_value.errc.value.return_value = 0
        self.engine.handles[row['id']] = handle
        with patch.object(self.engine, 'copy_completed', side_effect=OSError('destination unavailable')):
            self.engine.tick()
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['copy_error'], 'destination unavailable')
        with patch.object(self.engine, 'copy_completed') as copy:
            self.engine.tick()
            copy.assert_called_once()
            self.assertEqual(copy.call_args.args[0]['id'], row['id'])
            self.assertIs(copy.call_args.args[1], handle)

    def test_info_active_and_stopped(self):
        self.add()
        details = self.engine.dispatch(dict(command='info', target='example'))
        self.assertTrue(details['live'])
        self.assertEqual(details['total_size'], 12)
        self.assertEqual(details['files'][0]['path'], 'example.txt')
        self.assertIsNone(details['tracker_seeds'])
        self.assertIsNone(details['tracker_leechers'])
        self.assertEqual(details['connected_leechers'], 0)
        self.engine.dispatch(dict(command='stop', target='1'))
        details = self.engine.dispatch(dict(command='info', target='1'))
        self.assertFalse(details['live'])
        self.assertNotIn(1, self.engine.handles)
        self.assertEqual(details['total_size'], 12)
        self.assertIsNone(details['files'][0]['completed_bytes'])
        with self.assertRaisesRegex(ValueError, 'Unknown torrent'):
            self.engine.dispatch(dict(command='info', target='missing'))

    def test_list_stays_responsive_during_completion_copy(self):
        import threading
        row = self.add()
        row['copy_to'] = str(self.root / 'finished')
        handle = Mock()
        handle.status.return_value = Mock(progress=1, download_rate=0, upload_rate=0, is_seeding=True)
        handle.status.return_value.name = 'example'
        handle.status.return_value.errc.value.return_value = 0
        self.engine.handles[row['id']] = handle
        entered, release = threading.Event(), threading.Event()

        def slow_copy(snapshot, handle):
            entered.set()
            release.wait(5)
            snapshot['copied_to'] = snapshot['copy_to']

        with patch.object(self.engine, 'copy_completed', side_effect=slow_copy):
            try:
                self.engine.dispatch({'command': 'list'})
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                self.assertEqual(len(self.engine.dispatch({'command': 'list'})), 1)
                self.assertLess(time.monotonic() - started, 1)
            finally:
                release.set()
                self.engine.io_jobs[('copy', row['id'])].result(timeout=2)
            self.engine.tick(background=True)
            self.assertEqual(row['copied_to'], row['copy_to'])

    def test_connection_handshake_times_out(self):
        import socket
        import threading
        from terrence.client import connect_worker
        release = threading.Event()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()

            def stalled_worker():
                with listener.accept()[0]:
                    release.wait(2)

            thread = threading.Thread(target=stalled_worker)
            thread.start()
            try:
                with self.assertRaises(TimeoutError):
                    connect_worker(listener.getsockname(), b'test', timeout=.1)
            finally:
                release.set()
                thread.join(2)

    def test_completed_payload_stops_seeding(self):
        self.check_completion_copy(seed=False)

    def test_completion_copies_while_seeding(self):
        self.check_completion_copy(seed=True)

    def check_completion_copy(self, seed):
        payload = b'hello world!'
        self.source.write_bytes(lt.bencode({b'info': {
            b'name': b'example.txt', b'length': len(payload), b'piece length': 16384,
            b'pieces': hashlib.sha1(payload).digest()}}))
        folder = self.root / 'downloads' / '1'
        folder.mkdir()
        (folder / 'example.txt').write_bytes(payload)
        row = self.add()
        # Older in-progress torrents have no copy_to field at all.
        if not seed:
            row.pop('copy_to')
        self.engine.dispatch(dict(command='settings', copy_to='finished', seed_completed=seed))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.engine.tick()
            if row.get('copied_to'):
                break
            time.sleep(.05)
        self.assertEqual(row['status'], 'running' if seed else 'completed')
        self.assertEqual(self.engine.state['torrents'][0]['progress'], 1)
        self.assertEqual((self.root / 'finished' / 'example.txt').read_bytes(), payload)
        self.assertEqual((folder / 'example.txt').read_bytes(), payload)
        self.assertEqual(row['copied_to'], str(self.root / 'finished'))
        with patch.object(self.engine, 'copy_completed') as copy:
            self.engine.tick()
            copy.assert_not_called()

    def test_background_round_trip(self):
        from terrence.client import request
        isolated = self.root / 'background'
        isolated.mkdir()
        try:
            self.assertEqual(request(isolated, {'command': 'list'}), [])
            added = request(isolated, dict(command='add', kind='torrent', source=str(self.source), alias='background'))
            self.assertEqual(added['id'], 1)
            rows = request(isolated, {'command': 'list'})
            self.assertEqual(rows[0]['alias'], 'background')
            request(isolated, dict(command='stop', target='1'))
        finally:
            request(isolated, {'command': 'shutdown'}, start=False)
            deadline = time.monotonic() + 5
            while (isolated / '.terrence' / 'endpoint.json').exists() and time.monotonic() < deadline:
                time.sleep(.05)


if __name__ == '__main__':
    unittest.main()
