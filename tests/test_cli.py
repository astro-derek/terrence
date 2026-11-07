import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from terrence.cli import main


class VersionTests(unittest.TestCase):
    def test_version_without_worker(self):
        for arguments in (['version'], ['--version']):
            with self.subTest(arguments=arguments), patch('sys.argv', ['terrence', *arguments]), \
                    patch('terrence.cli.version', return_value='1.2.3'), \
                    patch('terrence.cli.request') as request, redirect_stdout(io.StringIO()) as output:
                if arguments == ['--version']:
                    with self.assertRaises(SystemExit) as exit:
                        main()
                    self.assertEqual(exit.exception.code, 0)
                else:
                    main()
                self.assertEqual(output.getvalue().strip(), 'terrence 1.2.3')
                request.assert_not_called()
