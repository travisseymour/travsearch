from .gui import run_gui
import os

os.environ.setdefault("QT_LOGGING_RULES", "qt.text.font.db=false")


def main() -> None:
    """Entry point for the travsearch application."""
    run_gui()


if __name__ == "__main__":
    main()
