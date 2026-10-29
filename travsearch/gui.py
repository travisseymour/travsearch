# SPDX-FileCopyrightText: TravSearch | Copyright (c) 2026 Travis L. Seymour, PhD <nogard@ucsc.edu>
# SPDX-License-Identifier: GPL-3.0-or-later

from importlib.metadata import version
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QScreen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .models import SearchArgs, SearchMode
from .search import build_filename_cmd, run_search
from .styles import render_style

SETTINGS_ORG = "travsearch"
SETTINGS_APP = "travsearch"

# Regex to parse rg output: filepath:linenum:content or just filepath
_RG_LINE_RE = re.compile(r"^(.+?):(\d+):")


_FILEPATH_ROLE = Qt.UserRole + 1
_LINENUM_ROLE = Qt.UserRole + 2
_CONTENT_ROLE = Qt.UserRole + 3


class ResultDelegate(QStyledItemDelegate):
    """Draws each result row: filepath in blue, then match content in gray."""

    def paint(self, painter, option, index):
        painter.save()
        # Draw selection/hover background
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter, option.widget)

        filepath = index.data(_FILEPATH_ROLE) or ""
        content = index.data(_CONTENT_ROLE) or ""

        rect = option.rect.adjusted(6, 2, -6, -2)
        fm = painter.fontMetrics()

        # Draw filepath in blue
        painter.setPen(QColor("#38bdf8"))
        if content:
            fp_display = filepath + " "
        else:
            fp_display = filepath
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, fp_display)

        # Draw content in dark gray after filepath
        if content:
            fp_width = fm.horizontalAdvance(fp_display)
            content_rect = rect.adjusted(fp_width, 0, 0, 0)
            painter.setPen(QColor("#64748b"))
            elided = fm.elidedText(content, Qt.ElideRight, content_rect.width())
            painter.drawText(content_rect, Qt.AlignLeft | Qt.AlignVCenter, elided)

        painter.restore()

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        hint.setHeight(max(hint.height(), option.fontMetrics.height() + 6))
        return hint


class ResultList(QListWidget):
    """QListWidget that opens files on double-click and has a context menu."""

    def __init__(self, parent: "SearchWindow"):
        super().__init__(parent)
        self._search_window = parent
        self.setItemDelegate(ResultDelegate(self))
        self.itemDoubleClicked.connect(self._on_double_click)

    def _on_double_click(self, item: QListWidgetItem):
        if not self._search_window.run_btn.isEnabled():
            return
        filepath = item.data(_FILEPATH_ROLE)
        linenum = item.data(_LINENUM_ROLE)
        if filepath and Path(filepath).exists():
            self._open_file(filepath, linenum)

    def _open_file(self, filepath: str, linenum: int | None) -> None:
        code = shutil.which("code")
        if code:
            if linenum:
                subprocess.Popen([code, "--goto", f"{filepath}:{linenum}"])
            else:
                subprocess.Popen([code, filepath])
            return
        xdg = shutil.which("xdg-open")
        if xdg:
            subprocess.Popen([xdg, filepath])

    def _open_folder(self, filepath: str) -> None:
        folder = str(Path(filepath).parent)
        xdg = shutil.which("xdg-open")
        if xdg:
            subprocess.Popen([xdg, folder])

    def contextMenuEvent(self, event) -> None:
        if not self._search_window.run_btn.isEnabled():
            super().contextMenuEvent(event)
            return
        item = self.itemAt(event.pos())
        if not item:
            super().contextMenuEvent(event)
            return
        filepath = item.data(_FILEPATH_ROLE)
        linenum = item.data(_LINENUM_ROLE)
        if not filepath or not Path(filepath).exists():
            super().contextMenuEvent(event)
            return

        menu = QMenu(self)
        if linenum:
            open_action = menu.addAction(f"Open file at line {linenum}")
        else:
            open_action = menu.addAction("Open file")
        folder_action = menu.addAction("Open containing folder")
        copy_action = menu.addAction("Copy path")
        menu.addSeparator()
        menu.addAction("Cancel")

        action = menu.exec(event.globalPos())
        if action == open_action:
            self._open_file(filepath, linenum)
        elif action == folder_action:
            self._open_folder(filepath)
        elif action == copy_action:
            QApplication.clipboard().setText(filepath)


