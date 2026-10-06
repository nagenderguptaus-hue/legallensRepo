"""Adapter loading: maps the ``LL_ORCHESTRATOR`` / ``LL_INGESTION`` settings to objects.

``"standin"`` selects the built-in rule-based stand-ins. Any other value is an import path
``"package.module:factory"``; the factory is called with the ``Settings`` and returns the
adapter. That is how the AI layer (Phase 3) plugs in without code changes here (NFR-7).
"""

import importlib
from typing import cast

from legallens.config import Settings
from legallens.ports.ingestion import IngestionPipeline
from legallens.ports.orchestrator import ChatOrchestrator


def _load_factory(spec: str) -> object:
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError(f"Adapter must be 'standin' or 'package.module:factory', got {spec!r}")
    return getattr(importlib.import_module(module_name), attr)


def load_orchestrator(settings: Settings) -> ChatOrchestrator:
    if settings.orchestrator == "standin":
        from legallens.adapters.standin.rule_based_orchestrator import RuleBasedOrchestrator

        return RuleBasedOrchestrator(settings)
    factory = _load_factory(settings.orchestrator)
    return cast(ChatOrchestrator, factory(settings))  # type: ignore[operator]


def load_ingestion_pipeline(settings: Settings) -> IngestionPipeline:
    if settings.ingestion == "standin":
        from legallens.adapters.standin.basic_ingestion import BasicIngestionPipeline

        return BasicIngestionPipeline()
    factory = _load_factory(settings.ingestion)
    return cast(IngestionPipeline, factory(settings))  # type: ignore[operator]
