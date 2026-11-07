# Repository instructions

## Versioning

- For every completed change to program behavior, CLI commands, dependencies, or
  packaging, update `[project].version` in `pyproject.toml` before declaring the
  work finished. Do this without waiting for the user to request a version bump.
- Use semantic versioning: increment the patch version for fixes, the minor
  version for backward-compatible features, and the major version for breaking
  changes. Reset lower components when incrementing a higher component.
- Bump once per logical change set, not once per file or intermediate edit.
  Documentation-only and test-only changes do not require a version bump.
- Keep `pyproject.toml` as the version source of truth; do not hardcode the version
  in Python code. The CLI reads installed package metadata.
- After a version bump, build a wheel and refresh the local editable installation.
  When the task includes reinstalling the global command, also refresh its pipx
  installation. Preserve the existing installation mode and dependencies.
- Verify the installed command reports the new version with both `terrence version`
  and `terrence --version`. Report the new version in the final response.

## Validation

- Run `.venv/Scripts/python -m unittest discover -s tests -v` on Windows
  (`.venv/bin/python` on Linux/macOS) after program changes.
- Run `git diff --check` before finishing.
- Shut down any running Terrence workers before reinstalling; workers load code
  at startup. Preserve user settings, torrent state, and downloaded files.
