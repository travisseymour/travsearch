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

import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from .extractors import (
    BINARY_SUFFIXES,
    OFFICE_SUFFIXES,
    PDF_SUFFIXES,
    extract_office_text,
    extract_pdf_text,
)
from .models import SearchArgs


def enumerate_files(
    args: SearchArgs,
    on_error: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> list[Path]:
    """Use fd to build the full file list. Returns list of Paths."""
    fd = shutil.which("fd") or shutil.which("fdfind")
    if fd is None:
        raise FileNotFoundError("'fd'/'fdfind' not found.\n  Install: sudo apt install fd-find")

    cmd = [fd, "--type", "f", "--no-ignore", "--hidden"]
    if not args.recursive:
        cmd += ["--max-depth", "1"]

    # Include patterns (comma-separated); default to * if blank
    include_patterns = [p.strip() for p in args.include.split(",") if p.strip()]
    if not include_patterns:
        include_patterns = ["*"]
    for pattern in include_patterns:
        cmd += ["--glob", pattern]

    # Exclude patterns (comma-separated)
    for pattern in (p.strip() for p in args.exclude.split(",") if p.strip()):
        cmd += ["--exclude", pattern]

    # Exclude file types that won't be searched
    if not args.search_pdf:
        for suffix in PDF_SUFFIXES:
            cmd += ["--exclude", f"*{suffix}"]
    if not args.search_office:
        for suffix in OFFICE_SUFFIXES:
            cmd += ["--exclude", f"*{suffix}"]

    # Always exclude known binary files
    for suffix in BINARY_SUFFIXES:
        cmd += ["--exclude", f"*{suffix}"]

    cmd.append(args.location)

    # Use Popen to allow interruption via stop_event
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    paths: list[Path] = []
    try:
        for line in proc.stdout:
            if stop_event is not None and stop_event.is_set():
                proc.terminate()
                proc.wait()
                return paths
            if line.strip():
                paths.append(Path(line.strip()))
        proc.wait()
        if proc.returncode not in (0, 1) and on_error:
            stderr = proc.stderr.read() if proc.stderr else ""
            on_error(f"fd error (exit {proc.returncode}): {stderr.strip()}")
        if proc.stderr:
            stderr = proc.stderr.read()
            if stderr.strip() and on_error:
                on_error(f"fd warning: {stderr.strip()}")
    except Exception as e:
        proc.terminate()
        proc.wait()
        if on_error:
            on_error(f"fd error: {e}")
    return paths


def search_file(
    path: Path,
    args: SearchArgs,
    file_num: int,
    total: int,
    on_progress: Callable[[int, int, str], None],
    on_match: Callable[[str, str, str], None],
    on_error: Callable[[str], None],
    stop_event: threading.Event,
) -> None:
    """Search a single file. Calls callbacks; never raises."""
    if stop_event.is_set():
        return

    on_progress(file_num, total, str(path))

    suffix = path.suffix.lower()
    rg = shutil.which("rg")
    if rg is None:
        on_error("'rg' not found — install ripgrep: sudo apt install ripgrep")
        return

    rg_cmd = [rg, "--no-heading", "--with-filename", "--line-number", "--color=never"]
    if args.plaintext:
        rg_cmd.append("--fixed-strings")
    if not args.case_sensitive:
        rg_cmd.append("--ignore-case")

    def run_rg_on_text(text: str, label: str) -> None:
        tf_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tf:
                tf.write(text)
                tf_path = tf.name
            proc = subprocess.run(
                rg_cmd + [args.pattern, tf_path],
                capture_output=True,
                text=True,
            )
            for line in proc.stdout.splitlines():
                if stop_event.is_set():
                    break
                display = line.replace(tf_path, label, 1)
                on_match(label, display, line)
            if proc.returncode > 1:
                on_error(f"{label}: rg error: {proc.stderr.strip()}")
        except Exception as e:
            on_error(f"{label}: {e}")
        finally:
            if tf_path:
                try:
                    Path(tf_path).unlink(missing_ok=True)
                except Exception:
                    pass

    def run_rg_direct(p: Path) -> None:
        try:
            proc = subprocess.run(
                rg_cmd + [args.pattern, str(p)],
                capture_output=True,
                text=True,
            )
            for line in proc.stdout.splitlines():
                if stop_event.is_set():
                    break
                on_match(str(p), line, line)
            if proc.returncode > 1:
                on_error(f"{p}: rg error: {proc.stderr.strip()}")
        except Exception as e:
            on_error(f"{p}: {e}")

    if suffix in OFFICE_SUFFIXES:
        if args.search_office:
            text = extract_office_text(path)
            if text is not None:
                run_rg_on_text(text, str(path))
    elif suffix in PDF_SUFFIXES:
        if args.search_pdf:
            text = extract_pdf_text(path)
            if text is not None:
                run_rg_on_text(text, str(path))
    else:
        run_rg_direct(path)


def run_search(
    args: SearchArgs,
    on_progress: Callable[[int, int, str], None],
    on_match: Callable[[str, str, str], None],
    on_error: Callable[[str], None],
    on_done: Callable[[int, int], None],
    stop_event: threading.Event,
    num_workers: int = 16,
) -> None:
    """
    Enumerate files with fd, then search each in a thread pool.
    All callbacks are invoked from worker threads — callers must be thread-safe.
    """
    try:
        files = enumerate_files(args, on_error, stop_event)
    except FileNotFoundError as e:
        on_error(f"ERROR: {e}")
        on_done(0, 0)
        return

    # Check if stop was requested during enumeration
    if stop_event.is_set():
        on_done(0, len(files))
        return

    total = len(files)
    if total == 0:
        on_error("fd found 0 files to search — check your location and glob settings")
        on_done(0, 0)
        return
    matched: set[str] = set()
    matched_lock = threading.Lock()

    def worker(item: tuple[int, Path]) -> None:
        file_num, path = item
        if stop_event.is_set():
            return

        def _on_match(fp: str, line: str, raw: str) -> None:
            with matched_lock:
                matched.add(fp)
            on_match(fp, line, raw)

        search_file(path, args, file_num, total, on_progress, _on_match, on_error, stop_event)

    pool = ThreadPoolExecutor(max_workers=num_workers)
    try:
        futs = [pool.submit(worker, (i + 1, p)) for i, p in enumerate(files)]

        for fut in as_completed(futs):
            if stop_event.is_set():
                break
            try:
                fut.result()
            except Exception as e:
                on_error(str(e))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    on_done(len(matched), total)


def build_filename_cmd(args: SearchArgs) -> list[str]:
    """Build the fd command for filename search mode."""
    fd = shutil.which("fd") or shutil.which("fdfind")
    if fd is None:
        raise FileNotFoundError("'fd'/'fdfind' not found.\n  Install: sudo apt install fd-find")
    cmd = [fd, "--type", "f", "--no-ignore", "--hidden"]
    if args.plaintext:
        cmd.append("--fixed-strings")
    if args.case_sensitive:
        cmd.append("--case-sensitive")
    else:
        cmd.append("--ignore-case")
    if not args.recursive:
        cmd += ["--max-depth", "1"]

    # Exclude patterns (comma-separated)
    for pattern in (p.strip() for p in args.exclude.split(",") if p.strip()):
        cmd += ["--exclude", pattern]

    # In filename mode, the search pattern itself filters filenames,
    # so include patterns are not needed (and --glob was being misused)
    cmd += [args.pattern, args.location]
    return cmd
