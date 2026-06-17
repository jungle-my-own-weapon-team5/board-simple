import ssl

import httpx2 as httpx
import pytest

from app.services.rag.legal_open_api import LawOpenApiClient


def test_law_open_api_client_uses_system_trust_store_by_default() -> None:
    client = LawOpenApiClient(oc="test-oc")

    assert isinstance(client.verify, ssl.SSLContext)


def test_law_open_api_client_allows_custom_tls_verification() -> None:
    client = LawOpenApiClient(oc="test-oc", verify=False)

    assert client.verify is False


def test_search_statute_extracts_preflight_metadata_and_redacts_oc() -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        params = dict(request.url.params)
        assert str(request.url).startswith("https://law.example.test/DRF/lawSearch.do")
        assert params["OC"] == "test-oc"
        assert params["target"] == "law"
        assert params["type"] == "JSON"
        assert params["query"] == "자동차관리법"
        return httpx.Response(
            200,
            json={
                "LawSearch": {
                    "totalCnt": "1",
                    "law": [
                        {
                            "법령일련번호": "123456",
                            "법령ID": "001234",
                            "법령명한글": "자동차관리법",
                            "공포일자": "20240101",
                            "공포번호": "12345",
                            "시행일자": "20240201",
                            "법령상세링크": "/법령/자동차관리법?OC=test-oc",
                            "소관부처명": "국토교통부",
                        }
                    ],
                }
            },
        )

    client = LawOpenApiClient(
        oc="test-oc",
        base_url="https://law.example.test/DRF/lawSearch.do",
        transport=httpx.MockTransport(handler),
    )

    result = client.search(query="자동차관리법", target="statute", limit=1)

    assert result.total_count == 1
    item = result.items[0]
    assert item.external_id == "123456"
    assert item.title == "자동차관리법"
    assert "[REDACTED]" in item.source_url
    assert "test-oc" not in str(item.metadata_json)
    preflight = item.preflight_metadata
    assert preflight is not None
    assert preflight.provider == "law_open_api"
    assert preflight.provider_target == "law"
    assert preflight.document_type == "statute"
    assert preflight.external_id == "123456"
    assert preflight.canonical_id == "001234"
    assert preflight.published_date.isoformat() == "2024-01-01"
    assert preflight.effective_date.isoformat() == "2024-02-01"
    assert preflight.version_label == "2024-02-01,12345,2024-01-01"
    assert preflight.source_url == "https://www.law.go.kr/법령/자동차관리법"
    assert preflight.metadata_json["published_date"] == "2024-01-01"
    assert preflight.metadata_json["effective_date"] == "2024-02-01"
    assert "[REDACTED]" in preflight.metadata_json["raw_metadata"]["법령상세링크"]
    assert "test-oc" not in str(preflight.metadata_json)
    assert "test-oc" in captured_urls[0]


def test_get_law_body_calls_service_endpoint_with_mst_and_extracts_articles() -> None:
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        params = dict(request.url.params)
        assert str(request.url).startswith("https://law.example.test/DRF/lawService.do")
        assert params["OC"] == "test-oc"
        assert params["target"] == "law"
        assert params["type"] == "JSON"
        assert params["MST"] == "123456"
        assert "ID" not in params
        return httpx.Response(
            200,
            json={
                "법령": {
                    "기본정보": {
                        "법령일련번호": "123456",
                        "법령ID": "001234",
                        "법령명_한글": "자동차관리법",
                        "공포일자": "20240101",
                        "공포번호": "12345",
                        "시행일자": "20240201",
                    },
                    "조문": {
                        "조문단위": [
                            {
                                "조문내용": "제1조(목적) 이 법은 자동차 관리를 정한다.",
                                "항": [
                                    {
                                        "항내용": "① 자동차 소유자는 등록하여야 한다.",
                                        "호": [
                                            {"호내용": "1. 등록 신청"},
                                            {"호내용": "2. 변경 신고"},
                                        ],
                                    }
                                ],
                            },
                            {
                                "조문내용": "제2조(정의) 이 법에서 사용하는 용어의 뜻은 다음과 같다.",
                            },
                        ]
                    },
                }
            },
        )

    client = LawOpenApiClient(
        oc="test-oc",
        service_url="https://law.example.test/DRF/lawService.do",
        transport=httpx.MockTransport(handler),
    )

    result = client.get_law_body(mst="123456", law_id="001234")

    assert result.title == "자동차관리법"
    assert result.external_id == "123456"
    assert result.mst == "123456"
    assert result.law_id == "001234"
    assert result.published_date.isoformat() == "2024-01-01"
    assert result.effective_date.isoformat() == "2024-02-01"
    assert result.version_label == "2024-02-01,12345,2024-01-01"
    assert result.source_url == "https://www.law.go.kr/법령/자동차관리법"
    assert "자동차관리법" in result.raw_text
    assert "제1조(목적) 이 법은 자동차 관리를 정한다." in result.raw_text
    assert "① 자동차 소유자는 등록하여야 한다." in result.raw_text
    assert "1. 등록 신청" in result.raw_text
    assert "제2조(정의)" in result.raw_text
    assert "test-oc" not in str(result.metadata_json)
    assert "test-oc" in captured_urls[0]


def test_get_law_body_keeps_article_heading_before_paragraphs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "법령": {
                    "기본정보": {
                        "법령일련번호": "123456",
                        "법령ID": "001234",
                        "법령명_한글": "형법",
                    },
                    "조문": {
                        "조문단위": [
                            {
                                "항": [
                                    {
                                        "항번호": "①",
                                        "항내용": "① 죄를 지은 후 수사기관에 자수한 경우에는 형을 감경하거나 면제할 수 있다.",
                                    }
                                ],
                                "조문내용": "제52조(자수, 자복)",
                                "조문제목": "자수, 자복",
                            }
                        ]
                    },
                }
            },
        )

    client = LawOpenApiClient(
        oc="test-oc",
        service_url="https://law.example.test/DRF/lawService.do",
        transport=httpx.MockTransport(handler),
    )

    result = client.get_law_body(mst="123456")

    assert "제52조(자수, 자복)\n① 죄를 지은 후" in result.raw_text
    assert "None" not in result.raw_text


def test_get_law_body_can_call_service_endpoint_with_law_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        assert params["ID"] == "ABC123"
        assert "MST" not in params
        return httpx.Response(
            200,
            json={
                "법령": {
                    "기본정보": {
                        "법령ID": "ABC123",
                        "법령명한글": "테스트법",
                    },
                    "조문": {
                        "조문단위": {
                            "조문내용": "제1조(목적) 테스트 목적을 정한다.",
                        }
                    },
                }
            },
        )

    client = LawOpenApiClient(
        oc="test-oc",
        service_url="https://law.example.test/DRF/lawService.do",
        transport=httpx.MockTransport(handler),
    )

    result = client.get_law_body(law_id="ABC123")

    assert result.title == "테스트법"
    assert result.external_id == "ABC123"
    assert result.raw_text.endswith("제1조(목적) 테스트 목적을 정한다.")


def test_get_law_body_requires_mst_or_law_id() -> None:
    client = LawOpenApiClient(oc="test-oc")

    with pytest.raises(ValueError, match="mst or law_id is required"):
        client.get_law_body()

