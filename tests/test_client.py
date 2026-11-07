import tempfile
import unittest
import hashlib
import time
from pathlib import Path

import libtorrent as lt

from torrenting.worker import Engine


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
        self.assertTrue(other.state['settings']['seed_completed'])

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
        from torrenting.client import request
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
            while (isolated / '.torrenting' / 'endpoint.json').exists() and time.monotonic() < deadline:
                time.sleep(.05)


if __name__ == '__main__':
    unittest.main()
