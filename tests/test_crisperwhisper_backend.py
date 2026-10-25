"""
Regression Test Suite for CrisperWhisper 2.0 Large ASR Backend Integration.
Guarantees zero regressions in engine registry, priority auto-detection, and API client.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

import pytest
from services import asr_backend as ab


def test_crisperwhisper_in_registry():
    assert "crisper-whisper" in ab._REGISTRY
    assert ab._REGISTRY["crisper-whisper"] is ab.CrisperWhisperBackend
    assert ab.CrisperWhisperBackend.id == "crisper-whisper"
    assert "CrisperWhisper" in ab.CrisperWhisperBackend.display_name


def test_crisperwhisper_gpu_compat():
    assert "cuda" in ab.CrisperWhisperBackend.gpu_compat
    assert "cpu" in ab.CrisperWhisperBackend.gpu_compat


def test_crisperwhisper_is_available_true():
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        avail, status = ab.CrisperWhisperBackend.is_available()
        assert avail is True
        assert status == "ready"


def test_crisperwhisper_is_available_false_on_error():
    with patch("requests.get") as mock_get:
        mock_get.side_effect = Exception("Connection refused")
        avail, status = ab.CrisperWhisperBackend.is_available()
        assert avail is False
        assert "unavailable" in status


def test_auto_detect_prioritizes_crisperwhisper(monkeypatch):
    monkeypatch.delenv("OMNIVOICE_ASR_BACKEND", raising=False)
    with patch.object(ab, "_probe_available") as mock_probe:
        def probe_side_effect(cls):
            if cls is ab.CrisperWhisperBackend:
                return True
            return False
        mock_probe.side_effect = probe_side_effect
        detected = ab._auto_detect()
        assert detected == "crisper-whisper"


def test_get_active_asr_backend_instantiates_crisperwhisper():
    with patch.object(ab, "active_backend_id", return_value="crisper-whisper"):
        backend = ab.get_active_asr_backend()
        assert isinstance(backend, ab.CrisperWhisperBackend)
        assert backend.id == "crisper-whisper"


def test_crisperwhisper_transcribe_payload():
    backend = ab.CrisperWhisperBackend()
    with patch("requests.post") as mock_post, patch("builtins.open", unittest.mock.mock_open(read_data=b"fake-audio-bytes")):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"text": "Hello world from CrisperWhisper", "language": "en"}
        mock_post.return_value = mock_resp

        result = backend.transcribe("/tmp/test_audio.wav")
        assert result["text"] == "Hello world from CrisperWhisper"
        assert result["language"] == "en"
        assert len(result["chunks"]) >= 1
