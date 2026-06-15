# RAG Chunking 설정값 근거

## 문서 상태

- 목적: 현재 RAG chunking 코드 profile 기본값과 향후 환경변수 후보 값을 정하기 위한 문헌 근거를 기록합니다.
- 범위: 대한민국 법률 일반, 판례, 법령해석례, 행정심판례, 사용자 업로드 법률 문서의 초기 chunking 정책입니다.
- 성격: 이 문서는 시스템 아키텍처 문서가 아닙니다. `docs/rag-pipeline.md`의 chunking 단계에서 사용할 설정값 판단 근거입니다.
- 검색일: 2026-06-15

## 결론

대한민국 법률 RAG에 대해 검증된 단일 최적 chunk size는 아직 확인하지 못했습니다. 국내외 연구는 공통적으로 고정 길이 하나를 최적값으로 제시하기보다, 문서 구조 보존, 의미 단위 분할, hybrid retrieval, reranking, 평가 fixture를 함께 봐야 한다는 방향을 보입니다.

따라서 이 프로젝트의 초기 정책은 다음처럼 둡니다.

- 법령은 조문 구조를 우선 보존합니다.
- 조문, 항, 호 구조는 별도 계층형 테이블로 저장하지 않고 chunk 본문과 metadata anchor에 보존합니다.
- 짧은 조문은 억지로 다른 조문과 병합하지 않습니다.
- 긴 조문이나 긴 문단만 fallback 길이 기준으로 분할합니다.
- `500 characters` 전후는 여러 legal RAG 연구에서 retrieval baseline 또는 균형점으로 쓰인 값이지만, 보편 최적값은 아닙니다.
- 이 프로젝트는 단순 검색보다 답변 초안 생성이 목적이므로, 일부 문서 유형은 retrieval-only baseline보다 약간 넓은 문맥을 허용합니다.
- 최종값은 fixture 기반 retrieval 평가 결과로 조정합니다.

## 현재 코드 Profile 초기값

답변 생성형 RAG를 위한 문서 유형별 초기 baseline은 현재 `backend/app/services/rag/chunking.py`의 코드 profile에 다음 값으로 적용합니다. 아직 이 값들은 환경변수로 주입되지 않습니다.

```text
fallback:       min_chars=150, max_chars=900,  overlap_chars=90,  merge_short_article_chunks=True
statute:        min_chars=0,   max_chars=700,  overlap_chars=80,  merge_short_article_chunks=False
case:           min_chars=250, max_chars=1200, overlap_chars=120, merge_short_article_chunks=True
interpretation: min_chars=200, max_chars=900,  overlap_chars=90,  merge_short_article_chunks=True
admin_appeal:   min_chars=200, max_chars=1000, overlap_chars=100, merge_short_article_chunks=True
user_file:      min_chars=150, max_chars=900,  overlap_chars=90,  merge_short_article_chunks=True
memo:           min_chars=80,  max_chars=500,  overlap_chars=50,  merge_short_article_chunks=True
```

`statute` 값의 의미는 다음과 같습니다.

- `min_chars=0`: 짧은 조문도 독립 citation 단위로 남깁니다.
- `max_chars=700`: 긴 조문을 검색 context에 과도하게 넣지 않되, 답변 생성에 필요한 요건, 예외, 효과 문맥을 함께 보존하기 위한 fallback 상한입니다.
- `overlap_chars=80`: 긴 조문을 분할할 때 앞뒤 문맥 손실을 줄이기 위한 보수적 overlap입니다.
- `merge_short_article_chunks=False`: 서로 다른 조문이 한 chunk에 섞여 citation 정밀도가 떨어지는 것을 피합니다.

이 값들은 법률 도메인 최적값으로 확정된 값이 아닙니다. 문헌에서 자주 쓰인 retrieval baseline, 답변 생성에 필요한 문맥량, 현재 프로젝트의 citation 요구를 결합한 시작점입니다.

