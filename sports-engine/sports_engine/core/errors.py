"""Engine-specific exceptions."""


class SportsEngineError(Exception):
    """Base class."""


class LeakageError(SportsEngineError):
    """Raised when information from after a cutoff reaches a pre-cutoff computation."""


class DataContractError(SportsEngineError):
    """Raised when data violates its contract and must not enter the database."""


class ProviderError(SportsEngineError):
    """A data provider failed. Callers must degrade gracefully, never crash the system."""


class ProviderNotEnabledError(ProviderError):
    """Provider is disabled or its terms have not been acknowledged."""


class DatasetNotFoundError(ProviderError):
    """The dataset does not exist upstream (e.g. HTTP 404): a coverage gap, not a failure."""


class RobotsDisallowedError(ProviderError):
    """robots.txt disallows the request. Never bypassed."""


class ImmutableRecordError(SportsEngineError):
    """Attempt to modify an immutable record (raw data, paper prediction, experiment)."""


class ForbiddenStakingError(SportsEngineError):
    """Martingale / loss-chasing style staking was requested. Always refused."""


class HoldoutAccessError(SportsEngineError):
    """Final holdout requested without explicit, logged authorisation."""
