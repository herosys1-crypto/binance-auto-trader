"""어느 폴더에서 pytest 를 돌려도 orchestra · examples 를 찾게."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
