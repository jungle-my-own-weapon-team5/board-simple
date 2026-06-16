from app.services.ai_runtime import _is_unique_seed_source_url, _normalize_for_rag_content


def test_normalize_for_rag_content_adds_korean_aliases() -> None:
    content = (
        "왜변이 일어난 후 조선정부는 大內·小貳殿을 제외하고 통교를 단절하였다. "
        "명종 2년 丁未約條를 체결하였다. 763)"
    )

    normalized = _normalize_for_rag_content(content)

    assert "대내씨(大內)" in normalized
    assert "소이전/소이씨(小貳殿)" in normalized
    assert "정미약조(丁未約條)" in normalized
    assert "763)" not in normalized


def test_normalize_for_rag_content_preserves_existing_aliases() -> None:
    content = "정미약조(丁未約條)는 대마도와의 통교 재개와 관련된다."

    normalized = _normalize_for_rag_content(content)

    assert normalized.count("정미약조") == 1
    assert "정미약조(丁未約條)" in normalized


def test_unique_seed_source_url_detection() -> None:
    assert _is_unique_seed_source_url("https://sillok.history.go.kr/id/kda_10101001_001")
    assert _is_unique_seed_source_url("https://contents.history.go.kr/front/nh/view.do?levelId=nh_022_0010")
    assert not _is_unique_seed_source_url("https://sillok.history.go.kr")
