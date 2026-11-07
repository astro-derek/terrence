# Terrence

A Python command-line BitTorrent client powered by libtorrent. Add torrent files,
torrent URLs, or magnet links, then manage background transfers using persistent
numeric IDs and optional aliases.

Each working directory has its own torrent list, settings, and downloads. Run
Terrence from the same directory to manage the same torrents.

## Features

- Download from local `.torrent` files, HTTP(S) torrent URLs, and magnet links.
- Start, stop, pause, and resume transfers by ID or alias.
- View aligned listings with progress, speeds, and estimated time remaining.
- Inspect seeds, leechers, trackers, metadata, and file progress.
- Export listings and detailed information as JSON.
- Remove torrents with optional file deletion.
- Configure whether completed torrents continue seeding.
- Set directory-local defaults in `terrence.json` for auto-start, download location,
  session transfer limits, and DHT discovery.

## Requirements

Python 3.10+ and libtorrent Python bindings (`>=2.0.11,<3`). Installation fetches
libtorrent as a dependency; a compatible wheel or a locally built binding must
be available for your platform and Python version.

Windows has been tested locally. Linux/macOS have process and file-locking
support in the code but have not been verified locally.

## Installation

Clone the repository:

```sh
git clone https://github.com/astro-derek/terrence.git
cd terrence
```

### Install a command available from any directory

Use pipx to install from your local checkout into a separate environment and
expose `terrence` on your user PATH.

