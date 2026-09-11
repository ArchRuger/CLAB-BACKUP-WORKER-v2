"""Development entry point. setup-discovery installs the shared stdlib helper."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'clab-backup-ui'))
from app.host_files import main

if __name__ == '__main__':
    raise SystemExit(main())
