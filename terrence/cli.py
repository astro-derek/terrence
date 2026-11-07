import argparse
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .client import request


def version_text():
    try:
        return f'terrence {version("terrence")}'
    except PackageNotFoundError:
        return 'terrence (version unavailable; package is not installed)'


def format_eta(seconds):
    if seconds is None:
        return '-'
    # Round up so an unfinished minute is still shown as time remaining.
    minutes = (max(0, int(seconds)) + 59) // 60
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m'


def print_torrents(torrents):
    headings = ['ID', 'ALIAS', 'STATUS', 'PROGRESS', 'DOWN KiB/s', 'UP KiB/s', 'ETA', 'NAME']
    rows = [
        [str(row['id']), row['alias'] or '-', row['status'],
         f"{row.get('progress', 0):.1%}",
         f"{row.get('download_rate', 0) / 1024:.1f}",
         f"{row.get('upload_rate', 0) / 1024:.1f}",
         format_eta(row.get('eta')), row.get('name', '')]
        for row in torrents
    ]
    widths = [max(len(values[index]) for values in [headings, *rows])
              for index in range(len(headings))]

    def format_row(values):
        return '  '.join(value.ljust(width) for value, width in zip(values, widths)).rstrip()

    print(format_row(headings))
    for torrent, values in zip(torrents, rows):
        print(format_row(values))
        if torrent.get('error'):
            print(f"    Error: {torrent['error']}")
        if torrent.get('copy_error'):
            print(f"    Copy error: {torrent['copy_error']}")


def print_table(headings, rows):
    widths = [max(len(row[i]) for row in [headings, *rows])
              for i in range(len(headings))]
    for row in [headings, *rows]:
        print('  '.join(value.ljust(width) for value, width in zip(row, widths)).rstrip())


def print_info(result):
    details = {key: value for key, value in result.items() if key not in ('files', 'trackers')}
    width = max((len(key.replace('_', ' ')) for key in details), default=0)
    for key, value in details.items():
        label = key.replace('_', ' ').capitalize()
        if isinstance(value, (list, dict)):
            value = json.dumps(value, indent=2)
        elif value is None:
            value = 'Unknown'
        elif key == 'progress':
            value = f'{value:.1%}'
        print(f'{label:<{width}} : {value}')

    print('\nFiles')
    files = result.get('files', [])
    if files:
        rows = []
        for file in files:
            size, completed = file['size'], file.get('completed_bytes')
            progress = 'Unknown' if completed is None else f'{completed / size:.1%}' if size else '100.0%'
            rows.append([str(size), str(completed) if completed is not None else 'Unknown',
                         progress, file['path']])
        print_table(['SIZE (bytes)', 'COMPLETED (bytes)', 'PROGRESS', 'PATH'], rows)
    else:
        print('No file information available.')

    print('\nTrackers')
    trackers = result.get('trackers', [])
    if trackers:
        print_table(['TIER', 'URL'], [
            [str(tracker['tier']) if tracker.get('tier') is not None else '-', tracker['url']]
            for tracker in trackers])
    else:
        print('No trackers.')


