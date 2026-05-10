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

from dataclasses import dataclass
from enum import Enum


class SearchMode(str, Enum):
    content = "content"
    filename = "filename"


@dataclass
class SearchArgs:
    pattern: str
    search_mode: SearchMode = SearchMode.content
    plaintext: bool = True
    case_sensitive: bool = False
    include: str = ""
    exclude: str = ""
    location: str = "."
    recursive: bool = True
    search_office: bool = True
    search_pdf: bool = True
    filenames_only: bool = False
