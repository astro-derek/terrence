import contextlib
import io
import json
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

from terrence.search import SearchError, parse_results, search
from terrence.cli import main

# Representative table markup; live compatibility must also be checked against EXT.
PAGE = '''<table><tr><th>Name</th><th>Size</th></tr><tr>
<td><a href="/category/">Category</a><a href="/example-linux-123/">Example &amp; Linux</a></td>
<td>1.2 GB</td><td class="text-success">1,234</td><td class="text-danger">5</td>
</tr><tr><td><a href="https://other.example/fake-456/">Advertisement</a></td></tr>
<tr><td><a href="/example-linux-123/">Duplicate</a></td></tr></table>'''


class SearchTests(unittest.TestCase):
    def test_parse_results_and_filter_links(self):
        self.assertEqual(parse_results(PAGE), [dict(title='Example & Linux',
            url='https://ext.to/example-linux-123/', size='1.2 GB', seeders=1234, leechers=5)])

    def test_missing_optional_fields(self):
        row, = parse_results('<tr><td><a href="/example-123/">Example</a></td></tr>')
        self.assertIsNone(row['size'])
        self.assertIsNone(row['seeders'])

    def test_empty_results_and_challenge(self):
        self.assertEqual(parse_results('<p>No torrents found</p>'), [])
        with self.assertRaisesRegex(SearchError, 'unrecognized'):
            parse_results('<title>Just a moment...</title>')

    @patch('terrence.search.urlopen')
    def test_request_encoding_and_limit(self, opener):
        response = opener.return_value.__enter__.return_value
        response.headers = Message()
        response.read.return_value = PAGE.encode()
        self.assertEqual(len(search('linux & test', page=2, limit=1)), 1)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, 'https://ext.to/search/?q=linux+%26+test&page=2')
        self.assertEqual(opener.call_args.kwargs['timeout'], 20)

    @patch('terrence.search.urlopen')
    def test_http_error(self, opener):
        opener.side_effect = HTTPError('https://ext.to', 403, 'Forbidden', {}, None)
        with self.assertRaisesRegex(SearchError, 'HTTP 403'):
            search('linux')

    @patch('terrence.search.urlopen')
    def test_invalid_input_does_not_request(self, opener):
        for args in [('', 1, 20), ('linux', 0, 20), ('linux', 1, 101)]:
            with self.assertRaises(ValueError):
                search(*args)
        opener.assert_not_called()

    @patch('terrence.cli.request')
    @patch('terrence.cli.search')
    def test_cli_json_does_not_start_worker(self, provider, worker):
        provider.return_value = parse_results(PAGE)
        output = io.StringIO()
        with patch('sys.argv', ['terrence', 'search', 'example', 'linux', '--json']), contextlib.redirect_stdout(output):
            main()
        self.assertEqual(json.loads(output.getvalue()), provider.return_value)
        provider.assert_called_once_with('example linux', page=1, limit=20)
        worker.assert_not_called()

    @patch('terrence.cli.search', side_effect=SearchError('EXT unavailable'))
    def test_cli_provider_failure(self, provider):
        with patch('sys.argv', ['terrence', 'search', 'linux']), contextlib.redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn('EXT unavailable', output.getvalue())
