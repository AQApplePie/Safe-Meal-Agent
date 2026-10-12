"""定义可安全映射到接口响应的应用异常。"""

from __future__ import annotations


# 类说明（异常类）：ApplicationError
# 作用：表示应用异常基类，供上层识别并映射错误响应。
class ApplicationError(Exception):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Application error'。
    public_message = "Application error"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'application_error'。
    code = "application_error"
    # 字段说明：retryable
    # 作用：当前失败是否允许重试。
    # 初始值：False。
    retryable = False

    # 方法说明：__init__
    # 作用：初始化应用异常基类，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   message（str | None）：本轮用户消息或问题文本；默认值为 None。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)


# 类说明（异常类）：ExternalProviderError
# 作用：表示外部菜谱来源异常，供上层识别并映射错误响应。
class ExternalProviderError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'External provider failed'。
    public_message = "External provider failed"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'external_provider_failed'。
    code = "external_provider_failed"


# 类说明（异常类）：FeatureUnavailableError
# 作用：表示功能不可用异常，供上层识别并映射错误响应。
class FeatureUnavailableError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Requested feature is unavailable'。
    public_message = "Requested feature is unavailable"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'feature_unavailable'。
    code = "feature_unavailable"


# 类说明（异常类）：AgentExecutionError
# 作用：表示Agent 执行异常，供上层识别并映射错误响应。
class AgentExecutionError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Agent execution failed'。
    public_message = "Agent execution failed"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'agent_execution_failed'。
    code = "agent_execution_failed"


# 类说明（异常类）：ResourceOwnershipError
# 作用：表示资源归属校验异常，供上层识别并映射错误响应。
class ResourceOwnershipError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Resource not found'。
    public_message = "Resource not found"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'resource_not_found'。
    code = "resource_not_found"


# 类说明（异常类）：InputValidationError
# 作用：表示输入校验异常，供上层识别并映射错误响应。
class InputValidationError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Invalid input'。
    public_message = "Invalid input"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'invalid_input'。
    code = "invalid_input"


# 类说明（异常类）：BusinessConstraintError
# 作用：表示业务约束异常，供上层识别并映射错误响应。
class BusinessConstraintError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Business constraint violated'。
    public_message = "Business constraint violated"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'business_constraint_violated'。
    code = "business_constraint_violated"


# 类说明（异常类）：ResourceNotFoundError
# 作用：表示资源不存在异常，供上层识别并映射错误响应。
class ResourceNotFoundError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Resource not found'。
    public_message = "Resource not found"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'resource_not_found'。
    code = "resource_not_found"


# 类说明（异常类）：ConflictError
# 作用：表示资源状态冲突异常，供上层识别并映射错误响应。
class ConflictError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Resource conflict'。
    public_message = "Resource conflict"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'resource_conflict'。
    code = "resource_conflict"


# 类说明（异常类）：ExternalModelError
# 作用：表示外部模型调用异常，供上层识别并映射错误响应。
class ExternalModelError(ExternalProviderError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Model provider failed'。
    public_message = "Model provider failed"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'external_model_failed'。
    code = "external_model_failed"


# 类说明（异常类）：ModelOutputValidationError
# 作用：表示模型输出校验异常，供上层识别并映射错误响应。
class ModelOutputValidationError(ExternalModelError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Model output failed schema validation'。
    public_message = "Model output failed schema validation"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'model_output_invalid'。
    code = "model_output_invalid"


# 类说明（异常类）：PartialStreamInterruptedError
# 作用：表示答案流中断异常，供上层识别并映射错误响应。
class PartialStreamInterruptedError(ExternalModelError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Model stream was interrupted after output started'。
    public_message = "Model stream was interrupted after output started"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'model_partial_stream_interrupted'。
    code = "model_partial_stream_interrupted"


# 类说明（异常类）：ExternalServiceError
# 作用：表示外部服务异常，供上层识别并映射错误响应。
class ExternalServiceError(ExternalProviderError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'External service failed'。
    public_message = "External service failed"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'external_service_failed'。
    code = "external_service_failed"


# 类说明（异常类）：DatabaseOperationError
# 作用：表示数据库操作异常，供上层识别并映射错误响应。
class DatabaseOperationError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Database operation failed'。
    public_message = "Database operation failed"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'database_operation_failed'。
    code = "database_operation_failed"


# 类说明（异常类）：DatabaseUnavailableError
# 作用：表示数据库不可用异常，供上层识别并映射错误响应。
class DatabaseUnavailableError(DatabaseOperationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Database is temporarily unavailable'。
    public_message = "Database is temporarily unavailable"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'database_unavailable'。
    code = "database_unavailable"
    # 字段说明：retryable
    # 作用：当前失败是否允许重试。
    # 初始值：True。
    retryable = True


# 类说明（异常类）：StoredDataIntegrityError
# 作用：表示持久数据完整性异常，供上层识别并映射错误响应。
class StoredDataIntegrityError(DatabaseOperationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Stored recipe data failed validation'。
    public_message = "Stored recipe data failed validation"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'stored_recipe_invalid'。
    code = "stored_recipe_invalid"


# 类说明（异常类）：OperationTimeoutError
# 作用：表示操作超时异常，供上层识别并映射错误响应。
class OperationTimeoutError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Operation timed out'。
    public_message = "Operation timed out"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'operation_timeout'。
    code = "operation_timeout"
    # 字段说明：retryable
    # 作用：当前失败是否允许重试。
    # 初始值：True。
    retryable = True


# 类说明（异常类）：RateLimitExceededError
# 作用：表示请求限流异常，供上层识别并映射错误响应。
class RateLimitExceededError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Rate limit exceeded'。
    public_message = "Rate limit exceeded"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'rate_limit_exceeded'。
    code = "rate_limit_exceeded"
    # 字段说明：retryable
    # 作用：当前失败是否允许重试。
    # 初始值：True。
    retryable = True


# 类说明（异常类）：AuthenticationError
# 作用：表示身份认证异常，供上层识别并映射错误响应。
class AuthenticationError(ApplicationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Invalid email or password'。
    public_message = "Invalid email or password"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'invalid_credentials'。
    code = "invalid_credentials"


# 类说明（异常类）：InvalidAccessTokenError
# 作用：表示访问令牌无效异常，供上层识别并映射错误响应。
class InvalidAccessTokenError(AuthenticationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Invalid or expired access token'。
    public_message = "Invalid or expired access token"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'invalid_access_token'。
    code = "invalid_access_token"


# 类说明（异常类）：InvalidRefreshTokenError
# 作用：表示刷新令牌无效异常，供上层识别并映射错误响应。
class InvalidRefreshTokenError(AuthenticationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Invalid or expired refresh token'。
    public_message = "Invalid or expired refresh token"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'invalid_refresh_token'。
    code = "invalid_refresh_token"


# 类说明（异常类）：AccountDisabledError
# 作用：表示账户禁用异常，供上层识别并映射错误响应。
class AccountDisabledError(AuthenticationError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Account is not active'。
    public_message = "Account is not active"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'account_disabled'。
    code = "account_disabled"


# 类说明（异常类）：EmailAlreadyRegisteredError
# 作用：表示邮箱已注册异常，供上层识别并映射错误响应。
class EmailAlreadyRegisteredError(ConflictError):
    # 字段说明：public_message
    # 作用：允许返回给用户的错误说明，避免泄露内部诊断信息。
    # 初始值：'Email is already registered'。
    public_message = "Email is already registered"
    # 字段说明：code
    # 作用：MessagePack 扩展类型标识。
    # 初始值：'email_already_registered'。
    code = "email_already_registered"
