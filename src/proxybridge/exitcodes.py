"""统一退出码语义（DESIGN-v2 §7）。不得在本模块之外硬编码数字。"""
from __future__ import annotations

OK = 0
FAIL = 1
DOCTOR_FAILED = 2        # 体检有 warn 或 fail
USAGE = 4
