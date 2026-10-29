# SPDX-FileCopyrightText: TravSearch | Copyright (c) 2026 Travis L. Seymour, PhD <nogard@ucsc.edu>
# SPDX-License-Identifier: GPL-3.0-or-later

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

from .extractors import (
    BINARY_SUFFIXES,
    OFFICE_SUFFIXES,
    PDF_SUFFIXES,
    extract_office_text,
    extract_pdf_text,
)
from .models import SearchArgs

_RG_OUTPUT_RE = re.compile(r"^(.+?):(\d+):")
_STAT_FILES_SEARCHED = re.compile(r"(\d+) files searched")
_STAT_FILES_MATCHED = re.compile(r"(\d+) files contained matches")


def _build_rg_cmd(args: SearchArgs) -> list[str]:
    """Build a single rg command for directory-wide text search."""
    rg = shutil.which("rg")
    if rg is None:
        raise FileNotFoundError("'rg' not found — install ripgrep: sudo apt install ripgrep")
    cmd = [
        rg,
        "--no-heading",
        "--with-filename",
        "--line-number",
        "--color=never",
        "--stats",
        "--hidden",
        "--no-ignore",
    ]
    if args.plaintext:
        cmd.append("--fixed-strings")
    if not args.case_sensitive:
        cmd.append("--ignore-case")
    if not args.recursive:
        cmd += ["--max-depth", "1"]

    # Include patterns (comma-separated); default to searching everything
    include_patterns = [p.strip() for p in args.include.split(",") if p.strip()]
    for pattern in include_patterns:
        cmd += ["--glob", pattern]

    # Exclude patterns (comma-separated)
    for pattern in (p.strip() for p in args.exclude.split(",") if p.strip()):
        cmd += ["--glob", f"!{pattern}"]

    # Exclude extractable formats (they are searched separately via text extraction)
    for suffix in OFFICE_SUFFIXES:
        cmd += ["--glob", f"!*{suffix}"]
    for suffix in PDF_SUFFIXES:
        cmd += ["--glob", f"!*{suffix}"]

    cmd += [args.pattern, args.location]
    return cmd


def _run_rg_phase(
    args: SearchArgs,
    on_progress: Callable[[int, int, str], None],
    on_match: Callable[[str, str, str], None],
    on_error: Callable[[str], None],
    stop_event: threading.Event,
) -> tuple[int, int]:
    """Run a single rg process on the search directory. Returns (matched_files, total_searched)."""
    try:
        cmd = _build_rg_cmd(args)
    except FileNotFoundError as e:
        on_error(f"ERROR: {e}")
        return 0, 0

    on_progress(0, 0, "searching text files…")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    matched_files: set[str] = set()
    tail_lines: list[str] = []  # collect non-match lines (stats may appear on stdout)
    try:
        for raw_line in proc.stdout:
            if stop_event.is_set():
                proc.terminate()
                proc.wait()
                return len(matched_files), 0
            line = raw_line.rstrip("\n")
            if not line:
                continue
            # rg output: filepath:linenum:content — only emit actual matches
            m = _RG_OUTPUT_RE.match(line)
            if m:
                fp = m.group(1)
                matched_files.add(fp)
                on_match(fp, line, line)
            else:
                tail_lines.append(line)
        proc.wait()
    except OSError as e:
        proc.terminate()
        proc.wait()
        on_error(f"rg error: {e}")
        return len(matched_files), 0

    # Parse stats — rg may write them to stderr or stdout depending on version
    stderr = proc.stderr.read() if proc.stderr else ""
    stats_text = stderr + "\n" + "\n".join(tail_lines)
    total_searched = 0
    total_matched = len(matched_files)
    m = _STAT_FILES_SEARCHED.search(stats_text)
    if m:
        total_searched = int(m.group(1))
    m = _STAT_FILES_MATCHED.search(stats_text)
    if m:
        total_matched = int(m.group(1))

    if proc.returncode > 1:
        # rg returns 1 for no match, 2+ for errors
        on_error(f"rg error (exit {proc.returncode}): {stderr.strip()}")

    return total_matched, total_searched


def _run_extractable_phase(
    files: list[Path],
    args: SearchArgs,
    on_progress: Callable[[int, int, str], None],
    on_match: Callable[[str, str, str], None],
    on_error: Callable[[str], None],
    stop_event: threading.Event,
    num_workers: int = 8,
) -> tuple[int, int]:
    """Search office/PDF files using extraction + thread pool. Returns (matched_files, total)."""
    total = len(files)
    if total == 0:
        return 0, 0

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
            except (OSError, RuntimeError) as e:
                on_error(str(e))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    return len(matched), total


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
    except OSError as e:
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
                check=False,
            )
            for line in proc.stdout.splitlines():
                if stop_event.is_set():
                    break
                display = line.replace(tf_path, label, 1)
                on_match(label, display, line)
            if proc.returncode > 1:
                on_error(f"{label}: rg error: {proc.stderr.strip()}")
        except OSError as e:
            on_error(f"{label}: {e}")
        finally:
            if tf_path:
                try:
                    Path(tf_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def run_rg_direct(p: Path) -> None:
        try:
            proc = subprocess.run(
                rg_cmd + [args.pattern, str(p)],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in proc.stdout.splitlines():
                if stop_event.is_set():
                    break
                on_match(str(p), line, line)
            if proc.returncode > 1:
                on_error(f"{p}: rg error: {proc.stderr.strip()}")
        except OSError as e:
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
    num_workers: int = 8,
) -> None:
    """
    Two-phase content search:
      Phase 1 — single rg invocation for text files (fast).
      Phase 2 — thread-pool extraction + rg for office/PDF files.
    All callbacks are invoked from worker threads — callers must be thread-safe.
    """
    # Phase 1: single rg for text files
    rg_matched, rg_total = _run_rg_phase(args, on_progress, on_match, on_error, stop_event)

    if stop_event.is_set():
        on_done(rg_matched, rg_total)
        return

    # Phase 2: extractable files (office/PDF)
    ext_matched = 0
    ext_total = 0
    if args.search_office or args.search_pdf:
        on_progress(0, 0, "scanning office/PDF files…")
        try:
            all_files = enumerate_files(args, on_error, stop_event)
        except FileNotFoundError as e:
            on_error(f"ERROR: {e}")
            on_done(rg_matched, rg_total)
            return

        if stop_event.is_set():
            on_done(rg_matched, rg_total)
            return

        target_suffixes = set()
        if args.search_office:
            target_suffixes |= set(OFFICE_SUFFIXES.keys())
        if args.search_pdf:
            target_suffixes |= PDF_SUFFIXES
        extractable = [f for f in all_files if f.suffix.lower() in target_suffixes]

        if extractable and not stop_event.is_set():
            ext_matched, ext_total = _run_extractable_phase(
                extractable, args, on_progress, on_match, on_error, stop_event, num_workers
            )

    on_done(rg_matched + ext_matched, rg_total + ext_total)


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
