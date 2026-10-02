"""支持 `python -m proxybridge ...`（与 console_script `proxy` 等价）。"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
