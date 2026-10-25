"""Cold-start trims in the OmniVoice sidecar: skip imports synthesis never uses
(~1.5 s of the omnivoice import) and read the installed weights while the
imports run, so a cold disk is not read serially afterwards."""
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from engines.omnivoice_subprocess import main as sidecar  # noqa: E402


def test_unused_heavy_imports_are_blocked_then_restored(monkeypatch):
    for name in ("sklearn", "torchvision"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    with sidecar._skip_unused_heavy_imports():
        assert sys.modules["sklearn"] is None and sys.modules["torchvision"] is None
        try:
            import sklearn  # noqa: F401
        except ImportError:
            pass
        else:
            raise AssertionError("sklearn imported while blocked")
    assert "sklearn" not in sys.modules and "torchvision" not in sys.modules


def test_an_already_imported_module_is_left_alone(monkeypatch):
    marker = object()
    monkeypatch.setitem(sys.modules, "sklearn", marker)
    monkeypatch.delitem(sys.modules, "torchvision", raising=False)
    with sidecar._skip_unused_heavy_imports():
        assert sys.modules["sklearn"] is marker
    assert sys.modules["sklearn"] is marker


def test_blocked_modules_are_restored_when_the_import_fails(monkeypatch):
    monkeypatch.delitem(sys.modules, "sklearn", raising=False)
    monkeypatch.delitem(sys.modules, "torchvision", raising=False)
    try:
        with sidecar._skip_unused_heavy_imports():
            raise RuntimeError("import failed")
    except RuntimeError:
        pass
    assert "sklearn" not in sys.modules and "torchvision" not in sys.modules


def test_prefetch_reads_every_safetensors_file_and_nothing_else(tmp_path, monkeypatch):
    opened = []
    real_open = open

    def tracking_open(path, *args, **kwargs):
        opened.append(os.path.basename(str(path)))
        return real_open(path, *args, **kwargs)

    (tmp_path / "audio_tokenizer").mkdir()
    for rel in ("model.safetensors", "audio_tokenizer/model.safetensors", "config.json"):
        (tmp_path / rel).write_bytes(b"x" * 16)
    monkeypatch.setattr("builtins.open", tracking_open)
    sidecar._prefetch_weights(str(tmp_path), threading.Event())
    assert sorted(opened) == ["model.safetensors", "model.safetensors"]


def test_prefetch_stops_when_the_real_load_starts(tmp_path):
    (tmp_path / "model.safetensors").write_bytes(b"x" * (24 * 1024 * 1024))
    stop = threading.Event()
    stop.set()
    sidecar._prefetch_weights(str(tmp_path), stop)  # returns without reading it all


def test_prefetch_never_raises_for_a_missing_checkpoint(tmp_path):
    sidecar._prefetch_weights(str(tmp_path / "does-not-exist"), threading.Event())
    sidecar._prefetch_weights("not-an-installed/repo-id", threading.Event())
