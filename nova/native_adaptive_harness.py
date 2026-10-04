"""Guarded adapter for Omnigent's native Codex harness registry entry."""
from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    from nova.native_adaptive_runtime import install_codex_guardrails

    host = __import__("os").environ.get("NOVA_ADAPTIVE_CODEX_HOST_PATH")
    if not host:
        raise RuntimeError("native adaptive Codex host binary binding is missing")
    install_codex_guardrails(host)
    from omnigent.inner.codex_harness import create_app as create_native_codex_app

    return create_native_codex_app()