## 문헌 검토

### 1. 한국어 법률 QA를 위한 하이브리드 RAG 시스템 최적화

- 저자: 서준원, 민정혜
- 연도: 2025
- 링크: https://journal.kci.go.kr/jksci/archive/articleView?artiId=ART003234187

한국어 법률 RAG에서 문서 분할, embedding model, retrieval strategy를 함께 최적화한 국내 연구입니다. 의미 기반 chunking, 한국어 법률 데이터로 fine-tuning한 E5 계열 embedding, BM25 기반 hybrid retrieval 조합이 우수한 결과를 보였다고 보고합니다.

이 연구는 고정 글자 수 하나보다 의미 기반 분할과 hybrid retrieval이 중요하다는 근거입니다.

### 2. RAG based Question Answering of Korean Laws and Precedents

- 저자: Kiho Seo, Takehito Utsuro
- 학회: FEVER 2025
- 링크: https://aclanthology.org/2025.fever-1.7/

한국 법령과 판례를 대상으로 RAG 질의응답을 구성한 연구입니다. 법령 collection을 조문, 항, 호의 3단계 구조로 다루며, 각 계층을 검색 가능한 단위로 보면서 계층 관계를 유지합니다.

이 연구는 대한민국 법령 RAG에서 조문 구조를 무시한 단순 길이 분할이 부적절하다는 강한 근거입니다. 다만 이 프로젝트는 초기 schema를 단순하게 유지하기 위해 계층을 별도 테이블로 만들지는 않고, chunk 본문과 metadata에 보존합니다.

### 3. RAR-Agent: 법률 질의응답을 위한 근거 보강형 검색 시스템

- 저자: 김규형, 도윤혁, 송준현, Ziyang Liu
- 연도: 2026
- 링크: https://journal.kci.go.kr/jksci/archive/articleView?artiId=ART003305933

한국어 법률 QA에서 lexical mismatch 문제를 줄이기 위해 rationale 기반 query formulation, Reciprocal Rank Fusion, reranker filtering을 결합한 연구입니다. KL-BQA, KL-RQA benchmark를 통해 법률 질의응답의 사실성을 평가합니다.

이 연구는 chunk size만으로 법률 RAG 품질을 해결할 수 없고, query 변환, hybrid retrieval, reranking, 평가 benchmark가 함께 필요하다는 근거입니다.

### 4. KoBLEX: Open Legal Question Answering with Multi-hop Reasoning

- 저자: Lee et al.
- 연도: 2025
- 링크: https://arxiv.org/html/2509.01324v1

한국 법률의 조문 근거 기반 open-ended QA benchmark입니다. 복수 조문을 함께 찾아야 하는 multi-hop reasoning을 다루며, ParSeR라는 3단계 Retrieve-Rerank-Selection retrieval 방식을 제안합니다.

이 연구는 대한민국 법률 질의응답에서 단일 chunk 검색보다 조문 근거 검색, 재정렬, 조문 간 결합이 중요하다는 근거입니다.

### 5. LegalBench-RAG

- 저자: Nicholas Pipitone, Ghita Houir Alami
- 연도: 2024
- 링크: https://arxiv.org/html/2408.10343v1

법률 도메인 RAG의 retrieval component를 평가하기 위한 benchmark입니다. 비교 대상 chunking 전략 중 하나로 `500 characters` 고정 길이, overlap 없음 방식을 사용하고, 다른 하나로 recursive character text splitter를 사용합니다.

이 연구는 `500 characters`를 legal RAG 실험 baseline으로 볼 수 있는 근거입니다. 단, 이 값은 대한민국 법률에 대한 최적값이 아니라 benchmark 비교를 위한 기준값입니다.

### 6. Towards Reliable Retrieval in RAG Systems for Large Legal Datasets

- 저자: Zilli et al.
- 연도: 2025
- 링크: https://aclanthology.org/2025.nllp-1.3.pdf

