# 이 파일은 OpenAI, Gemini, Claude, mock provider에서 발생할 수 있는 오류를 backend 내부의 공통 오류로 정리
class ProviderError(Exception):
    """AI provider adapter에서 발생하는 내부 공통 오류입니다."""

    error_code = "provider_error"


class ProviderConfigError(ProviderError):
    """provider 실행에 필요한 서버 설정이 누락되었거나 잘못된 경우입니다."""

    error_code = "provider_config_error"


class ProviderAuthError(ProviderError):
    """provider 인증에 실패한 경우입니다."""

    error_code = "provider_auth_error"


class ProviderRateLimitError(ProviderError):
    """provider rate limit에 걸린 경우입니다."""

    error_code = "provider_rate_limit_error"


class ProviderTimeoutError(ProviderError):
    """provider 요청이 timeout된 경우입니다."""

    error_code = "provider_timeout_error"


class ProviderUnavailableError(ProviderError):
    """provider가 일시적으로 사용할 수 없는 경우입니다."""

    error_code = "provider_unavailable_error"


class ProviderCapabilityError(ProviderError):
    """선택한 provider가 요청한 기능을 지원하지 않는 경우입니다."""

    error_code = "provider_capability_error"


class ProviderResponseError(ProviderError):
    """provider 응답을 내부 공통 형식으로 변환하지 못한 경우입니다."""

    error_code = "provider_response_error"