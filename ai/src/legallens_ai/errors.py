"""Errors the orchestrator raises. Same shape as the backend's ``OrchestratorError`` (a stable
``code`` plus a message the user can act on), so the backend can map them one to one."""


class OrchestratorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ModelUnavailableError(OrchestratorError):
    """Network failure, timeout, rate limit or server error. Retrying later may work."""

    def __init__(self, message: str = "The AI model is not responding. Try again shortly.") -> None:
        super().__init__("model_unavailable", message)


class ModelConfigurationError(OrchestratorError):
    """Missing or rejected credentials, unknown model id, invalid request. Retrying won't help."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


class ModelRefusedError(OrchestratorError):
    """The model declined the request (``stop_reason == "refusal"``), even after fallbacks."""

    def __init__(
        self, message: str = "The AI model declined this request. Try rephrasing it."
    ) -> None:
        super().__init__("model_refused", message)


class IntentUnparseableError(OrchestratorError):
    """The model answered, but not with a usable intent (refusal, truncation, bad output)."""

    def __init__(
        self, message: str = "The intent of this message could not be determined. Try again."
    ) -> None:
        super().__init__("intent_unparseable", message)


class RewriteUnparseableError(OrchestratorError):
    """The query rewriter answered, but not with a usable result."""

    def __init__(
        self, message: str = "The question could not be prepared for search. Try again."
    ) -> None:
        super().__init__("rewrite_unparseable", message)


class RetrievalUnavailableError(OrchestratorError):
    """The vector store, keyword index, embedding model or reranker failed."""

    def __init__(
        self, message: str = "Document search is not available right now. Try again shortly."
    ) -> None:
        super().__init__("retrieval_unavailable", message)


class DocumentNotIndexedError(OrchestratorError):
    def __init__(
        self,
        message: str = "This document has not been indexed yet. Wait until it is Ready, "
        "or upload it again.",
    ) -> None:
        super().__init__("document_not_indexed", message)


class DocumentTooLargeError(OrchestratorError):
    def __init__(self, message: str) -> None:
        super().__init__("document_too_large", message)
