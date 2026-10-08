"""定义可安全映射到接口响应的应用异常。"""

from __future__ import annotations


class ApplicationError(Exception):

    public_message = "Application error"
    code = "application_error"
    retryable = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)


class ExternalProviderError(ApplicationError):
    public_message = "External provider failed"
    code = "external_provider_failed"


class FeatureUnavailableError(ApplicationError):

    public_message = "Requested feature is unavailable"
    code = "feature_unavailable"


class AgentExecutionError(ApplicationError):

    public_message = "Agent execution failed"
    code = "agent_execution_failed"


class ResourceOwnershipError(ApplicationError):

    public_message = "Resource not found"
    code = "resource_not_found"


class InputValidationError(ApplicationError):
    public_message = "Invalid input"
    code = "invalid_input"


class BusinessConstraintError(ApplicationError):
    public_message = "Business constraint violated"
    code = "business_constraint_violated"


class ResourceNotFoundError(ApplicationError):
    public_message = "Resource not found"
    code = "resource_not_found"


class ConflictError(ApplicationError):
    public_message = "Resource conflict"
    code = "resource_conflict"


class ExternalModelError(ExternalProviderError):
    public_message = "Model provider failed"
    code = "external_model_failed"


class ModelOutputValidationError(ExternalModelError):
    public_message = "Model output failed schema validation"
    code = "model_output_invalid"


class PartialStreamInterruptedError(ExternalModelError):

    public_message = "Model stream was interrupted after output started"
    code = "model_partial_stream_interrupted"


class ExternalServiceError(ExternalProviderError):
    public_message = "External service failed"
    code = "external_service_failed"


class DatabaseOperationError(ApplicationError):
    public_message = "Database operation failed"
    code = "database_operation_failed"


class DatabaseUnavailableError(DatabaseOperationError):
    public_message = "Database is temporarily unavailable"
    code = "database_unavailable"
    retryable = True


class StoredDataIntegrityError(DatabaseOperationError):
    public_message = "Stored recipe data failed validation"
    code = "stored_recipe_invalid"


class OperationTimeoutError(ApplicationError):
    public_message = "Operation timed out"
    code = "operation_timeout"
    retryable = True


class RateLimitExceededError(ApplicationError):
    public_message = "Rate limit exceeded"
    code = "rate_limit_exceeded"
    retryable = True


class AuthenticationError(ApplicationError):
    public_message = "Invalid email or password"
    code = "invalid_credentials"


class InvalidAccessTokenError(AuthenticationError):
    public_message = "Invalid or expired access token"
    code = "invalid_access_token"


class InvalidRefreshTokenError(AuthenticationError):
    public_message = "Invalid or expired refresh token"
    code = "invalid_refresh_token"


class AccountDisabledError(AuthenticationError):
    public_message = "Account is not active"
    code = "account_disabled"


class EmailAlreadyRegisteredError(ConflictError):
    public_message = "Email is already registered"
    code = "email_already_registered"
