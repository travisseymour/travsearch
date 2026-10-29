# SPDX-FileCopyrightText: TravSearch | Copyright (c) 2026 Travis L. Seymour, PhD <nogard@ucsc.edu>
# SPDX-License-Identifier: GPL-3.0-or-later

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
