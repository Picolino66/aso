"""Tracing OpenTelemetry opcional (§33).

Ativado com `ASO_OTEL=1` (requer o extra `[otel]` instalado). Caso contrário — ou se
o OTel não estiver disponível — retorna um tracer no-op, sem custo e sem dependência
obrigatória. Exporta spans para o console (ConsoleSpanExporter) por padrão.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol, cast


class _Span(Protocol):
    def set_attribute(self, key: str, value: Any) -> None: ...


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        return None


class Tracer(Protocol):
    def start_as_current_span(self, name: str) -> Any: ...


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, name: str) -> Iterator[_NoopSpan]:
        yield _NoopSpan()


def get_tracer() -> Tracer:
    if os.environ.get("ASO_OTEL") != "1":
        return _NoopTracer()
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        trace.set_tracer_provider(provider)
        return cast(Tracer, trace.get_tracer("aso"))
    except Exception:
        return _NoopTracer()
