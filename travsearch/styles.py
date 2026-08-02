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

from pathlib import Path

from jinja2 import Template

# Jinja2 stylesheet template — uses {{ }} for variables, { } is literal CSS
_STYLE_TEMPLATE = """\
QMainWindow, QWidget#root {
    background: #0f1117;
}
QWidget {
    background: #0f1117;
    color: #e2e8f0;
    font-family: 'Liberation Mono', 'DejaVu Sans Mono', monospace;
    font-size: {{ sz2 }}px;
}
QLabel#title {
    font-size: {{ sz1 }}px;
    font-weight: bold;
    color: #38bdf8;
    letter-spacing: 2px;
}
QLabel#subtitle {
    font-size: {{ sz4 }}px;
    color: #475569;
    letter-spacing: 1px;
}
QLabel#field-label {
    color: #94a3b8;
    font-size: {{ sz4 }}px;
    letter-spacing: 1px;
}
QLabel#cmd-preview {
    color: #334155;
    font-size: {{ sz4 }}px;
    font-family: 'Liberation Mono', 'DejaVu Sans Mono', monospace;
}
QLabel#status {
    color: #475569;
    font-size: {{ sz4 }}px;
}
QLineEdit {
    background: #1e2333;
    border: 1px solid #2d3748;
    border-radius: 4px;
    padding: 6px 10px;
    color: #e2e8f0;
    selection-background-color: #38bdf8;
    selection-color: #0f1117;
}
QLineEdit:focus {
    border: 1px solid #38bdf8;
}
QComboBox {
    background: #1e2333;
    border: 1px solid #2d3748;
    border-radius: 4px;
    padding: 6px 10px;
    color: #e2e8f0;
    min-width: 120px;
}
QComboBox:focus { border: 1px solid #38bdf8; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 24px;
    border-left: 1px solid #2d3748;
}
QComboBox::down-arrow {
    image: url({{ arrow_path }});
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    background: #1e2333;
    border: 1px solid #38bdf8;
    selection-background-color: #38bdf8;
    selection-color: #0f1117;
}
QCheckBox {
    color: #94a3b8;
    spacing: 6px;
    font-size: {{ sz3 }}px;
}
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #2d3748;
    border-radius: 3px;
    background: #1e2333;
}
QCheckBox::indicator:checked {
    background: #38bdf8;
    border-color: #38bdf8;
}
QPushButton#run-btn {
    background: #38bdf8;
    color: #0f1117;
    border: none;
    border-radius: 4px;
    padding: 8px 24px;
    font-weight: bold;
    font-size: {{ sz2 }}px;
    letter-spacing: 1px;
}
QPushButton#run-btn:hover { background: #7dd3fc; }
QPushButton#run-btn:pressed { background: #0ea5e9; }
QPushButton#run-btn:disabled { background: #2d3748; color: #475569; }
QPushButton#browse-btn {
    background: #1e2333;
    color: #38bdf8;
    border: 1px solid #38bdf8;
    border-radius: 4px;
    padding: 6px 12px;
    font-size: {{ sz3 }}px;
}
QPushButton#browse-btn:hover { background: #38bdf8; color: #0f1117; }
QPushButton#clear-btn {
    background: transparent;
    color: #475569;
    border: 1px solid #2d3748;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: {{ sz3 }}px;
}
QPushButton#clear-btn:hover { color: #94a3b8; border-color: #475569; }
QPushButton#stop-btn {
    background: transparent;
    color: #f87171;
    border: 1px solid #f87171;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: {{ sz3 }}px;
}
QPushButton#stop-btn:hover { background: #f87171; color: #0f1117; }
QPushButton#stop-btn:disabled { color: #2d3748; border-color: #2d3748; background: transparent; }
QPushButton#clear-field-btn {
    background: transparent;
    color: #475569;
    border: 1px solid #2d3748;
    border-radius: 4px;
    padding: 0px;
    font-size: {{ sz2 }}px;
    font-weight: bold;
}
QPushButton#clear-field-btn:hover { color: #f87171; border-color: #f87171; }
QPushButton#reset-btn {
    background: transparent;
    color: #475569;
    border: 1px solid #2d3748;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: {{ sz4 }}px;
}
QPushButton#reset-btn:hover { color: #fbbf24; border-color: #fbbf24; }
QTextEdit#output {
    background: #080b10;
    border: 1px solid #1e2333;
    border-radius: 4px;
    color: #a3e635;
    font-family: 'Liberation Mono', 'DejaVu Sans Mono', monospace;
    font-size: {{ sz3 }}px;
    padding: 8px;
}
QFrame#divider {
    background: #1e2333;
    max-height: 1px;
}
QLabel#progress-label {
    color: #475569;
    font-size: {{ sz4 }}px;
    font-family: 'Liberation Mono', 'DejaVu Sans Mono', monospace;
}
QProgressBar {
    background: #1e2333;
    border: 1px solid #2d3748;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: #38bdf8;
    border-radius: 3px;
}
QSlider#font-slider::groove:horizontal {
    height: 3px;
    background: #2d3748;
    border-radius: 2px;
}
QSlider#font-slider::handle:horizontal {
    background: #38bdf8;
    border: none;
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider#font-slider::sub-page:horizontal {
    background: #38bdf8;
    border-radius: 2px;
}
"""

# Base font sizes (at slider value 0)
_BASE_SIZES = {"sz1": 22, "sz2": 13, "sz3": 12, "sz4": 11}

# Path to arrow image
_ARROW_PATH = Path(__file__).parent / "arrow_down.svg"


def render_style(slider_value: int) -> str:
    """Render the stylesheet with the given font size offset."""
    sizes = {k: v + slider_value for k, v in _BASE_SIZES.items()}
    return Template(_STYLE_TEMPLATE).render(**sizes, arrow_path=_ARROW_PATH.as_posix())
