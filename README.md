# TravSearch

A GUI application for searching filenames or file content using `fd` and `rg` (ripgrep).

[![TravSearch UI](travsearch/travsearch_ui.png)](travsearch/travsearch_ui.png)

---

## Features

- **Content search**: Search inside files using ripgrep
- **Filename search**: Find files by name using fd
- **Office document support**: Search inside `.docx`, `.odt`, `.xlsx`, `.ods`, `.pptx` files
- **PDF support**: Search inside PDF files (requires `pdftotext`)
- **Glob filtering**: Filter files by pattern (e.g., `*.docx`)
- **Regex support**: Toggle between plain text and regex matching
- **Settings persistence**: Remembers your last search settings and window position

## System Dependencies

TravSearch wraps multiple command-line tools. Install them before running:

### 1. `fd` — fast filename search

```bash
sudo apt install fd-find
```

> On Debian/Ubuntu the binary is called `fdfind`. You may want to alias it:
>
> ```bash
> echo 'alias fd=fdfind' >> ~/.bashrc && source ~/.bashrc
> ```

### 2. `rg` — ripgrep (fast content search)

```bash
sudo apt install ripgrep
```

### 3. `pdftotext` — PDF text extraction (optional, for searching PDFs)

```bash
sudo apt install poppler-utils
```

> Office documents (`.docx`, `.odt`, `.xlsx`, `.pptx`) are searched by extracting
> their embedded XML directly — no extra tools required for those.

## Installation

```bash
# Clone the repository
git clone https://github.com/travisseymour/travsearch.git
cd travsearch

# Install with uv
uv sync

# Or install with pip
pip install -e .
```

## Usage

Run the application:

```bash
travsearch
```

Or run directly with Python:

```bash
python -m travsearch.main
```

## Development

Install with dev dependencies:

```bash
uv sync --group dev
```

Format code with ruff:

```bash
uv run ruff format travsearch/
uv run ruff check travsearch/
```

## License

MIT