On Windows, open PowerShell outside an activated virtual environment:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install .
```

Restart your terminal after `ensurepath`. If using an integrated terminal, you
may also need to restart your editor.

On Linux/macOS, install pipx using its
[platform instructions](https://pipx.pypa.io/latest/how-to/install-pipx.html), then
run these commands from the checkout:

```sh
pipx ensurepath
pipx install .
```

Open a new terminal and verify:

```sh
terrence --help
terrence version
```

### Install for local development

On Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

On Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

For a local installation, replace `terrence` in examples with
`.\.venv\Scripts\terrence` on Windows or `.venv/bin/terrence` on Linux/macOS.
You can also use that environment's Python with `-m terrence`.
Editable installations pick up source changes without reinstalling; restart
existing workers to load changes to worker code.

## Quick start

From the directory where you want to store downloads:

```sh
terrence add torrent "/path/to/example.torrent" --alias example
terrence list
terrence info example
terrence pause example
terrence resume example
```

To configure defaults before adding torrents:

```sh
terrence settings --download-directory incoming --auto-start false
terrence add torrent "example.torrent" --alias later
terrence start later
```

The example adds the torrent stopped and saves it under `incoming/<id>/`.

Adding a torrent starts it immediately by default. Use `--no-start` to add it
stopped, or `--start` to override a disabled auto-start default.
HTTP(S) torrent URLs and magnet links
are also accepted; replace these placeholders with actual sources:

```sh
terrence add torrent "https://example.org/example.torrent"
terrence add magnet "magnet:?xt=urn:btih:..." --alias other
```

## Commands

`<target>` is a numeric ID or alias. IDs persist across worker restarts and are
not reused after removal. Aliases are optional, unique within the working
directory, and cannot be purely numeric.

| Command | Behavior |
| --- | --- |
| `version` or `--version` | Show the installed Terrence package version without starting a worker. |
| `add torrent <file-or-url> [--alias <name>] [--start / --no-start] [--copy-to <path>]` | Add a torrent file or HTTP(S) URL, optionally overriding start and completion copy defaults. |
| `add magnet <uri> [--alias <name>] [--start / --no-start] [--copy-to <path>]` | Add a magnet link, optionally overriding start and completion copy defaults. |
| `list [--json]` | Show managed torrents, status, progress, speeds, and ETA. |
| `info <target> [--json]` | Show detailed information with file and tracker tables. |
| `pause <target>` | Pause activity while retaining the torrent in the session. |
| `resume <target>` | Resume a paused torrent. |
| `stop <target>` | Release the torrent's active session resources; retain state and files. |
| `start <target>` | Start a stopped torrent or restart a paused/completed torrent. |
| `alias <target> [<name>]` | Set an alias; omit the name to clear it. |
| `remove <target> [--delete-files]` | Remove a torrent; keep files unless explicitly requested otherwise. |
| `settings` | Show this directory's settings. |
| `settings --seed-completed true` | Allow active torrents to continue seeding after completion. |
| `settings --seed-completed false` | Stop seeding on completion (default). |
| `settings --auto-start true/false` | Set whether new torrents start automatically. |
| `settings --download-directory <path>` | Set the relative download folder for new torrents. |
| `settings --copy-to <path>` | Set the completion copy directory for torrents without an explicit override. |
| `settings --no-copy-to` | Disable the default completion copy directory. |
| `settings --download-rate-limit <bytes-per-second>` | Set the session download limit; `0` means unlimited. |
| `settings --upload-rate-limit <bytes-per-second>` | Set the session upload limit; `0` means unlimited. |
| `settings --enable-dht true/false` | Enable or disable DHT peer discovery. |
| `shutdown` | Stop this directory's worker and transfers, retaining saved state. |

Use `terrence <command> --help` for command options.
In the table, `true/false` means choose either `true` or `false`; pass only one
of `--start` and `--no-start`. Settings flags can be combined in one command.

### Status and information

`list` reports speeds in KiB/s and ETA as hours and minutes remaining, such as
`2h 05m`. Partial minutes round up. Unknown ETA displays as `-` in the table.
JSON output keeps ETA in seconds, or `null` when unknown.

`info` includes source, hashes, save path, transfer rates and totals, piece
information, web seeds, and peer counts. Files appear in a table with size,
completed bytes, progress, and path; trackers appear with tier and URL.
Sizes and totals are bytes; detailed transfer rates are bytes/second. Transfer
totals are not retained across removal from the active session or worker restarts.

- **Connected seeds/leechers:** current peer connections.
- **Known peers/seeds:** discovered peers, which may not be reachable.
- **Tracker seeds/leechers:** tracker-reported swarm counts; unavailable counts
  display as `Unknown` in text or `null` in JSON.

Stopped torrents have no live swarm statistics. Inspecting one does not restart
that torrent. Magnet file details require metadata, which is not currently
retained when a magnet leaves the active session.

## Storage and background operation

### Directory defaults

Terrence creates `terrence.json` when a worker first starts in the current working
directory. Help commands do not create files or start a worker.
Edit this file or use `terrence settings` to view and update defaults:

```json
{
  "seed_completed": false,
  "auto_start": true,
  "download_directory": "downloads",
  "copy_to": null,
  "download_rate_limit": 0,
  "upload_rate_limit": 0,
  "enable_dht": true
}
```

| Setting | Meaning |
| --- | --- |
| `seed_completed` | Keep active torrents seeding after completion. Default: `false`. |
| `auto_start` | Start newly added torrents. Default: `true`; override per add with `--start` or `--no-start`. |
| `download_directory` | Relative subdirectory for new downloads. Default: `downloads`; must remain inside the working directory, outside `.terrence` and `.git`. |
| `copy_to` | Copy completed torrent contents to this directory. Relative to the working directory, or absolute. Default: `null` (disabled); override per add with `--copy-to PATH`. |
| `download_rate_limit` | Combined session download limit in bytes/second; `0` means unlimited. |
| `upload_rate_limit` | Combined session upload limit in bytes/second; `0` means unlimited. |
| `enable_dht` | Enable DHT peer discovery. Default: `true`. |

```sh
terrence settings
terrence settings --auto-start false
terrence settings --download-directory incoming --download-rate-limit 1048576
terrence settings --upload-rate-limit 262144 --enable-dht true
terrence add torrent "example.torrent" --start
terrence add torrent "example.torrent" --copy-to "D:/Completed"
terrence settings --copy-to "finished"
terrence settings --no-copy-to
```

Manual edits are loaded on the next command; CLI settings changes are saved
and applied immediately. `terrence settings` displays effective settings, including
defaults for omitted keys. Precedence is: explicit `add --start`/`--no-start`/`--copy-to`
flags, then values in `terrence.json`, then built-in defaults.
Rate limits must be integers from `0` to `2147483647`; `1048576` bytes/second is
1 MiB/s. Boolean values in JSON must be `true` or `false`, without quotes.
Invalid JSON, unknown keys,
and invalid values produce an error without replacing the file. Fix the file
and retry; `shutdown` remains available even if the file is invalid.

Download-directory and auto-start defaults affect new torrents only. Existing
torrents keep their stored paths, including when restarted or removed. Download
and upload limits apply to the whole directory's session. Completed torrents
are not automatically restarted when seeding is enabled.

An explicit `add --copy-to` destination is saved for that torrent. Otherwise,
Terrence uses the current `copy_to` setting on completion, including for existing
in-progress torrents. Manual settings edits apply on the next command.
On completion, Terrence copies the torrent's files and directory
layout directly into that destination, retaining the originals for seeding. Copies
also run when `seed_completed` is enabled, and a successful copy is recorded so it
is not repeated on restart. Matching destination files are overwritten. Use distinct
destinations for torrents with conflicting filenames. Destinations must not overlap
the torrent's download directory or be inside `.terrence` or `.git`.
Copy failures appear as `copy_error` in torrent details (and in `list`) and are
retried by the worker while the torrent remains attached. Stopping a torrent also
stops retries until it is started again.

Existing settings in `.terrence/state.json` migrate into `terrence.json` when
the new file does not exist. An existing `terrence.json` takes precedence.
Local `terrence.json` files are ignored by Git.

### Files and worker lifecycle

Terrence creates these directories where you run it:

```text
.terrence/
  state.json      # IDs, aliases, paths, and saved torrent state
  worker.log      # Background worker diagnostics
  <id>.torrent    # Imported metadata for torrent file/URL sources
