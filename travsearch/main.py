"""
TravSearch: GUI to Search filenames or file content using fd and rg utilities.
Copyright (C) 2026  Travis L. Seymour, PhD

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import os
from pathlib import Path

from .gui import run_gui

os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db=false")


def main() -> None:
    """Entry point for the travsearch application."""
    # Capture current working directory before Qt changes it
    cwd = str(Path.cwd())
    run_gui(initial_location=cwd)


if __name__ == "__main__":
    main()
