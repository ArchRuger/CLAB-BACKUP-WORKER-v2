"""Entry point of the full-screen installer, run by bootstrap.launch() with the private
environment's Python in isolated mode (-I). Exits 75 if it cannot start; nothing has
been changed at that point, so install-manager.py may offer the plain menu instead."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import textual  # noqa: F401  (the pinned package from the private environment)
    from installer_tui.app import main
except Exception as error:  # missing or broken packages: report, change nothing
    sys.stderr.write(f'The full-screen installer cannot start ({type(error).__name__}: {error}).\n'
                     'Repair it with:  bash deploy/install.sh --setup-tui\n')
    sys.exit(75)

sys.exit(main(sys.argv[1:]))