대규모 법률 데이터셋에서 RAG retrieval 안정성을 다룹니다. 부록에서 `200`, `500`, `800` character chunk와 `150`, `300` character summary 조합을 비교하고, 최종 pipeline에는 `500 characters` chunk와 `150 characters` summary를 선택합니다.

이 연구는 `500 characters`가 precision과 recall 사이의 균형점으로 관찰된 사례입니다. 다만 summary prepend를 함께 사용한 설정이므로, chunk size만 독립적으로 가져와 최적값으로 단정하면 안 됩니다.

### 7. Legal Chunking: Evaluating Methods for Effective Legal Text Retrieval

- 학회: JURIX 2024
- 링크: https://journals.sagepub.com/doi/10.3233/FAIA241255

GDPR을 대상으로 simple text splitting, regex recursive splitting, semantic chunking을 비교한 legal chunking 연구입니다. 어떤 방법도 개별 chunk 수준에서 모든 질문에 일관되게 높은 semantic relevance를 보이지는 않았다고 보고합니다.

이 연구는 법률 문서 chunking에 보편적인 단일 해법이 없고, 문서 유형과 질문 유형에 따라 평가가 필요하다는 근거입니다.

### 8. Document Segmentation Matters for Retrieval-Augmented Generation

- 저자: Wang et al.
- 학회: ACL Findings 2025
- 링크: https://aclanthology.org/2025.findings-acl.422/

일반 RAG chunking 연구입니다. 큰 chunk는 불필요한 정보를 포함해 retrieval과 generation을 방해할 수 있고, 작은 chunk는 의미 정보가 부족해 답변 품질을 떨어뜨릴 수 있다는 trade-off를 정리합니다.

이 연구는 `max_chars`와 `min_chars`를 무작정 크게 또는 작게 둘 수 없고, 검색 정확도와 의미 완결성 사이의 균형을 평가해야 한다는 근거입니다.

### 9. NitiBench: Benchmarking LLM Frameworks on Thai Legal Question Answering Capabilities

- 저자: Akarajaradwong et al.
- 학회: EMNLP 2025
- 링크: https://aclanthology.org/2025.emnlp-main.1739/

태국 법률 QA benchmark입니다. 법률 문서의 복잡한 구조 때문에 hierarchy-aware chunking과 cross-reference 처리를 평가합니다. 결과적으로 domain-specific component가 naive method보다 일부 개선을 보였지만, 복잡한 법률 질의에서는 retrieval model의 한계도 남아 있다고 설명합니다.

이 연구는 한국 법령처럼 구조가 강한 법률 문서에서도 hierarchy-aware 접근과 cross-reference 처리가 중요하다는 비교 근거입니다.

### 10. Interpretable Long-Form Legal Question Answering with Retrieval-Augmented Large Language Models

- 저자: Antoine Louis, Gijs van Dijck, Gerasimos Spanakis
- 학회: AAAI 2024
- 링크: https://arxiv.org/abs/2309.17050

프랑스어 statutory law question answering을 위한 retrieve-then-read pipeline과 LLeQA dataset을 제안한 연구입니다. 법률 QA에서는 긴 답변도 관련 법 조항에 근거해야 하고, retrieval 결과의 해석 가능성이 중요하다는 점을 보여줍니다.

이 연구는 chunk 자체보다 citation 가능한 법 조항 검색과 근거 기반 답변이 중요하다는 근거입니다.

## 설정값 해석

### `min_chars`

법령 chunk에서 `min_chars`는 낮게 두는 편이 안전합니다. 조문이 짧다는 이유만으로 다른 조문과 병합하면 citation 단위가 흐려집니다.

대한민국 법령 일반에서는 짧은 정의 조항, 적용 범위 조항, 벌칙 조항이 독립적으로 중요한 의미를 가질 수 있습니다. 따라서 `statute` profile에서는 `min_chars=0` 또는 매우 작은 값을 우선 검토합니다.

