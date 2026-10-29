# SPDX-FileCopyrightText: TravSearch | Copyright (c) 2026 Travis L. Seymour, PhD <nogard@ucsc.edu>
# SPDX-License-Identifier: GPL-3.0-or-later

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
