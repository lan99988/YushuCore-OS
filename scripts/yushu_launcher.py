"""PyInstaller entry point for the Windows portable application."""

from yushu_app.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