class SearchWorker(QObject):
    """Worker that runs the search pipeline in a QThread."""

    progress = Signal(int, int, str)  # file_num, total, path
    match = Signal(str, str)  # filepath, display_line
    finished = Signal(int, int)  # matched_files, total_files

    def __init__(self, args: SearchArgs):
        super().__init__()
        self._args = args
        self._stop = threading.Event()

    def run(self):
        def on_progress(n, total, path):
            self.progress.emit(n, total, path)

        def on_match(fp, line, raw):
            self.match.emit(fp, line)

        def on_error(msg):
            self.match.emit("", f"ERROR: {msg}")

        def on_done(matched, total):
            self.finished.emit(matched, total)

        run_search(
            self._args,
            on_progress,
            on_match,
            on_error,
            on_done,
            self._stop,
            num_workers=16,
        )

    def stop(self):
        self._stop.set()


class FdWorker(QObject):
    """Worker for filename search mode using fd directly."""

    output = Signal(str)
    error = Signal(str)
    finished = Signal(int, int)

    def __init__(self, cmd: list[str]):
        super().__init__()
        self.cmd = cmd
        self._running = True

    def run(self):
        try:
            proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for line in proc.stdout:
                if not self._running:
                    proc.terminate()
                    break
                self.output.emit(line.rstrip())
            proc.wait()
            self.finished.emit(0, 0)
        except OSError as e:
            self.error.emit(str(e))
            self.finished.emit(0, 0)

    def stop(self):
        self._running = False


