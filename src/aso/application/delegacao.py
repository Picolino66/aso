"""Delegação tipada da façade `OrchestrationService` aos serviços de aplicação (ADR-0066).

MEL-32: depois de extraída toda a lógica, a façade só repassava chamadas — ~230 métodos de
três a oito linhas cada, repetindo assinaturas que já existem nos serviços (e que podiam
divergir deles em silêncio). `Delegado` troca cada repasse por uma linha declarativa que
herda a assinatura do método do serviço: o mypy continua checando os chamadores (API, CLI e
testes) contra o serviço real, e mudar a assinatura no serviço muda a da façade junto.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Concatenate, overload


class Delegado[S, **P, R]:
    """Descritor: `fachada.metodo(...)` chama `fachada.<atributo>.metodo(...)`.

    É um descritor sem `__set__`: atribuir no objeto (ex.: `monkeypatch.setattr`) sobrepõe a
    delegação só naquela instância, como acontecia com o método escrito à mão.
    """

    def __init__(self, atributo: str, metodo: Callable[Concatenate[S, P], R]) -> None:
        self._atributo = atributo
        self._nome = metodo.__name__

    @overload
    def __get__(self, obj: None, owner: type[Any]) -> Delegado[S, P, R]: ...

    @overload
    def __get__(self, obj: object, owner: type[Any] | None = None) -> Callable[P, R]: ...

    def __get__(self, obj: object | None, owner: type[Any] | None = None) -> Any:
        if obj is None:
            return self
        return getattr(getattr(obj, self._atributo), self._nome)
