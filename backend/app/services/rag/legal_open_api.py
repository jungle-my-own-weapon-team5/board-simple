"""국가법령정보 Open API 검색 client입니다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from xml.etree import ElementTree

import httpx2 as httpx

LawOpenApiTarget = Literal["statute", "case", "interpretation", "admin_appeal"]
DEFAULT_LAW_OPEN_API_BASE_URL = "https://www.law.go.kr/DRF/lawSearch.do"
TARGET_TO_EXTERNAL_TARGET: dict[LawOpenApiTarget, str] = {
    "statute": "law",
    "case": "prec",
    "interpretation": "expc",
    "admin_appeal": "decc",
}
EXTERNAL_TARGET_TO_LIST_KEYS: dict[str, tuple[str, ...]] = {
    "law": ("law", "Law"),
    "prec": ("prec", "Prec"),
    "expc": ("expc", "Expc", "molegCgmExpc"),
    "decc": ("decc", "Decc"),
}


class LawOpenApiError(Exception):
    """외부 법률 API 오류의 base class입니다."""


class LawOpenApiConfigError(LawOpenApiError):
    """LAW_OPEN_API_OC 등 필수 설정이 없을 때 사용합니다."""


class LawOpenApiTimeoutError(LawOpenApiError):
    """외부 API timeout을 내부 오류로 정규화합니다."""


class LawOpenApiUnavailableError(LawOpenApiError):
    """외부 API 연결 실패 또는 5xx 오류입니다."""


class LawOpenApiAuthError(LawOpenApiError):
    """외부 API 인증 실패입니다."""


class LawOpenApiRateLimitError(LawOpenApiError):
    """외부 API rate limit 오류입니다."""


class LawOpenApiResponseError(LawOpenApiError):
    """외부 API 응답 구조를 해석할 수 없을 때 사용합니다."""


@dataclass(frozen=True)
class LawOpenApiSearchItem:
    external_id: str | None
    title: str
    source_url: str | None
    summary: str | None
    target: LawOpenApiTarget
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LawOpenApiSearchResult:
    query: str
    target: LawOpenApiTarget
    external_target: str
    page: int
    limit: int
    total_count: int | None
    items: list[LawOpenApiSearchItem]


class LawOpenApiClient:
    """국가법령정보 공동활용 `lawSearch.do` 목록 검색 client입니다."""

    def __init__(
        self,
        *,
        oc: str,
        base_url: str = DEFAULT_LAW_OPEN_API_BASE_URL,
        timeout_seconds: int = 30,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.oc = oc
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def search(
        self,
        *,
        query: str,
        target: LawOpenApiTarget,
        limit: int = 5,
        page: int = 1,
        search_scope: int = 1,
    ) -> LawOpenApiSearchResult:
        self._validate_request(
            query=query,
            target=target,
            limit=limit,
            page=page,
            search_scope=search_scope,
        )
        external_target = TARGET_TO_EXTERNAL_TARGET[target]
        params: dict[str, object] = {
            "OC": self.oc,
            "target": external_target,
            "type": "JSON",
            "query": query.strip(),
            "display": limit,
            "page": page,
            "search": search_scope,
        }
        if target == "admin_appeal":
            params["mobileYn"] = "Y"

        response = self._get(params)
        payload = self._parse_response_payload(response)
        rows = _extract_result_rows(payload, external_target)
        total_count = _extract_total_count(payload)
        items = [
            _normalize_item(row, target=target, oc=self.oc)
            for row in rows[:limit]
        ]
        return LawOpenApiSearchResult(
            query=query.strip(),
            target=target,
            external_target=external_target,
            page=page,
            limit=limit,
            total_count=total_count,
            items=items,
        )

    def _validate_request(
        self,
        *,
        query: str,
        target: LawOpenApiTarget,
        limit: int,
        page: int,
        search_scope: int,
    ) -> None:
        if not self.oc.strip():
            raise LawOpenApiConfigError("LAW_OPEN_API_OC is required")
        if not query.strip():
            raise ValueError("query must not be blank")
        if target not in TARGET_TO_EXTERNAL_TARGET:
            raise ValueError("target is not supported")
        if limit <= 0 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        if page <= 0:
            raise ValueError("page must be positive")
        if search_scope not in {1, 2}:
            raise ValueError("search_scope must be 1 or 2")

    def _get(self, params: dict[str, object]) -> httpx.Response:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url, params=params)
        except httpx.TimeoutException as exc:
            raise LawOpenApiTimeoutError("law open api request timed out") from exc
        except httpx.RequestError as exc:
            raise LawOpenApiUnavailableError("law open api request failed") from exc

        self._raise_for_error_response(response)
        return response

    def _raise_for_error_response(self, response: httpx.Response) -> None:
        status_code = response.status_code
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise LawOpenApiAuthError("law open api authentication failed")
        if status_code == 429:
            raise LawOpenApiRateLimitError("law open api rate limit exceeded")
        if status_code in {408, 504}:
            raise LawOpenApiTimeoutError("law open api request timed out")
        if status_code >= 500:
            raise LawOpenApiUnavailableError("law open api service unavailable")
        raise LawOpenApiResponseError("law open api request rejected")

    def _parse_response_payload(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = _parse_xml_response(response.text)
        if not isinstance(payload, dict):
            raise LawOpenApiResponseError("law open api response must be an object")
        if _has_api_error(payload):
            raise LawOpenApiResponseError("law open api returned an error response")
        return payload


def _parse_xml_response(text: str) -> dict[str, Any]:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise LawOpenApiResponseError(
            "law open api response was not valid JSON or XML"
        ) from exc
    return {root.tag: _element_to_value(root)}


def _element_to_value(element: ElementTree.Element) -> Any:
    children = list(element)
    if not children:
        return element.text or ""

    grouped: dict[str, Any] = {}
    for child in children:
        child_value = _element_to_value(child)
        if child.tag in grouped:
            existing = grouped[child.tag]
            if isinstance(existing, list):
                existing.append(child_value)
            else:
                grouped[child.tag] = [existing, child_value]
        else:
            grouped[child.tag] = child_value
    return grouped


def _extract_result_rows(
    payload: dict[str, Any],
    external_target: str,
) -> list[dict[str, Any]]:
    list_keys = EXTERNAL_TARGET_TO_LIST_KEYS.get(external_target, (external_target,))
    for key in list_keys:
        rows = _find_first_list_by_key(payload, key)
        if rows is not None:
            return [row for row in rows if isinstance(row, dict)]

    fallback_rows = _find_first_list_of_objects(payload)
    if fallback_rows is None:
        return []
    return fallback_rows


def _find_first_list_by_key(value: Any, key: str) -> list[Any] | None:
    if isinstance(value, dict):
        child = value.get(key)
        if isinstance(child, list):
            return child
        if isinstance(child, dict):
            return [child]
        for nested_value in value.values():
            found = _find_first_list_by_key(nested_value, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_first_list_by_key(item, key)
            if found is not None:
                return found
    return None


def _find_first_list_of_objects(value: Any) -> list[dict[str, Any]] | None:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    if isinstance(value, dict):
        for nested_value in value.values():
            found = _find_first_list_of_objects(nested_value)
            if found is not None:
                return found
    return None


def _extract_total_count(payload: dict[str, Any]) -> int | None:
    for key in ("totalCnt", "totalcnt", "검색결과개수", "총건수"):
        value = _find_first_scalar_by_key(payload, key)
        if value is None:
            continue
        try:
            return int(str(value).replace(",", ""))
        except ValueError:
            return None
    return None


def _find_first_scalar_by_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value and not isinstance(value[key], (dict, list)):
            return value[key]
        for nested_value in value.values():
            found = _find_first_scalar_by_key(nested_value, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_first_scalar_by_key(item, key)
            if found is not None:
                return found
    return None


def _normalize_item(
    row: dict[str, Any],
    *,
    target: LawOpenApiTarget,
    oc: str,
) -> LawOpenApiSearchItem:
    title = _first_text(row, _title_keys(target)) or "제목 없음"
    external_id = _first_text(row, _external_id_keys(target))
    source_url = _normalize_source_url(_first_text(row, _source_url_keys()), oc=oc)
    summary = _first_text(row, _summary_keys(target))
    return LawOpenApiSearchItem(
        external_id=external_id,
        title=title,
        source_url=source_url,
        summary=summary,
        target=target,
        metadata_json={
            key: _redact_oc(str(value), oc)
            for key, value in row.items()
            if not isinstance(value, (dict, list))
        },
    )


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _external_id_keys(target: LawOpenApiTarget) -> tuple[str, ...]:
    common = ("ID", "id", "일련번호")
    if target == "statute":
        return ("법령일련번호", "법령ID", "MST", *common)
    if target == "case":
        return ("판례일련번호", "판례ID", "사건번호", *common)
    if target == "interpretation":
        return ("법령해석례일련번호", "해석례일련번호", "안건번호", "itmno", *common)
    return ("행정심판례일련번호", "재결례일련번호", "사건번호", *common)


def _title_keys(target: LawOpenApiTarget) -> tuple[str, ...]:
    if target == "statute":
        return ("법령명한글", "법령명", "현행법령명", "법령약칭명")
    if target == "case":
        return ("사건명", "판례명", "제목")
    if target == "interpretation":
        return ("안건명", "법령해석례명", "법령해석명", "제목")
    return ("사건명", "재결례명", "행정심판례명", "제목")


def _summary_keys(target: LawOpenApiTarget) -> tuple[str, ...]:
    if target == "case":
        return ("판시사항", "판결요지", "요약", "내용")
    if target == "interpretation":
        return ("질의요지", "회답", "요약", "내용")
    if target == "admin_appeal":
        return ("재결요지", "요약", "내용")
    return ("소관부처명", "요약", "내용")


def _source_url_keys() -> tuple[str, ...]:
    return (
        "법령상세링크",
        "판례상세링크",
        "법령해석례상세링크",
        "행정심판례상세링크",
        "상세링크",
        "링크",
        "url",
    )


def _normalize_source_url(value: str | None, *, oc: str) -> str | None:
    if value is None:
        return None
    redacted_value = _redact_oc(value, oc)
    if redacted_value.startswith("http://") or redacted_value.startswith("https://"):
        return redacted_value
    if redacted_value.startswith("/"):
        return f"https://www.law.go.kr{redacted_value}"
    return f"https://www.law.go.kr/{redacted_value.lstrip()}"


def _redact_oc(value: str, oc: str) -> str:
    if oc.strip():
        return value.replace(oc, "[REDACTED]")
    return value


def _has_api_error(payload: dict[str, Any]) -> bool:
    error_value = _find_first_scalar_by_key(payload, "error")
    if error_value is None:
        error_value = _find_first_scalar_by_key(payload, "Error")
    if error_value is None:
        return False
    return bool(str(error_value).strip())

