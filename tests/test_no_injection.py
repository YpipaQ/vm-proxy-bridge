"""防回流：注入层（D1–D4 防线 / 死手开关 / 预演 / 会话确认）与自启动（systemd / autostart）已取缔。

这些是**永久**断言，不是一次性检查：任何人把注入层加回来，这里立刻红。
"""
import importlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.filterwarnings("error")

PKG_DIR = Path(__file__).resolve().parents[1] / "src" / "proxybridge"
SRC_DIR = PKG_DIR.parent
TESTS_DIR = Path(__file__).resolve().parent

#: 已删模块：既不许有文件，也不许还能 import
DELETED_MODULES = ["inject", "guard", "rehearse", "session", "desktop", "sysd"]

#: 已取缔功能的关键词（\b 词边界，避免误伤 start_new_session 这类合法 kwarg）
FORBIDDEN = re.compile(
    r"\b(xsessionrc|inject|guard|rehearse|safe_mode|systemd|autostart|linger|rescue|"
    r"D1|D2|D3|D4|managed_block)\b"
)

#: tests/ 里放宽：测试**本来就要**点名这些字样来断言"它不存在"（如 hasattr(paths,"xsessionrc")）。
#: 那边只查真正的**导入**残留 —— 那才会让测试套件假通过。
FORBIDDEN_IMPORT = re.compile(r"^\s*(?:from|import)\s+\S*\b(inject|guard|rehearse|session|desktop|sysd)\b")

#: 允许保留的**历史说明**注释（例如"曾用于…，已取缔"）；留空 = 一处都不许有
ALLOWED_HISTORICAL: list[str] = []


@pytest.mark.parametrize("name", DELETED_MODULES)
def test_deleted_module_file_is_gone(name):
    assert not (PKG_DIR / f"{name}.py").exists(), f"{name}.py 应已被删除"


@pytest.mark.parametrize("name", DELETED_MODULES)
def test_deleted_module_is_not_importable(name):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(f"proxybridge.{name}")


@pytest.mark.parametrize("name", DELETED_MODULES)
def test_no_lazy_import_of_deleted_module(name):
    """不许 `try: from . import guard except ImportError: pass` 这类兜底。"""
    hits = []
    for f in sorted(PKG_DIR.glob("*.py")):
        for i, line in enumerate(f.read_text("utf-8").splitlines(), 1):
            if re.search(rf"(?:from|import)\s+.*\b{name}\b", line):
                hits.append(f"{f.name}:{i}: {line.strip()}")
    assert not hits, "仍有对被删模块的引用：\n" + "\n".join(hits)


@pytest.mark.parametrize("root", [SRC_DIR, TESTS_DIR], ids=["src", "tests"])
def test_no_injection_or_autostart_traces(root):
    strict = Path(root) == SRC_DIR
    hits = []
    for f in sorted(Path(root).rglob("*.py")):
        if "__pycache__" in f.parts or f == Path(__file__):
            # 跳过本文件自身：它按定义就要点名这些字样（这不是回流，是防线本身）
            continue
        for i, line in enumerate(f.read_text("utf-8").splitlines(), 1):
            if strict:
                bad = FORBIDDEN.search(line) and not any(a in line for a in ALLOWED_HISTORICAL)
            else:
                bad = FORBIDDEN_IMPORT.search(line)
            if bad:
                hits.append(f"{f.relative_to(root.parent)}:{i}: {line.strip()}")
    assert not hits, "注入层/自启动的字样回流了：\n" + "\n".join(hits)


def test_deleted_verbs_are_not_registered():
    """CLI 不得再注册 session/guard/rescue/service 四组子命令。"""
    from proxybridge.cli import build_parser
    parser = build_parser()
    verbs = set()
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            verbs |= set(action.choices)
    assert not (verbs & {"session", "guard", "rescue", "service"}), f"残留动词：{sorted(verbs)}"


def test_no_state_or_manifest_injection_helpers():
    """paths / state / manifest 不得再暴露注入相关的接口。"""
    from proxybridge import manifest, paths, state
    assert not hasattr(paths, "xsessionrc")
    assert not hasattr(paths, "guard_file")
    assert "guard" not in state.DEFAULT_STATE and "generation" not in state.DEFAULT_STATE
    assert set(state.DEFAULT_STATE) == {"schema", "desired_on", "actual"}
    # 清单只登记普通文件（systemd 单元那种 kind="unit" 已废）
    assert manifest.Entry.__dataclass_fields__["kind"].default == "file"
