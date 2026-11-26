#!/usr/bin/env python3
"""Install a per-user GNOME/Linux application entry. Does not need administrator access."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def desktop_value(value: str) -> str:
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')


def exec_argument(value: str) -> str:
    # Desktop Entry command quoting, not shell quoting. Percent starts field codes.
    escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    return desktop_value('"' + escaped.replace('%', '%%') + '"')


def desktop_entry(root: Path) -> str:
    executable = exec_argument(str(root / 'CodeDebunker'))
    return '\n'.join([
        '[Desktop Entry]', 'Version=1.0', 'Type=Application', 'Name=CodeDebunker',
        'Comment=Explore code structure, explanations, and isolated tests',
        'Exec=' + executable,
        'Icon=' + desktop_value(str(root / 'frontend/public/favicon.svg')),
        'Terminal=false', 'StartupNotify=false', 'Categories=Development;IDE;',
        'Keywords=Code;Python;JavaScript;TypeScript;UML;', 'Actions=Stop;', '',
        '[Desktop Action Stop]', 'Name=Stop CodeDebunker', 'Exec=' + executable + ' --stop', '',
    ])


def destinations(*, project_only: bool) -> list[Path]:
    result = [ROOT / 'CodeDebunker.desktop']
    if not project_only:
        data_home = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))).expanduser()
        if not data_home.is_absolute():
            raise ValueError('XDG_DATA_HOME must be an absolute path.')
        # A Snap/Flatpak IDE may export its private data directory. GNOME's host
        # Applications menu does not scan those application-private directories.
        if any(data_home.is_relative_to(path) for path in (Path.home() / 'snap', Path.home() / '.var/app')):
            data_home = Path.home() / '.local/share'
        result.append(data_home / 'applications/codedebunker.desktop')
    return result


def install(*, project_only: bool = False) -> list[Path]:
    files = destinations(project_only=project_only)
    contents = desktop_entry(ROOT)
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        path.chmod(0o755)
        if shutil.which('gio'):
            # Some file managers use this metadata for a double-clickable project shortcut.
            subprocess.run(['gio', 'set', str(path), 'metadata::trusted', 'true'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if not project_only and shutil.which('update-desktop-database'):
        subprocess.run(['update-desktop-database', str(files[-1].parent)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description='Add CodeDebunker to your Applications menu.')
    parser.add_argument('--project-only', action='store_true', help='Only create the shortcut in this project')
    parser.add_argument('--dry-run', action='store_true', help='Show the paths and entry without installing')
    args = parser.parse_args()
    if args.dry_run:
        print('\n'.join(str(path) for path in destinations(project_only=args.project_only)))
        print('\n' + desktop_entry(ROOT))
        return
    for path in install(project_only=args.project_only):
        print(f'Installed: {path}')
    print('Open CodeDebunker from the Applications menu. No terminal is needed.')


if __name__ == '__main__':
    main()