class SearchWindow(QMainWindow):
    """Main application window."""

    def __init__(self, initial_location: str | None = None):
        super().__init__()
        self.setWindowTitle(f"TravSearch! (v{version('travsearch')})")
        self.setMinimumSize(1024, 768)
        self._worker = None
        self._thread = None
        self._seen_files: set[str] = set()
        self._last_progress_time: float = 0.0
        self._match_buffer: list[tuple[str, str]] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_matches)
        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._build_ui()
        self._restore_settings()
        # Override location with command-line working directory if provided
        if initial_location:
            self.location_edit.setEditText(initial_location)
        self._apply_font_size(self.font_slider.value())

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(0)

        # Header row: title/subtitle left, slider right
        header_row = QHBoxLayout()
        header_row.setSpacing(0)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("TravSearch")
        title.setObjectName("title")
        sub = QLabel("Linux Search Using One or More of these tools: [fd · rg · rga]")
        sub.setObjectName("subtitle")
        title_col.addWidget(title)
        title_col.addWidget(sub)

        header_row.addLayout(title_col)
        header_row.addStretch()

        self.reset_btn = QPushButton("reset")
        self.reset_btn.setObjectName("reset-btn")
        self.reset_btn.setFixedWidth(90)
        self.reset_btn.setToolTip("Reset all fields to defaults")
        self.reset_btn.clicked.connect(self._reset_all)
        header_row.addWidget(self.reset_btn, alignment=Qt.AlignBottom)
        header_row.addSpacing(10)

        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setObjectName("font-slider")
        self.font_slider.setRange(0, 12)
        self.font_slider.setValue(4)
        self.font_slider.setFixedWidth(100)
        self.font_slider.setToolTip("Font size")
        header_row.addWidget(self.font_slider, alignment=Qt.AlignBottom)

        outer.addLayout(header_row)
        outer.addSpacing(20)

        # Form grid
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(1, 1)

        def field_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setObjectName("field-label")
            return lbl

        row = 0

        # Pattern (editable combo with history)
        grid.addWidget(field_label("PATTERN"), row, 0, Qt.AlignTop)
        pattern_row = QHBoxLayout()
        pattern_row.setSpacing(6)
        self.pattern_edit = QComboBox()
        self.pattern_edit.setEditable(True)
        self.pattern_edit.setInsertPolicy(QComboBox.NoInsert)
        self.pattern_edit.lineEdit().setPlaceholderText("text or regex to search for…")
        pattern_row.addWidget(self.pattern_edit)
        self.pattern_clear_btn = QPushButton("×")
        self.pattern_clear_btn.setObjectName("clear-field-btn")
        self.pattern_clear_btn.setFixedWidth(28)
        self.pattern_clear_btn.setToolTip("Clear pattern")
        self.pattern_clear_btn.clicked.connect(lambda: self.pattern_edit.setEditText(""))
        pattern_row.addWidget(self.pattern_clear_btn)
        grid.addLayout(pattern_row, row, 1, 1, 2)
        row += 1

        # Location (editable combo with history)
        grid.addWidget(field_label("LOCATION"), row, 0, Qt.AlignTop)
        loc_row = QHBoxLayout()
        loc_row.setSpacing(6)
        self.location_edit = QComboBox()
        self.location_edit.setEditable(True)
        self.location_edit.setInsertPolicy(QComboBox.NoInsert)
        loc_row.addWidget(self.location_edit)
        browse_btn = QPushButton("browse")
        browse_btn.setObjectName("browse-btn")
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._browse)
        loc_row.addWidget(browse_btn)
        self.location_clear_btn = QPushButton("×")
        self.location_clear_btn.setObjectName("clear-field-btn")
        self.location_clear_btn.setFixedWidth(28)
        self.location_clear_btn.setToolTip("Clear location (reset to home)")
        self.location_clear_btn.clicked.connect(lambda: self.location_edit.setEditText(str(Path.home())))
        loc_row.addWidget(self.location_clear_btn)
        grid.addLayout(loc_row, row, 1, 1, 2)
        row += 1

        # Include (editable combo with history)
        grid.addWidget(field_label("INCLUDE"), row, 0, Qt.AlignTop)
        include_row = QHBoxLayout()
        include_row.setSpacing(6)
        self.include_edit = QComboBox()
        self.include_edit.setEditable(True)
        self.include_edit.setInsertPolicy(QComboBox.NoInsert)
        self.include_edit.lineEdit().setPlaceholderText("e.g. *.py, *.txt  (blank = *)")
        include_row.addWidget(self.include_edit)
        self.include_clear_btn = QPushButton("×")
        self.include_clear_btn.setObjectName("clear-field-btn")
        self.include_clear_btn.setFixedWidth(28)
        self.include_clear_btn.setToolTip("Clear include")
        self.include_clear_btn.clicked.connect(lambda: self.include_edit.setEditText(""))
        include_row.addWidget(self.include_clear_btn)
        grid.addLayout(include_row, row, 1, 1, 2)
        row += 1

        # Exclude (editable combo with history)
        grid.addWidget(field_label("EXCLUDE"), row, 0, Qt.AlignTop)
        exclude_row = QHBoxLayout()
        exclude_row.setSpacing(6)
        self.exclude_edit = QComboBox()
        self.exclude_edit.setEditable(True)
        self.exclude_edit.setInsertPolicy(QComboBox.NoInsert)
        self.exclude_edit.lineEdit().setPlaceholderText("e.g. *.log, node_modules  (blank = exclude nothing)")
        exclude_row.addWidget(self.exclude_edit)
        self.exclude_clear_btn = QPushButton("×")
        self.exclude_clear_btn.setObjectName("clear-field-btn")
        self.exclude_clear_btn.setFixedWidth(28)
        self.exclude_clear_btn.setToolTip("Clear exclude")
        self.exclude_clear_btn.clicked.connect(lambda: self.exclude_edit.setEditText(""))
        exclude_row.addWidget(self.exclude_clear_btn)
        grid.addLayout(exclude_row, row, 1, 1, 2)
        row += 1

        # Mode
        grid.addWidget(field_label("MODE"), row, 0, Qt.AlignTop)
        mode_row = QHBoxLayout()
        mode_row.setSpacing(16)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["content", "filename"])
        mode_row.addWidget(self.mode_combo)
        self.regex_chk = QCheckBox("regex")
        self.regex_chk.setChecked(False)
        mode_row.addWidget(self.regex_chk)
        self.case_sensitive_chk = QCheckBox("case sensitive")
        self.case_sensitive_chk.setChecked(False)
        mode_row.addWidget(self.case_sensitive_chk)
        mode_row.addStretch()
        grid.addLayout(mode_row, row, 1, 1, 2)
        row += 1

        # Options
        grid.addWidget(field_label("OPTIONS"), row, 0, Qt.AlignTop)
        opts_row = QHBoxLayout()
        opts_row.setSpacing(20)
        self.recursive_chk = QCheckBox("recursive")
        self.office_chk = QCheckBox("office docs")
        self.pdf_chk = QCheckBox("PDFs")
        self.recursive_chk.setChecked(True)
        self.office_chk.setChecked(True)
        self.pdf_chk.setChecked(True)
        for chk in (self.recursive_chk, self.office_chk, self.pdf_chk):
            opts_row.addWidget(chk)
        opts_row.addSpacing(16)
        self.content_radio = QRadioButton("show filenames && match text")
        self.filenames_radio = QRadioButton("show filenames")
        self.content_radio.setChecked(True)
        opts_row.addWidget(self.content_radio)
        opts_row.addWidget(self.filenames_radio)
        opts_row.addStretch()
        grid.addLayout(opts_row, row, 1, 1, 2)
        row += 1

        outer.addLayout(grid)
        outer.addSpacing(16)

        # Command preview (selectable for copying)
        self.cmd_label = QLabel()
        self.cmd_label.setObjectName("cmd-preview")
        self.cmd_label.setWordWrap(True)
        self.cmd_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.cmd_label.setCursor(Qt.IBeamCursor)
        outer.addWidget(self.cmd_label)
        outer.addSpacing(8)

        # Progress bar + file counter
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        outer.addWidget(self.progress_bar)
        outer.addSpacing(4)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("progress-label")
        outer.addWidget(self.progress_label)
        outer.addSpacing(8)

        # Buttons
        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("▶  RUN")
        self.run_btn.setObjectName("run-btn")
        self.run_btn.setFixedHeight(38)
        self.stop_btn = QPushButton("■  STOP")
        self.stop_btn.setObjectName("stop-btn")
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.setEnabled(False)
        self.clear_btn = QPushButton("clear")
        self.clear_btn.setObjectName("clear-btn")
        self.clear_btn.setFixedHeight(38)
        btn_row.addWidget(self.run_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(self.stop_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)
        outer.addSpacing(14)

        # Divider
        div = QFrame()
        div.setObjectName("divider")
        div.setFrameShape(QFrame.HLine)
        outer.addWidget(div)
        outer.addSpacing(10)

        # Output (clickable list - double-click opens file)
        self.result_list = ResultList(self)
        self.result_list.setObjectName("result-list")
        outer.addWidget(self.result_list, stretch=1)

        # Status
        outer.addSpacing(6)
        self.status_label = QLabel("ready")
        self.status_label.setObjectName("status")
        outer.addWidget(self.status_label)

        # Connections
        self.run_btn.clicked.connect(self._run)
        self.stop_btn.clicked.connect(self._stop)
        self.clear_btn.clicked.connect(self._clear)
        self.font_slider.valueChanged.connect(self._apply_font_size)
        for widget in (self.pattern_edit, self.location_edit, self.include_edit, self.exclude_edit):
            widget.editTextChanged.connect(self._update_preview)
        for widget in (
            self.mode_combo,
            self.regex_chk,
            self.case_sensitive_chk,
            self.recursive_chk,
            self.office_chk,
            self.pdf_chk,
            self.filenames_radio,
            self.content_radio,
        ):
            if hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(self._update_preview)
            elif hasattr(widget, "toggled"):
                widget.toggled.connect(self._update_preview)
            else:
                widget.stateChanged.connect(self._update_preview)

        self._update_preview()

    def _restore_settings(self):
        s = self._settings
        self.font_slider.setValue(int(s.value("font_size", 4)))

        # Restore combo box histories and current values
        for combo, history_key, value_key, default in [
            (self.pattern_edit, "pattern_history", "pattern", ""),
            (self.location_edit, "location_history", "location", "."),
            (self.include_edit, "include_history", "include", ""),
            (self.exclude_edit, "exclude_history", "exclude", ""),
        ]:
            history = s.value(history_key, [])
            if isinstance(history, list):
                combo.addItems(history)
            combo.setEditText(s.value(value_key, default))

        idx = self.mode_combo.findText(s.value("mode", "content"))
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.regex_chk.setChecked(not s.value("plaintext", True, type=bool))
        self.case_sensitive_chk.setChecked(s.value("case_sensitive", False, type=bool))
        self.recursive_chk.setChecked(s.value("recursive", True, type=bool))
        self.office_chk.setChecked(s.value("search_office", True, type=bool))
        self.pdf_chk.setChecked(s.value("search_pdf", True, type=bool))
        if s.value("filenames_only", False, type=bool):
            self.filenames_radio.setChecked(True)
        else:
            self.content_radio.setChecked(True)
        geometry = s.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1024, 768)
            screen_geo = QScreen.availableGeometry(QApplication.primaryScreen())
            x = screen_geo.x() + (screen_geo.width() - self.width()) // 2
            y = screen_geo.y() + (screen_geo.height() - self.height()) // 2
            self.move(x, y)

    def _save_settings(self):
        s = self._settings
        s.setValue("font_size", self.font_slider.value())

        # Save combo box histories and current values
        for combo, history_key, value_key in [
            (self.pattern_edit, "pattern_history", "pattern"),
            (self.location_edit, "location_history", "location"),
            (self.include_edit, "include_history", "include"),
            (self.exclude_edit, "exclude_history", "exclude"),
        ]:
            history = [combo.itemText(i) for i in range(combo.count())]
            s.setValue(history_key, history)
            s.setValue(value_key, combo.currentText())

        s.setValue("mode", self.mode_combo.currentText())
        s.setValue("plaintext", not self.regex_chk.isChecked())
        s.setValue("case_sensitive", self.case_sensitive_chk.isChecked())
        s.setValue("recursive", self.recursive_chk.isChecked())
        s.setValue("search_office", self.office_chk.isChecked())
        s.setValue("search_pdf", self.pdf_chk.isChecked())
        s.setValue("filenames_only", self.filenames_radio.isChecked())
        s.setValue("window_geometry", self.saveGeometry())

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    def _add_to_history(self, combo: QComboBox, value: str, max_items: int = 20) -> None:
        """Add value to combo history, moving it to top if duplicate, limiting to max_items."""
        if not value.strip():
            return
        # Remove existing occurrence if present
        idx = combo.findText(value)
        if idx >= 0:
            combo.removeItem(idx)
        # Insert at top
        combo.insertItem(0, value)
        # Remove excess items
        while combo.count() > max_items:
            combo.removeItem(combo.count() - 1)
        # Keep the current text
        combo.setEditText(value)

    def _save_histories(self) -> None:
        """Save current field values to their histories (called on RUN)."""
        self._add_to_history(self.pattern_edit, self.pattern_edit.currentText())
        self._add_to_history(self.location_edit, self.location_edit.currentText())
        self._add_to_history(self.include_edit, self.include_edit.currentText())
        self._add_to_history(self.exclude_edit, self.exclude_edit.currentText())

    def _apply_font_size(self, value: int):
        self.setStyleSheet(render_style(value))

    def _current_args(self) -> SearchArgs:
        return SearchArgs(
            pattern=self.pattern_edit.currentText(),
            search_mode=SearchMode(self.mode_combo.currentText()),
            plaintext=not self.regex_chk.isChecked(),
            case_sensitive=self.case_sensitive_chk.isChecked(),
            include=self.include_edit.currentText(),
            exclude=self.exclude_edit.currentText(),
            location=self.location_edit.lineEdit().text().strip() or ".",
            recursive=self.recursive_chk.isChecked(),
            search_office=self.office_chk.isChecked(),
            search_pdf=self.pdf_chk.isChecked(),
            filenames_only=self.filenames_radio.isChecked(),
        )

    def _update_preview(self, *_):
        args = self._current_args()
        if args.search_mode == SearchMode.filename:
            try:
                cmd = build_filename_cmd(args)
                self.cmd_label.setText("$ " + " ".join(cmd))
            except (FileNotFoundError, ValueError):
                self.cmd_label.setText("")
        else:
            fd = shutil.which("fd") or shutil.which("fdfind") or "fd"
            rg = shutil.which("rg") or "rg"
            include_part = f' --glob "{args.include}"' if args.include.strip() else ""
            exclude_part = f' --exclude "{args.exclude}"' if args.exclude.strip() else ""
            self.cmd_label.setText(
                f"$ {fd} --type f{include_part}{exclude_part} {args.location} | "
                f"{rg} {'--fixed-strings ' if args.plaintext else ''}[pattern] <file>"
            )

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder", self.location_edit.currentText() or ".")
        if folder:
            self.location_edit.setEditText(folder)

    def _clear(self):
        self.result_list.clear()
        self._seen_files.clear()
        self._match_buffer.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0, 1)
        self.progress_label.setText("")
        self.status_label.setText("ready")

    def _reset_all(self):
        """Reset all fields to their default values."""
        self.pattern_edit.setEditText("")
        self.location_edit.setEditText(str(Path.home()))
        self.include_edit.setEditText("")
        self.exclude_edit.setEditText("")
        idx = self.mode_combo.findText("filename")
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.regex_chk.setChecked(False)
        self.case_sensitive_chk.setChecked(False)
        self.recursive_chk.setChecked(True)
        self.office_chk.setChecked(False)
        self.pdf_chk.setChecked(False)
        self.filenames_radio.setChecked(True)

    def _stop(self):
        if self._worker:
            self._worker.stop()
            # Force-kill any subprocess the worker thread may be blocking on
            if self._thread and self._thread.isRunning():
                self._thread.requestInterruption()
        self.stop_btn.setEnabled(False)
        self.status_label.setText("stopped")

    def _run(self):
        if self._worker:
            self._worker.stop()

        pattern = self.pattern_edit.currentText().strip()
        if not pattern:
            self._append_error("No pattern entered.")
            return

        # Save current values to history
        self._save_histories()

        args = self._current_args()

        # Filename mode: simple fd subprocess
        if args.search_mode == SearchMode.filename:
            try:
                cmd = build_filename_cmd(args)
            except FileNotFoundError as e:
                self._append_error(str(e))
                return
            self.result_list.clear()
            self._seen_files.clear()
            self._match_buffer.clear()
            self.status_label.setText("searching…")
            self.run_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.progress_bar.setRange(0, 0)
            self._flush_timer.start()

            self._thread = QThread()
            self._worker = FdWorker(cmd)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.output.connect(self._append_output)
            self._worker.error.connect(self._append_error)
            self._worker.finished.connect(self._on_finished)
            self._worker.finished.connect(self._thread.quit)
            self._thread.start()
            return

        # Content mode: full pipeline with progress
        self.result_list.clear()
        self._seen_files.clear()
        self._match_buffer.clear()
        self._last_progress_time = 0.0
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_label.setText("enumerating files…")
        self.status_label.setText("searching…")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._flush_timer.start()

        self._thread = QThread()
        self._worker = SearchWorker(args)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.match.connect(self._on_match)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, n: int, total: int, path: str):
        # Throttle UI updates to every 50ms to keep UI responsive
        now = time.time()
        if n < total and (now - self._last_progress_time) < 0.05:
            return
        self._last_progress_time = now

        if self.progress_bar.maximum() != total:
            self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(n)
        short = path if len(path) <= 80 else "…" + path[-79:]
        self.progress_label.setText(f"[{n}/{total}]  {short}")

    def _on_match(self, fp: str, line: str):
        self._match_buffer.append((fp, line))

    def _flush_matches(self):
        if not self._match_buffer:
            return
        batch = self._match_buffer[:200]
        self._match_buffer = self._match_buffer[200:]
        show_filenames = self.filenames_radio.isChecked()
        for fp, line in batch:
            if show_filenames:
                if fp and fp not in self._seen_files:
                    self._seen_files.add(fp)
                    self._add_result_item(fp, "")
            else:
                self._add_result_item(fp, line)

    def _add_result_item(self, fp: str, line: str):
        """Add a result to the list widget. Parses filepath:linenum:content from line."""
        filepath = fp
        linenum = None
        content = ""
        if line:
            m = _RG_LINE_RE.match(line)
            if m:
                filepath = m.group(1)
                linenum = int(m.group(2))
                content = line[m.end() :]
            else:
                content = line
        item = QListWidgetItem()
        item.setData(_FILEPATH_ROLE, filepath)
        item.setData(_LINENUM_ROLE, linenum)
        item.setData(_CONTENT_ROLE, content)
        # Set display text for accessibility / search
        item.setText(f"{filepath} {content}" if content else filepath)
        self.result_list.addItem(item)
        self.result_list.scrollToBottom()

    def _append_output(self, line: str):
        self._add_result_item(line, "")

    def _append_error(self, line: str):
        item = QListWidgetItem()
        item.setData(_FILEPATH_ROLE, "")
        item.setData(_LINENUM_ROLE, None)
        item.setData(_CONTENT_ROLE, line)
        item.setForeground(QColor("#f87171"))
        self.result_list.addItem(item)

    def _on_finished(self, matched: int, total: int):
        self._flush_timer.stop()
        # Flush any remaining buffered matches
        while self._match_buffer:
            self._flush_matches()
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(total)
            self.progress_label.setText(f"[{total}/{total}]  done")
            summary = f"{matched} match(es) found across {total} file(s) searched"
            self.status_label.setText(summary)
        else:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            self.progress_label.setText("")
            self.status_label.setText("done")
        self._worker = None


def run_gui(initial_location: str | None = None) -> None:
    """Launch the GUI application."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Set application icon (shows in dock/taskbar)
    icon_path = Path(__file__).parent / "resources" / "icons" / "Icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    win = SearchWindow(initial_location=initial_location)
    win.show()
    sys.exit(app.exec())
