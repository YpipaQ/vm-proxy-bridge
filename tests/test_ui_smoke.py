"""GUI 冒烟：能建窗口、能刷新状态；无 CustomTkinter 时降级到 tkinter。"""
import pytest

tk = pytest.importorskip("tkinter")

from proxybridge import ctl, ui  # noqa: E402


def _display_ok() -> bool:
    try:
        r = tk.Tk(); r.withdraw(); r.destroy(); return True
    except Exception:                                     # noqa: BLE001
        return False


requires_display = pytest.mark.skipif(not _display_ok(), reason="无可用 X 显示")


@requires_display
def test_window_builds_and_refreshes(tmp_path, monkeypatch):
    h = tmp_path / "home"; h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    root, app = ui.build_window()
    try:
        root.update_idletasks()
        app.refresh()
        root.update_idletasks()
        header = str(app.header.cget("text"))
        assert "转发器" in header and "系统代理" in header and "配置" in header
    finally:
        root.destroy()


@requires_display
def test_queue_serialises_and_ignores_clicks_while_busy(tmp_path, monkeypatch):
    h = tmp_path / "home"; h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    root, app = ui.build_window()
    try:
        app.busy = True
        app.enqueue("support_bundle")
        assert app.queue == [], "忙时点击必须被忽略，不能堆队列"
    finally:
        root.destroy()


@requires_display
def test_gui_never_writes_files(tmp_path, monkeypatch):
    """GUI 只读契约：建窗口 + 刷新不得在 HOME 里产生任何文件。"""
    from pathlib import Path
    h = tmp_path / "home"; h.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(h))
    before = sorted(str(p) for p in Path(h).rglob("*"))
    root, app = ui.build_window()
    try:
        app.refresh()
        root.update_idletasks()
    finally:
        root.destroy()
    assert sorted(str(p) for p in Path(h).rglob("*")) == before


def test_fallback_flag_matches_import():
    assert isinstance(ui._HAS_CTK, bool)
    if not ui._HAS_CTK:
        assert ui.ctk is None, "导入失败时必须把 ctk 置 None，不能留半残对象"
