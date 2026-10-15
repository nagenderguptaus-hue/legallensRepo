"""Legal Lens AI layer: the intent router and the Ask / Summary / Draft workflows."""

from legallens_ai.config import AISettings
from legallens_ai.errors import (
    IntentUnparseableError,
    ModelConfigurationError,
    ModelUnavailableError,
    OrchestratorError,
)
from legallens_ai.intent_classifier import IntentClassifier
from legallens_ai.orchestrator import Orchestrator
from legallens_ai.schemas import (
    ClassifierResult,
    DocumentInfo,
    Intent,
    IntentClassification,
    OrchestratorRequest,
    RoutingDecision,
    TokenUsage,
    Turn,
)

__all__ = [
    "AISettings",
    "ClassifierResult",
    "DocumentInfo",
    "Intent",
    "IntentClassification",
    "IntentClassifier",
    "IntentUnparseableError",
    "ModelConfigurationError",
    "ModelUnavailableError",
    "Orchestrator",
    "OrchestratorError",
    "OrchestratorRequest",
    "RoutingDecision",
    "TokenUsage",
    "Turn",
]
