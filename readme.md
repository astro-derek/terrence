# readme

## introduction
We want a command line program that allows us to manage torrents and magnet link. 

Functionality needed in first pass:
- add torrent which takes a torrent url
- add magnet which takes a magnet url
- list which lists currently managed torrents
- start, stop, pause, resume commands for torrents
- alias or numeric id to use as nickname when referring to torrent with commands
- current directory should be used for config
- create a default `downloads` directory where files can be stored 

## Answers to questions
1. this program should be the client that downloads the seed torrent
2. yes - make sure the list command will show these.
3. yes and yes
4. stop stops downloading and seeding. pause just pauses activity, start starts the download and resume resumes from pause.
    - stop disconnects and releases resources. pause keeps torrent ready to resume.
5. yes - you can create a settings or state json file to track this if necessary.
6. yes
7. yes
8. provide settings to control these settings. defaults are: completed torrents stop seeding. Yes - we need a removal command.
    - removal - yes... --delete-files should be specified if we want to delete the files.
9. make it interoperable if possible. python is required.
10. aliases - should be optional. each torrent should be given a numerical id by default. if the user wants to specify an alias, they can do so, but can refer to the torrent by id or alias with any command.

## Installation

Requires Python 3.10+ and libtorrent's Python bindings. From this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

On Linux/macOS, use `.venv/bin/python` and `.venv/bin/torrenting` instead of
the Windows `.venv\Scripts\` paths. A compatible libtorrent wheel or a locally
built libtorrent Python binding is required for your platform and Python version.

## Usage

Run commands from the directory whose torrents you want to manage:

```powershell
.\.venv\Scripts\torrenting add torrent "https://example.org/example.torrent" --alias example
.\.venv\Scripts\torrenting add torrent "C:\path\example.torrent"
.\.venv\Scripts\torrenting add magnet "magnet:?xt=urn:btih:..." --alias other
.\.venv\Scripts\torrenting list
.\.venv\Scripts\torrenting list --json
.\.venv\Scripts\torrenting pause example
.\.venv\Scripts\torrenting resume example
.\.venv\Scripts\torrenting stop 1
.\.venv\Scripts\torrenting start 1
.\.venv\Scripts\torrenting alias 1 new-name
.\.venv\Scripts\torrenting remove 1
.\.venv\Scripts\torrenting remove other --delete-files
.\.venv\Scripts\torrenting settings --seed-completed true
.\.venv\Scripts\torrenting shutdown
```

You can also run `python -m torrenting` from this checkout without installing
the command, provided libtorrent is installed in that Python environment.

The background worker starts automatically and continues after the CLI exits.
`list` shows progress, status, speeds in KiB/s, and ETA in seconds (`None` when
unknown). IDs persist and are never reused. Aliases are optional, unique within
the working directory, and cannot be purely numeric. Omit the name from `alias`
to clear it. Added torrents start immediately; duplicate torrents are rejected.

State and settings are stored in `.torrenting/state.json`; worker diagnostics
are in `.torrenting/worker.log`. Downloads live in `downloads/<id>/` so each
torrent has a separate directory. Run commands from the same directory each
time. Keep `.torrenting` private: it contains the local worker's authentication key.

`stop` removes the torrent from the active download session and releases its
resources. `pause` retains its session handle; `resume` applies only to paused
torrents. `start` also restarts stopped or completed torrents. Existing pieces
are checked when a torrent is reattached or the worker restarts; fast-resume
snapshots are not yet implemented. Magnet metadata may need fetching again.

Completed torrents stop seeding by default. `settings --seed-completed true`
allows active torrents to continue seeding; use `start` on already completed
torrents to restart them. `remove` keeps downloaded files unless `--delete-files`
is supplied. File deletion for an active torrent is asynchronous.

`shutdown` stops the worker and all transfers while retaining saved states.
The next command starts it again and restores active torrents. Workers do not
automatically start after a computer reboot. Windows is tested locally;
Linux/macOS support uses the same client with POSIX process and locking support.

## Tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Tests use generated torrent metadata and local payload files; they do not
download public torrents.

## Search EXT

```sh
torrenting search linux
torrenting search "linux distribution" --page 2 --limit 10
torrenting search linux --json
```

Search reads `https://ext.to/search/` and prints titles, detail-page URLs,
size, seeders, and leechers when available. `--page` selects a positive page
number; `--limit` caps that page's displayed results (1–100, default 20).
Search does not start a background worker or add downloads. Open a result's
URL to obtain a torrent file or magnet URI, then use the existing `add`
command. JSON output contains `title`, `url`, `size`, `seeders`, and `leechers`;
unavailable metadata is `null`.

EXT must be reachable through your network policy. HTTP errors and
unrecognized pages (including access challenges) are reported as errors rather
than empty results. This integration reads HTML, so site layout changes may
require parser updates. Live compatibility has not yet been verified in this
cloud environment because its network policy blocks EXT; parser and request
tests use representative HTML, not a captured live response.