def main():
    parser = argparse.ArgumentParser(
        prog='terrence', formatter_class=argparse.RawDescriptionHelpFormatter,
        description='Download and manage torrents from the command line.\n'
                    'Transfers continue in the background after the command exits.',
        epilog='Examples:\n'
               '  terrence add torrent "example.torrent" --alias example\n'
               '  terrence list\n'
               '  terrence info example\n'
               '  terrence pause 1\n'
               '  terrence resume 1\n'
               '  terrence settings --auto-start false\n'
               '  terrence add torrent "later.torrent" --no-start\n'
               '  terrence shutdown\n\n'
               'Defaults: terrence.json; state: .terrence/ in the current directory.\n'
               'Files: downloads/<id>/ unless download_directory is configured.\n'
               'Each directory manages its own torrents. IDs persist; aliases are optional.\n'
               'Commands start a background worker when needed, including list and info.\n'
               'Completed torrents stop seeding by default.\n\n'
               'Edit terrence.json or use terrence settings to change defaults.\n'
               'Manual edits apply on the next command; explicit add flags override defaults.\n\n'
               'Run terrence <command> --help for details and more examples.')
    parser.add_argument('--version', action='version', version=version_text(),
                        help='Show the installed Terrence version and exit')
    commands = parser.add_subparsers(dest='command', required=True, title='commands', metavar='COMMAND')

    def command_help(name, summary, description, examples):
        return commands.add_parser(
            name, help=summary, description=description,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog='Examples:\n' + '\n'.join(f'  terrence {example}' for example in examples))

    add = command_help('add', 'Add a torrent or magnet link using directory defaults',
                       'Add a local .torrent file, an HTTP(S) torrent URL, or a magnet URI.\n'
                       'Quote sources containing spaces or shell characters such as &.\n'
                       'Start behavior and download folder use defaults from terrence.json.\n'
                       'Use --start or --no-start to override auto_start for this torrent.',
                       ['add torrent "example.torrent" --alias example',
                        'add torrent "later.torrent" --alias later --no-start',
                        'add torrent "example.torrent" --start',
                        'add torrent "https://example.org/example.torrent"',
                        'add magnet "magnet:?xt=urn:btih:<info-hash>" --alias other'])
    add.add_argument('kind', choices=['torrent', 'magnet'], help='Use torrent for a file/URL, or magnet for a magnet URI')
    add.add_argument('source', help='Local .torrent path, HTTP(S) torrent URL, or complete magnet URI')
    add.add_argument('--alias', metavar='NAME', help='Optional unique nickname in this directory; cannot be purely numeric')
    add.add_argument('--copy-to', metavar='PATH',
                     help='Copy completed contents to this directory, overriding copy_to in terrence.json')
    starting = add.add_mutually_exclusive_group()
    starting.add_argument('--start', dest='start', action='store_true', default=None,
                          help='Start immediately, overriding auto_start in terrence.json')
    starting.add_argument('--no-start', dest='start', action='store_false',
                          help='Add stopped, overriding auto_start in terrence.json')
    listing = command_help('list', 'List torrents, progress, speeds, and ETA',
                           'Show torrents managed in the current directory.\n'
                           'Speeds are KiB/s; ETA is hours and minutes remaining (e.g. 2h 05m).\n'
                           'Partial minutes round up; unknown ETA is -. JSON keeps ETA in seconds.',
                           ['list', 'list --json'])
    listing.add_argument('--json', action='store_true', help='Print JSON instead of a table; unknown values are null')
    info = command_help('info', 'Inspect peers, trackers, files, and torrent metadata',
                        'Show detailed status, seeds/leechers, transfer statistics, and metadata.\n'
                        'Files and trackers appear as tables. Detailed sizes are bytes; rates are bytes/s.\n'
                        'Tracker counts may be Unknown. Stopped torrents have no live swarm statistics.\n'
                        'Inspecting a stopped torrent does not restart that torrent.',
                        ['info 1', 'info example', 'info example --json'])
    info.add_argument('target', help='Persistent numeric ID or alias from list')
    info.add_argument('--json', action='store_true', help='Print JSON instead of formatted details; unknown values are null')
    actions = {
        'start': ('Start or restart a torrent',
                  'Start a stopped torrent or restart a paused/completed torrent.\n'
                  'Use the torrent\'s saved download path, even if directory defaults changed.\n'
                  'Existing pieces may be checked; completed torrents require seeding enabled to keep running.'),
        'stop': ('Stop transfers and release torrent resources',
                 'Stop downloading and seeding, removing the torrent from the active session.\n'
                 'Keep its ID, alias, state, and files. Use start to restart it.'),
        'pause': ('Pause transfers while retaining the session handle',
                  'Pause downloading and seeding while keeping the torrent ready to resume.\n'
                  'A stopped torrent must be started before it can be paused.'),
        'resume': ('Resume a paused torrent',
                   'Resume downloading/seeding after pause. For stopped torrents, use start.'),
        'remove': ('Remove a torrent, optionally deleting downloaded files',
                   'Remove a torrent from management. Downloaded files are kept by default.\n'
                   'Empty download folders are removed automatically.\n'
                   '--delete-files deletes the whole torrent download folder, including its contents.\n'
                   'Active folder deletion is retried in the background until file handles are released.'),
    }
    for name, (summary, description) in actions.items():
        examples = [f'{name} 1', f'{name} example']
        if name == 'remove':
            examples.append('remove example --delete-files')
        sub = command_help(name, summary, description, examples)
        sub.add_argument('target', help='Persistent numeric ID or alias from list')
        if name == 'remove':
            sub.add_argument('--delete-files', action='store_true', help='Delete the torrent download folder and all contents (default: keep files)')
    alias = command_help('alias', 'Set or clear a torrent nickname',
                         'Assign a unique alias within this directory, or omit NAME to clear it.\n'
                         'Aliases cannot be purely numeric. The numeric ID always remains usable.',
                         ['alias 1 example', 'alias example new-name', 'alias 1'])
    alias.add_argument('target', help='Persistent numeric ID or current alias from list')
    alias.add_argument('name', nargs='?', metavar='NAME', help='New unique nickname; omit to clear the current alias')
    settings = command_help('settings', 'Show or change this directory\'s settings',
                            'Read defaults from terrence.json in the current working directory.\n'
                            'The file is created automatically. Edit it or use these options.\n'
                            'No options: show effective settings, including defaults for omitted keys.\n'
                            'CLI changes are saved and applied immediately; manual edits load on the next command.\n'
                            'Unknown keys, invalid types, and invalid values are rejected.\n'
                            'Download directory and auto-start changes affect new torrents only.\n'
                            'Copy destination changes apply to torrents without an explicit --copy-to.\n'
                            'Existing files are not moved. Rate limits apply to the whole session.\n'
                            'Completed torrents stop seeding by default. Enabling seeding does not\n'
                            'restart completed torrents automatically; use start on those torrents.',
                            ['settings', 'settings --auto-start false',
                             'settings --download-directory incoming --download-rate-limit 1048576',
                             'settings --upload-rate-limit 262144',
                             'settings --download-rate-limit 0 --enable-dht false',
                             'settings --seed-completed true',
                             'settings --seed-completed false', 'start example'])
    settings.add_argument('--seed-completed', choices=['true', 'false'],
                          help='Continue seeding after completion: true to enable, false to stop (default setting: false)')
    settings.add_argument('--auto-start', choices=['true', 'false'],
                          help='Start newly added torrents automatically (default: true)')
    settings.add_argument('--download-directory', metavar='PATH',
                          help='Relative subdirectory inside the working directory, outside .terrence and .git; new torrents only (default: downloads)')
    copying = settings.add_mutually_exclusive_group()
    copying.add_argument('--copy-to', metavar='PATH',
                          help='Completion copy directory for torrents without an explicit --copy-to (relative or absolute)')
    copying.add_argument('--no-copy-to', dest='copy_to', action='store_const', const='',
                          help='Disable the default completion copy directory')
    settings.add_argument('--download-rate-limit', type=int, metavar='BYTES_PER_SECOND',
                          help='Combined download limit, 0..2147483647 bytes/second; 0 = unlimited (default)')
    settings.add_argument('--upload-rate-limit', type=int, metavar='BYTES_PER_SECOND',
                          help='Combined upload limit, 0..2147483647 bytes/second; 0 = unlimited (default)')
    settings.add_argument('--enable-dht', choices=['true', 'false'],
                          help='Enable DHT peer discovery (default: true)')
    command_help('shutdown', 'Stop this directory\'s background worker and transfers',
                 'Stop the background worker for the current directory, preserving state and files.\n'
                 'The next command starts it again and restores previously active torrents.\n'
                 'Before updating Terrence, shut down workers in every directory where it is running.',
                 ['shutdown'])
    command_help('version', 'Show the installed Terrence version',
                 'Print the installed package version and exit without starting a worker.\n'
                 'You can also use terrence --version.', ['version', '--version'])
    args = vars(parser.parse_args())
    if args['command'] == 'version':
        print(version_text())
        return
    json_output = args.pop('json', False)
    try:
        result = request(Path.cwd(), args, start=args['command'] != 'shutdown')
        if args['command'] == 'list' and not json_output:
            print_torrents(result)
        elif args['command'] == 'info' and not json_output:
            print_info(result)
        else:
            print(json.dumps(result, indent=2))
    except (ValueError, OSError, TimeoutError) as error:
        parser.exit(1, f'Error: {error}\n')
