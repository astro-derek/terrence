import tempfile
import unittest
import hashlib
import time
import json
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

    def test_completed_payload_stops_seeding(self):
        payload = b'hello world!'
        self.source.write_bytes(lt.bencode({b'info': {
            b'name': b'example.txt', b'length': len(payload), b'piece length': 16384,
            b'pieces': hashlib.sha1(payload).digest()}}))
        folder = self.root / 'downloads' / '1'
        folder.mkdir()
        (folder / 'example.txt').write_bytes(payload)
        self.add()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            self.engine.tick()
            if self.engine.state['torrents'][0]['status'] == 'completed':
                break
            time.sleep(.05)
        self.assertEqual(self.engine.state['torrents'][0]['status'], 'completed')
        self.assertEqual(self.engine.state['torrents'][0]['progress'], 1)

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
