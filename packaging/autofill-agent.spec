# PyInstaller spec for the standalone agent (one folder, not one file: it starts faster and trips fewer
# antivirus heuristics). Build with:  pyinstaller packaging/autofill-agent.spec --noconfirm
# Run from the repository root, with the backend installed in the same environment.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is provided by PyInstaller)
backend = root / "backend"

hidden = collect_submodules("autofill_agent") + collect_submodules("uvicorn") + [
    "sqlalchemy.dialects.sqlite",
    "multipart",
    "python_multipart",
]

a = Analysis(  # noqa: F821
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(backend)],
    datas=[(str(backend / "autofill_agent" / "ui"), "autofill_agent/ui")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="autofill-agent",
    console=True,  # keep the console: it shows the data path and is how you stop the agent
)
coll = COLLECT(exe, a.binaries, a.datas, name="autofill-agent")  # noqa: F821
