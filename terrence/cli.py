import argparse
import json
from pathlib import Path

from .client import request


def print_torrents(torrents):
    headings = ['ID', 'ALIAS', 'STATUS', 'PROGRESS', 'DOWN KiB/s', 'UP KiB/s', 'ETA', 'NAME']
    rows = [
        [str(row['id']), row['alias'] or '-', row['status'],
         f"{row.get('progress', 0):.1%}",
         f"{row.get('download_rate', 0) / 1024:.1f}",
         f"{row.get('upload_rate', 0) / 1024:.1f}",
         str(row['eta']) if row.get('eta') is not None else '-', row.get('name', '')]
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
    parser = argparse.ArgumentParser(description='Manage torrents in the current directory')
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add')
    add.add_argument('kind', choices=['torrent', 'magnet'])
    add.add_argument('source', help='Torrent file/HTTP(S) URL, or magnet URI')
    add.add_argument('--alias')
    listing = commands.add_parser('list')
    listing.add_argument('--json', action='store_true')
    info = commands.add_parser('info', help='Show detailed torrent, peer, tracker, and file information')
    info.add_argument('target', help='Numeric ID or alias')
    info.add_argument('--json', action='store_true')
    for command in ['start', 'stop', 'pause', 'resume', 'remove']:
        sub = commands.add_parser(command)
        sub.add_argument('target', help='Numeric ID or alias')
        if command == 'remove':
            sub.add_argument('--delete-files', action='store_true')
    alias = commands.add_parser('alias')
    alias.add_argument('target')
    alias.add_argument('name', nargs='?', help='Omit to clear alias')
    settings = commands.add_parser('settings')
    settings.add_argument('--seed-completed', choices=['true', 'false'])
    commands.add_parser('shutdown', help='Stop the background client, keeping saved state')
    args = vars(parser.parse_args())
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
