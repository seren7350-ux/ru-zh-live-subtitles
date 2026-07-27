"""Minimal PyInstaller entry point; keep freeze support before project imports."""

import multiprocessing


def main() -> int:
    from live_subtitles.frozen_entry import main as frozen_main

    return frozen_main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