### `max_chars`

`max_chars`는 chunk가 너무 커져 retrieval 결과에 불필요한 조문, 단서, 예외가 섞이는 것을 막기 위한 상한입니다. 동시에 답변 생성 단계에서 필요한 요건, 예외, 효과 문맥이 지나치게 끊기지 않도록 너무 작게 두지 않아야 합니다.

LegalBench-RAG와 Zilli et al.의 연구에서 `500 characters`가 baseline 또는 균형점으로 사용되었습니다. 이 프로젝트에서는 이를 최적값으로 보지 않고, 법령 retrieval precision을 고려한 하한 후보로 봅니다. 초기 `statute` profile은 답변 생성 문맥을 조금 더 보존하기 위해 `700 characters`를 사용합니다.

### `overlap_chars`

`overlap_chars`는 긴 chunk를 나눌 때 문맥 손실을 줄이기 위한 값입니다. 법령에서는 단서, 예외, 문장 후반부의 요건이 중요할 수 있으므로 overlap을 완전히 제거하면 경계 부근 의미가 끊길 수 있습니다.

다만 overlap이 크면 같은 내용이 여러 chunk에 반복되어 검색 결과가 중복될 수 있습니다. 초기값은 `50-100 characters` 범위에서 시작하고, 이 프로젝트에서는 `80 characters`를 후보로 둡니다.

### `merge_short_article_chunks`

법령에서는 짧은 조문끼리 병합하지 않는 것이 citation 측면에서 안전합니다. 반면 사용자 업로드 문서, 메모, 일반 설명 문서에서는 짧은 문단을 병합해야 의미가 살아날 수 있습니다.

따라서 `statute`는 `False`, `user_file`이나 `memo`는 `True`를 검토합니다.

## 프로젝트 적용 방침

초기 구현은 schema를 확장하지 않고 다음 방식으로 처리합니다.

- 원문 text 안에 조문, 항, 호 표기를 유지합니다.
- chunk `content`에 citation 가능한 원문을 그대로 저장합니다.
- `metadata_json.anchor`에 조문 또는 문단 anchor를 저장합니다.
- 별도 `LegalArticle`, `LegalParagraph`, `LegalItem` 테이블은 만들지 않습니다.
- chunking service는 법률 구조를 분할 기준으로만 활용합니다.

향후 환경변수화가 필요하면 다음 후보를 검토합니다.

```text
RAG_STATUTE_CHUNK_MIN_CHARS
RAG_STATUTE_CHUNK_MAX_CHARS
RAG_STATUTE_CHUNK_OVERLAP_CHARS
RAG_STATUTE_MERGE_SHORT_ARTICLE_CHUNKS
RAG_CASE_CHUNK_MIN_CHARS
RAG_CASE_CHUNK_MAX_CHARS
RAG_CASE_CHUNK_OVERLAP_CHARS
```

단, 환경변수만 늘리면 설정 복잡도가 커집니다. MVP에서는 코드 profile로 시작하고, 실제 운영에서 문서 유형별 조정 필요가 확인되면 환경변수로 승격합니다.

## 평가 계획

설정값은 문헌만으로 확정하지 않습니다. 다음 fixture 평가를 통해 조정합니다.

- 같은 법령 문서에 대해 `max_chars=500`, `700`, `900` 비교
- 판례 문서에 대해 `max_chars=900`, `1200`, `1500` 비교
- `overlap_chars=0`, `50`, `80`, `100` 비교
- 짧은 조문 병합 여부 비교
- query별 expected chunk의 top-k 포함 여부 측정
- citation이 정확한 조문 단위로 붙는지 확인
- 같은 조문이 중복 chunk로 과도하게 노출되는지 확인
- 법령, 판례, 사용자 업로드 문서 유형별 결과 분리 기록

MVP 기준은 `docs/evaluation-plan.md`의 retrieval 평가와 citation 평가를 따릅니다.

