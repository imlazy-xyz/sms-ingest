"""Loopback-bind enforcement tests (no real sockets — pure validator)."""

from __future__ import annotations

import pytest

from reader import binding


def test_default_host_is_loopback():
    assert binding.is_loopback_host(binding.DEFAULT_HOST)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.5.6.7", "::1", "localhost", "LOCALHOST"])
def test_is_loopback_host_accepts_loopback_forms(host):
    assert binding.is_loopback_host(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "10.0.0.5", "example.com", "192.168.1.1", ""])
def test_is_loopback_host_rejects_non_loopback(host):
    assert not binding.is_loopback_host(host)


def test_enforce_loopback_passes_loopback_host():
    assert binding.enforce_loopback("127.0.0.1") == "127.0.0.1"


def test_enforce_loopback_raises_on_non_loopback_by_default():
    with pytest.raises(binding.NonLoopbackBindError):
        binding.enforce_loopback("0.0.0.0")


def test_enforce_loopback_allows_explicit_opt_out():
    assert binding.enforce_loopback("0.0.0.0", allow_non_loopback=True) == "0.0.0.0"


def test_resolve_bind_host_defaults_to_loopback():
    assert binding.resolve_bind_host() == binding.DEFAULT_HOST


def test_resolve_bind_host_rejects_non_loopback_request():
    with pytest.raises(binding.NonLoopbackBindError):
        binding.resolve_bind_host("0.0.0.0")


def test_resolve_bind_host_accepts_explicit_loopback_request():
    assert binding.resolve_bind_host("::1") == "::1"
