"""PyInstaller entry point. Kept outside the package so the frozen app starts through the normal import path."""

from autofill_agent.__main__ import main

if __name__ == "__main__":
    main()