downloads/
  <id>/           # Files belonging to this torrent
terrence.json     # User-editable defaults for this working directory
```

`downloads/` is the default; new torrents use a different folder if configured.
The worker also creates lock and connection files in `.terrence`. Keep this
directory private: it contains the local worker's authentication key and torrent
sources, which may include private tracker credentials.

Commands automatically start a worker when needed, including `list` and `info`.
The worker continues after the command exits. After `shutdown`, the next command
starts it again and restores previously active torrents. Workers do not start
automatically at login or after a reboot.

Completed torrents stop seeding by default. Changing `--seed-completed` does not
restart torrents already marked completed; use `start` to restart those.
`remove` deletes an empty torrent download folder but retains nonempty folders
and their files. `remove --delete-files` deletes the torrent's entire numeric
download folder and all its contents. Active folder deletion runs in the
background and retries while files are locked; pending cleanup survives worker
restarts. The parent download directory and separate completion copies are kept.

Fast-resume snapshots are not implemented: existing pieces are checked when a
torrent is reattached or a worker restarts. Magnet metadata may need fetching
again. Torrent search is not included.

## Updating and uninstalling

Completion copies and pending folder cleanup run in file-worker threads so
`list` and `info` do not wait for those operations to finish. While a completion
copy is pending, `stop` and `remove` ask you to retry after it finishes, keeping
the source files available to the copy. Connection setup times out after five
seconds if the background worker cannot complete its handshake; commands are
not automatically replayed after a timeout. Command responses have a separate
30-second timeout. Initial worker startup, torrent URL fetching, and disk checks
can still take time.

First run `terrence shutdown` in **each directory** with an active worker. Avoid
other Terrence commands until the update finishes, since they can restart workers.

Update your checkout, then reinstall from its directory:

```powershell
git pull
py -m pipx install --force .
```

On Linux/macOS use `pipx install --force .`.

On Windows, a permission error involving the pipx environment's
`Scripts\python.exe` commonly means a worker is still running. Shut down workers
and wait for them to exit before retrying. If necessary, inspect process command
lines in Task Manager to identify remaining `terrence.worker` processes.

To uninstall:

```sh
pipx uninstall terrence
```

Uninstalling keeps directory-local state and downloaded files.
It also preserves `terrence.json`. Reinstalling does not reset directory defaults.

## Try a local download

The repository includes a sample torrent and a loopback HTTP web seed. This
tests a real download of a 274,432-byte generated text file without public
trackers or peers.

After setting up the development environment, run this from the checkout in
one terminal:

```powershell
.\.venv\Scripts\python examples\local_torrent.py --serve
```

In another terminal, also from the checkout:

```sh
terrence add torrent examples/local-test/sample.torrent --alias local-test
terrence list
terrence info local-test
```

For a development-only installation, use the environment's `terrence` path
as described above. On Linux/macOS use `.venv/bin/python` for the seed.

The torrent should quickly reach `completed`, with its file at
`downloads/<id>/sample.txt`. The seed binds to `127.0.0.1:8765`; stop it with
Ctrl+C when finished. Run the script without `--serve` to regenerate sample files.

To remove the torrent and its downloaded copy:

```sh
terrence remove local-test --delete-files
```

## Development checks

From the checkout, after installing the development environment:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

On Linux/macOS substitute `.venv/bin/python`. Tests cover torrent lifecycle,
persistence, aliases, removal, completion, detailed information, and background
communication using generated local fixtures rather than public downloads.
