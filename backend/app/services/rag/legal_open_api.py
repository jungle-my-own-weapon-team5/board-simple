"""국가법령정보 Open API 검색 client입니다."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html import unescape
import re
from typing import Any, Literal
from xml.etree import ElementTree

import httpx2 as httpx

LawOpenApiTarget = Literal["statute", "case", "interpretation", "admin_appeal"]
DEFAULT_LAW_OPEN_API_BASE_URL = "https://www.law.go.kr/DRF/lawSearch.do"
DEFAULT_LAW_OPEN_API_SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
TARGET_TO_EXTERNAL_TARGET: dict[LawOpenApiTarget, str] = {
    "statute": "law",
    "case": "prec",
    "interpretation": "expc",
    "admin_appeal": "decc",
}
LAW_BODY_CONTENT_KEYS = {
    "조문내용",
    "항내용",
    "호내용",
    "목내용",
    "부칙내용",
}
TAG_PATTERN = re.compile(r"<[^>]+>")
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
class LawOpenApiDocumentMetadata:
    """전문 조회 전 최신성 비교에 사용하는 외부 법률 문서 metadata입니다."""

    provider: str
    provider_target: str
    document_type: LawOpenApiTarget
    title: str
    external_id: str | None
    canonical_id: str | None
    version_label: str | None
    published_date: date | None
    effective_date: date | None
    source_url: str | None
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LawOpenApiSearchItem:
    external_id: str | None
    title: str
    source_url: str | None
    summary: str | None
    target: LawOpenApiTarget
    metadata_json: dict[str, Any] = field(default_factory=dict)
    preflight_metadata: LawOpenApiDocumentMetadata | None = None


@dataclass(frozen=True)
class LawOpenApiSearchResult:
    query: str
    target: LawOpenApiTarget
    external_target: str
    page: int
    limit: int
    total_count: int | None
    items: list[LawOpenApiSearchItem]


@dataclass(frozen=True)
class LawOpenApiLawBody:
    """`lawService.do`에서 받은 법령 본문을 ingestion 가능한 형태로 정규화한 결과입니다."""

    title: str
    raw_text: str
    external_id: str | None
    law_id: str | None
    mst: str | None
    source_url: str | None
    published_date: date | None
    effective_date: date | None
    version_label: str | None
    metadata_json: dict[str, Any] = field(default_factory=dict)


class LawOpenApiClient:
    """국가법령정보 공동활용 `lawSearch.do` 목록 검색 client입니다."""

    def __init__(
        self,
        *,
        oc: str,
        base_url: str = DEFAULT_LAW_OPEN_API_BASE_URL,
        service_url: str = DEFAULT_LAW_OPEN_API_SERVICE_URL,
        timeout_seconds: int = 30,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.oc = oc
        self.base_url = base_url
        self.service_url = service_url
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

    def get_law_body(
        self,
        *,
        mst: str | None = None,
        law_id: str | None = None,
    ) -> LawOpenApiLawBody:
        """현행법령 본문을 조회해 조문 중심 plain text로 변환합니다.

        국가법령정보 `lawService.do?target=law`는 `MST` 또는 `ID` 중 하나로
        본문을 조회합니다. 둘 다 있으면 목록 응답의 법령일련번호에 해당하는
        `MST`를 우선 사용합니다.
        """

        self._validate_law_body_request(mst=mst, law_id=law_id)
        params: dict[str, object] = {
            "OC": self.oc,
            "target": "law",
            "type": "JSON",
        }
        if mst is not None and mst.strip():
            params["MST"] = mst.strip()
        elif law_id is not None and law_id.strip():
            params["ID"] = law_id.strip()

        response = self._get(params, url=self.service_url)
        payload = self._parse_response_payload(response)
        return _normalize_law_body(payload, oc=self.oc)

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

    def _validate_law_body_request(
        self,
        *,
        mst: str | None,
        law_id: str | None,
    ) -> None:
        if not self.oc.strip():
            raise LawOpenApiConfigError("LAW_OPEN_API_OC is required")
        if (mst is None or not mst.strip()) and (law_id is None or not law_id.strip()):
            raise ValueError("mst or law_id is required")

    def _get(
        self,
        params: dict[str, object],
        *,
        url: str | None = None,
    ) -> httpx.Response:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(url or self.base_url, params=params)
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
    preflight_metadata = _normalize_preflight_metadata(
        row,
        target=target,
        title=title,
        external_id=external_id,
        source_url=source_url,
        oc=oc,
    )
    return LawOpenApiSearchItem(
        external_id=preflight_metadata.external_id or external_id,
        title=title,
        source_url=source_url,
        summary=summary,
        target=target,
        metadata_json=_redact_mapping_scalars(row, oc),
        preflight_metadata=preflight_metadata,
    )


def _normalize_preflight_metadata(
    row: dict[str, Any],
    *,
    target: LawOpenApiTarget,
    title: str,
    external_id: str | None,
    source_url: str | None,
    oc: str,
) -> LawOpenApiDocumentMetadata:
    provider_target = TARGET_TO_EXTERNAL_TARGET[target]
    canonical_id = _first_text(row, _canonical_id_keys(target))
    if target == "statute" and canonical_id is None:
        canonical_id = title if title != "제목 없음" else None
    published_date = _parse_yyyymmdd_date(_first_text(row, _published_date_keys(target)))
    effective_date = _parse_yyyymmdd_date(_first_text(row, _effective_date_keys(target)))
    version_label = _build_preflight_version_label(
        target=target,
        effective_date=effective_date,
        version_number=_first_text(row, _version_number_keys(target)),
        published_date=published_date,
    )
    preflight_source_url = _preflight_source_url(
        target=target,
        title=title,
        source_url=source_url,
    )
    return LawOpenApiDocumentMetadata(
        provider="law_open_api",
        provider_target=provider_target,
        document_type=target,
        title=title,
        external_id=external_id,
        canonical_id=canonical_id,
        version_label=version_label,
        published_date=published_date,
        effective_date=effective_date,
        source_url=preflight_source_url,
        metadata_json={
            "provider": "law_open_api",
            "provider_target": provider_target,
            "document_type": target,
            "external_id": external_id,
            "canonical_id": canonical_id,
            "version_label": version_label,
            "published_date": _date_to_iso(published_date),
            "effective_date": _date_to_iso(effective_date),
            "source_url": preflight_source_url,
            "raw_metadata": _redact_mapping_scalars(row, oc),
        },
    )


def _normalize_law_body(
    payload: dict[str, Any],
    *,
    oc: str,
) -> LawOpenApiLawBody:
    law_root = _extract_law_root(payload)
    basic_info = _find_first_dict_by_key(law_root, "기본정보") or {}
    title = (
        _first_text(basic_info, ("법령명_한글", "법령명한글", "법령명", "현행법령명"))
        or _first_text(payload, ("법령명_한글", "법령명한글", "법령명", "현행법령명"))
        or "제목 없음"
    )
    mst = _first_text(basic_info, ("법령일련번호", "MST"))
    law_id = _first_text(basic_info, ("법령ID", "ID"))
    published_date = _parse_yyyymmdd_date(
        _first_text(basic_info, ("공포일자", "공포일"))
    )
    effective_date = _parse_yyyymmdd_date(
        _first_text(basic_info, ("시행일자", "시행일"))
    )
    promulgation_number = _first_text(basic_info, ("공포번호",))
    body_parts = _extract_law_body_parts(law_root)
    raw_text = _join_law_body_text(
        title=title,
        published_date=published_date,
        effective_date=effective_date,
        body_parts=body_parts,
    )
    if not raw_text.strip():
        raise LawOpenApiResponseError("law open api body text was empty")

    external_id = mst or law_id
    version_label = _build_law_version_label(
        effective_date=effective_date,
        promulgation_number=promulgation_number,
        published_date=published_date,
    )
    source_url = _law_hangul_url(title)
    return LawOpenApiLawBody(
        title=title,
        raw_text=raw_text,
        external_id=external_id,
        law_id=law_id,
        mst=mst,
        source_url=source_url,
        published_date=published_date,
        effective_date=effective_date,
        version_label=version_label,
        metadata_json={
            "provider_target": "law",
            "external_id": external_id,
            "law_id": law_id,
            "mst": mst,
            "promulgation_number": promulgation_number,
            "source_url": source_url,
            "raw_basic_info": _redact_mapping_scalars(basic_info, oc),
        },
    )


def _extract_law_root(payload: dict[str, Any]) -> dict[str, Any]:
    law_root = _find_first_dict_by_key(payload, "법령")
    if law_root is not None:
        return law_root
    return payload


def _find_first_dict_by_key(value: Any, key: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        child = value.get(key)
        if isinstance(child, dict):
            return child
        for nested_value in value.values():
            found = _find_first_dict_by_key(nested_value, key)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_first_dict_by_key(item, key)
            if found is not None:
                return found
    return None


def _extract_law_body_parts(law_root: dict[str, Any]) -> list[str]:
    article_rows = _find_first_list_by_key(law_root, "조문단위")
    if article_rows is None:
        article_rows = _find_first_list_by_key(law_root, "부칙단위")

    parts: list[str] = []
    if article_rows is not None:
        for row in article_rows:
            row_parts: list[str] = []
            _collect_law_content_texts(row, row_parts)
            parts.extend(row_parts)

    if parts:
        return _deduplicate_adjacent_texts(parts)

    fallback_parts: list[str] = []
    _collect_law_content_texts(law_root, fallback_parts)
    return _deduplicate_adjacent_texts(fallback_parts)


def _collect_law_content_texts(value: Any, parts: list[str]) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if key in LAW_BODY_CONTENT_KEYS:
                text = _clean_body_text(nested_value)
                if text:
                    parts.append(text)
                continue
            _collect_law_content_texts(nested_value, parts)
        return

    if isinstance(value, list):
        for item in value:
            _collect_law_content_texts(item, parts)


def _clean_body_text(value: Any) -> str | None:
    if isinstance(value, (dict, list)):
        nested_parts: list[str] = []
        _collect_law_content_texts(value, nested_parts)
        return "\n".join(nested_parts) if nested_parts else None
    text = unescape(str(value))
    text = TAG_PATTERN.sub("", text)
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned or None


def _deduplicate_adjacent_texts(parts: list[str]) -> list[str]:
    deduplicated: list[str] = []
    for part in parts:
        if deduplicated and deduplicated[-1] == part:
            continue
        deduplicated.append(part)
    return deduplicated


def _join_law_body_text(
    *,
    title: str,
    published_date: date | None,
    effective_date: date | None,
    body_parts: list[str],
) -> str:
    header = [title]
    if published_date is not None:
        header.append(f"공포일자: {published_date.isoformat()}")
    if effective_date is not None:
        header.append(f"시행일자: {effective_date.isoformat()}")
    return "\n".join(header + ["", *body_parts]).strip()


def _parse_yyyymmdd_date(value: str | None) -> date | None:
    if value is None:
        return None
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) != 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def _build_law_version_label(
    *,
    effective_date: date | None,
    promulgation_number: str | None,
    published_date: date | None,
) -> str | None:
    parts = [
        effective_date.isoformat() if effective_date is not None else None,
        promulgation_number,
        published_date.isoformat() if published_date is not None else None,
    ]
    label = ",".join(part for part in parts if part)
    return label or None


def _build_preflight_version_label(
    *,
    target: LawOpenApiTarget,
    effective_date: date | None,
    version_number: str | None,
    published_date: date | None,
) -> str | None:
    if target == "statute":
        return _build_law_version_label(
            effective_date=effective_date,
            promulgation_number=version_number,
            published_date=published_date,
        )

    parts = [
        effective_date.isoformat() if effective_date is not None else None,
        version_number,
        published_date.isoformat() if published_date is not None else None,
    ]
    label = ",".join(part for part in parts if part)
    return label or None


def _date_to_iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _preflight_source_url(
    *,
    target: LawOpenApiTarget,
    title: str,
    source_url: str | None,
) -> str | None:
    if target == "statute":
        return _law_hangul_url(title) or source_url
    return source_url


def _law_hangul_url(title: str) -> str | None:
    stripped_title = title.strip()
    if not stripped_title or stripped_title == "제목 없음":
        return None
    return f"https://www.law.go.kr/법령/{stripped_title}"


def _redact_mapping_scalars(
    mapping: dict[str, Any],
    oc: str,
) -> dict[str, str]:
    return {
        key: _redact_oc(str(value), oc)
        for key, value in mapping.items()
        if not isinstance(value, (dict, list))
    }


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


def _canonical_id_keys(target: LawOpenApiTarget) -> tuple[str, ...]:
    if target == "statute":
        return ("법령ID", "ID", "lawId")
    if target == "case":
        return ("사건번호", "판례ID", "판례일련번호", "ID")
    if target == "interpretation":
        return ("안건번호", "법령해석례일련번호", "해석례일련번호", "ID")
    return ("사건번호", "행정심판례일련번호", "재결례일련번호", "ID")


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


def _published_date_keys(target: LawOpenApiTarget) -> tuple[str, ...]:
    if target == "statute":
        return ("공포일자", "공포일")
    if target == "case":
        return ("선고일자", "판결일자", "판례일자")
    if target == "interpretation":
        return ("회신일자", "해석일자", "안건일자")
    return ("재결일자", "의결일자", "처분일자")


def _effective_date_keys(target: LawOpenApiTarget) -> tuple[str, ...]:
    if target == "statute":
        return ("시행일자", "시행일")
    return ()


def _version_number_keys(target: LawOpenApiTarget) -> tuple[str, ...]:
    if target == "statute":
        return ("공포번호",)
    if target == "case":
        return ("사건번호",)
    if target == "interpretation":
        return ("안건번호",)
    return ("사건번호",)


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

