import argparse
import json
from pathlib import Path

from .client import request


def main():
    parser = argparse.ArgumentParser(description='Manage torrents in the current directory')
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add')
    add.add_argument('kind', choices=['torrent', 'magnet'])
    add.add_argument('source', help='Torrent file/HTTP(S) URL, or magnet URI')
    add.add_argument('--alias')
    listing = commands.add_parser('list')
    listing.add_argument('--json', action='store_true')
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
            print('ID  ALIAS  STATUS  PROGRESS  DOWN KiB/s  UP KiB/s  ETA  NAME')
            for row in result:
                print(f"{row['id']}  {row['alias'] or '-'}  {row['status']}  "
                      f"{row.get('progress', 0):.1%}  {row.get('download_rate', 0)/1024:.1f}  "
                      f"{row.get('upload_rate', 0)/1024:.1f}  {row.get('eta', '-') }  {row.get('name', '')}")
                if row.get('error'):
                    print(f"    Error: {row['error']}")
        else:
            print(json.dumps(result, indent=2))
    except (ValueError, OSError, TimeoutError) as error:
        parser.exit(1, f'Error: {error}\n')
