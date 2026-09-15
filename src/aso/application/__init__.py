"""Camada de aplicação — serviços por caso de uso extraídos do `OrchestrationService` (ADR-0066).

A extração é incremental (MEL-32): cada passo move um grupo de responsabilidades para cá e o
`OrchestrationService` delega, sem mudar a API pública.
"""
