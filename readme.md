# terrence

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

### Project-local installation

Requires Python 3.10+ and libtorrent's Python bindings. From this directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

On Linux/macOS, use `.venv/bin/python` and `.venv/bin/terrence` instead of
the Windows `.venv\Scripts\` paths. A compatible libtorrent wheel or a locally
built libtorrent Python binding is required for your platform and Python version.

### Global command installation

Use pipx to make `terrence` available from any directory for your user account,
with its dependencies in a separate environment. No administrator access is
needed. These instructions install from this checkout, not from PyPI.

On Windows, open PowerShell outside an activated virtual environment:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install "C:\Users\dpleg\dev\python\torrenting"
```

Replace the checkout path if yours is different. Restart your terminal (and
VS Code if using its integrated terminal) after `ensurepath` updates PATH.

On macOS or Linux, install pipx using the
[official platform instructions](https://pipx.pypa.io/latest/how-to/install-pipx.html),
then run:

```sh
pipx ensurepath
pipx install /absolute/path/to/torrenting
```

Open a new terminal, then verify the installation:

```powershell
terrence --help
```

You can now use `terrence` in place of `.\.venv\Scripts\terrence` in the examples
below. Configuration and downloads still belong to the directory where you run
the command, so return to that directory to manage the same torrents.

To refresh the installed copy after changing the source, first run
`terrence shutdown` in each directory with an active worker, then reinstall:

```powershell
py -m pipx install --force "C:\Users\dpleg\dev\python\torrenting"
```

On macOS/Linux use `pipx install --force /absolute/path/to/torrenting`.
To uninstall the command, run `pipx uninstall terrence`; downloaded files and
directory-local `.terrence` state are retained.

## Usage

Run commands from the directory whose torrents you want to manage:

```powershell
.\.venv\Scripts\terrence add torrent "https://example.org/example.torrent" --alias example
.\.venv\Scripts\terrence add torrent "C:\path\example.torrent"
.\.venv\Scripts\terrence add magnet "magnet:?xt=urn:btih:..." --alias other
.\.venv\Scripts\terrence list
.\.venv\Scripts\terrence list --json
.\.venv\Scripts\terrence info 1
.\.venv\Scripts\terrence info example --json
.\.venv\Scripts\terrence pause example
.\.venv\Scripts\terrence resume example
.\.venv\Scripts\terrence stop 1
.\.venv\Scripts\terrence start 1
.\.venv\Scripts\terrence alias 1 new-name
.\.venv\Scripts\terrence remove 1
.\.venv\Scripts\terrence remove other --delete-files
.\.venv\Scripts\terrence settings --seed-completed true
.\.venv\Scripts\terrence shutdown
```

You can also run `python -m terrence` from this checkout without installing
the command, provided libtorrent is installed in that Python environment.

The background worker starts automatically and continues after the CLI exits.
`info <id-or-alias>` shows torrent metadata, source, hashes, save path, transfer
rates (bytes/second), transfer totals (bytes, for the current handle lifetime),
file sizes and progress, trackers, web seeds, and peer counts. `--json` provides
machine-readable output. Connected seeds and leechers describe current
connections; known peers may be offline. Tracker seeds/leechers are swarm counts
reported by trackers and show `Unknown` (JSON `null`) when unavailable, rather
than zero. See the [libtorrent status definitions](https://www.libtorrent.org/reference-Torrent_Status.html).
Stopped torrents retain metadata but have no live swarm statistics; `info` does
not restart them. Magnets awaiting metadata may not yet have file details.

`list` shows progress, status, speeds in KiB/s, and ETA in seconds (`None` when
unknown). IDs persist and are never reused. Aliases are optional, unique within
the working directory, and cannot be purely numeric. Omit the name from `alias`
to clear it. Added torrents start immediately; duplicate torrents are rejected.

Configuration and saved torrent state live in `.terrence` in the working directory.
State and settings are stored in `.terrence/state.json`; worker diagnostics
are in `.terrence/worker.log`. Downloads live in `downloads/<id>/` so each
torrent has a separate directory. Run commands from the same directory each
time. Keep `.terrence` private: it contains the local worker's authentication key.

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

### Try a local download

A generated sample torrent is available at `examples/local-test/sample.torrent`.
Its 274,432-byte text payload is served by a local HTTP web seed, so you can test
a real download without public trackers or peers.

From the project directory, run this in one terminal and leave it running:

```powershell
.\.venv\Scripts\python examples\local_torrent.py --serve
```

In another terminal, also from the project directory:

```powershell
.\.venv\Scripts\terrence add torrent examples\local-test\sample.torrent --alias local-test
.\.venv\Scripts\terrence list
```

The torrent should reach `completed`; its file will be `downloads/<id>/sample.txt`.
The sample is small and will usually finish immediately. The server binds only
to `127.0.0.1:8765`. Press Ctrl+C in the server terminal when finished. To remove
the torrent and its downloaded copy:

```powershell
.\.venv\Scripts\terrence remove local-test --delete-files
```

Run `examples/local_torrent.py` without `--serve` to regenerate the sample files.

### Automated checks

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Tests use generated torrent metadata and local payload files; they do not
download public torrents.
