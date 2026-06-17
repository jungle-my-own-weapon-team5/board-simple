from scripts.score_sillok_article_candidates import SillokCandidate, score_candidate, trim_grouped_to_total


def test_sillok_candidate_scoring_prefers_specific_event_article() -> None:
    strong = score_candidate(
        SillokCandidate(
            sillok_id="kca_11711024_002",
            title="세자가 금빛 고양이를 구하려 하다",
            period="태종실록",
            source_url="https://sillok.history.go.kr/id/kca_11711024_002",
            categories="왕실-종친(宗親) / 과학-생물(生物)",
            content="세자가 신효창의 집에 금빛 고양이를 구하니 탁신이 서연관에게 말하였다.",
        )
    )
    weak = score_candidate(
        SillokCandidate(
            sillok_id="kca_10000000_001",
            title="관직을 제수하다",
            period="태종실록",
            source_url="https://sillok.history.go.kr/id/kca_10000000_001",
            categories="인사-임면(任免)",
            content="아무개를 사정으로 삼았다.",
        )
    )

    assert strong.score > weak.score
    assert strong.primary_bucket == "person_relation"
    assert "yangnyeong_cat" in strong.evaluation_matches
    assert all(not reason.startswith("validation:") for reason in strong.selection_reasons)
    assert "low_signal_penalty" in weak.selection_reasons


def test_sillok_candidate_scoring_classifies_life_history_article() -> None:
    scored = score_candidate(
        SillokCandidate(
            sillok_id="sample",
            title="흉년으로 백성을 진휼하게 하다",
            period="선조실록",
            source_url="https://sillok.history.go.kr/id/sample",
            categories="구휼(救恤) / 농업(農業)",
            content="흉년이 들어 진휼하고 전세와 군역을 감면하게 하였다.",
        )
    )

    assert scored.primary_bucket == "system_life"
    assert scored.score_parts["system_life"] > 0


def test_trim_grouped_to_total_removes_lowest_scores() -> None:
    scores = [
        score_candidate(
            SillokCandidate(
                sillok_id=f"kca_1000000{index}_001",
                title=f"사건 기사 {index}",
                period="태종실록",
                source_url=f"https://sillok.history.go.kr/id/kca_1000000{index}_001",
                categories="정치-변란",
                content="반정과 상소에 관한 기사이다." * index,
            )
        )
        for index in range(1, 5)
    ]

    grouped = trim_grouped_to_total({"태종실록": scores}, 2)

    assert sum(len(items) for items in grouped.values()) == 2
    assert {item.sillok_id for item in grouped["태종실록"]} == {
        scores[2].sillok_id,
        scores[3].sillok_id,
    }
