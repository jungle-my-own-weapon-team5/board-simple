# RAG 검색용 텍스트 정규화 트러블슈팅

작성일: 2026-06-16

## 문제

신편 한국사와 실록 국역 seed에는 현대 한국어 문장 안에 한자 표기가 섞여 있다.

예:

```text
왜변이 일어난 후 조선정부는 실정막부와 大內·小貳殿을 제외하고 대마도에 대해서는 일체의 통교를 단절하였다.
그러나 명종 2년(1547) 丁未約條를 체결하고 교역 재개를 허락하였다.
```

사용자는 보통 `정미약조`, `대내씨`, `소이씨`, `병자호란`, `집현전`처럼 현대 한국어로 검색한다. 그런데 seed 문서에 `丁未約條`, `大內`, `小貳殿`, `丙子胡亂`, `集賢殿`처럼 한자만 있으면 키워드 검색과 embedding 검색 모두에서 질의와 문서 사이의 표현 차이가 커진다.

## 기존 구조

기존 RAG 저장 흐름은 다음과 같았다.

```text
seed Markdown 본문
→ 원문 섹션 제거
→ 문단 단위 chunk
→ rag_chunks.content에 그대로 저장
→ rag_chunks.content를 embedding
→ rag_chunks.embedding_json 저장
```

즉, embedding 전에 검색 친화 정규화가 거의 없었다.

## 변경 방향

새 컬럼은 만들지 않는다.

```text
rag_chunks.content
= 검색과 citation 표시를 함께 담당하는 RAG 친화 텍스트

rag_chunks.embedding_json
= rag_chunks.content를 embedding한 벡터
```

정규화는 DB에 chunk를 저장하기 전에 수행한다.

```text
seed Markdown 본문
→ 원문 섹션 제거
→ 한자 용어에 한글 별칭 보강
→ 각주 번호/HTML entity/불필요한 공백 정리
→ chunk
→ rag_chunks.content 저장
→ embedding
```

예:

```text
大內 → 대내씨(大內)
小貳殿 → 소이전/소이씨(小貳殿)
丁未約條 → 정미약조(丁未約條)
丙子胡亂 → 병자호란(丙子胡亂)
集賢殿 → 집현전(集賢殿)
```

## 구현 위치

정규화 함수:

```text
backend/app/services/ai_runtime.py
```

핵심 함수:

```py
_normalize_for_rag_content()
_add_hanja_aliases()
_add_hanja_alias()
```

적용 위치:

```py
_parse_seed_markdown()
```

`_parse_seed_markdown()`에서 seed Markdown 본문을 읽은 뒤, `rag_chunks.content`로 들어가기 전에 정규화한다.

## 비용 안전장치

정규화가 적용되면 기존 chunk content와 달라지는 문서가 생기고, 해당 chunk의 기존 embedding은 재사용할 수 없다.

이 상태에서 RAG 검색 API가 누락 embedding을 자동으로 전부 생성하면 예상치 못한 OpenAI 비용이 발생할 수 있다. 그래서 검색 API에서는 더 이상 누락 chunk 전체를 자동 embedding하지 않는다.

현재 정책:

```text
RAG 검색 API
→ 기존 embedding이 있으면 vector search
→ vector 결과가 없으면 keyword fallback
→ missing embedding 전체 자동 생성은 하지 않음
```

embedding은 명시적으로 아래 스크립트를 실행할 때만 생성한다.

```powershell
cd backend
python scripts/embed_rag_chunks.py --limit 200 --batch-size 100
```

전체 재임베딩은 비용이 발생할 수 있으므로 `--limit`로 작은 단위부터 진행한다.

## 정규화 전/후 비교

대상 seed 상태:

```text
전체 seed Markdown: 3,153개
신편 한국사 overview seed: 954개
정규화 전 예상 chunk 수: 7,677개
정규화 후 예상 chunk 수: 7,609개
정규화로 content가 바뀌는 문서: 1,210개
```

chunk 수가 줄어든 이유는 주로 각주 번호, HTML entity, 불필요한 공백이 정리되기 때문이다.

## 한자 별칭 커버리지

| 한자 | 주입 별칭 | 한자 포함 문서 | 기존 한글 동시 포함 | 정규화 후 한글 포함 |
|---|---:|---:|---:|---:|
| 訓民正音 | 훈민정음 | 17 | 12 | 17 |
| 癸酉靖難 | 계유정난 | 7 | 3 | 7 |
| 丁未約條 | 정미약조 | 4 | 2 | 4 |
| 壬辰倭亂 | 임진왜란 | 3 | 2 | 3 |
| 丙子胡亂 | 병자호란 | 2 | 0 | 2 |
| 科田法 | 과전법 | 11 | 5 | 11 |
| 經國大典 | 경국대전 | 78 | 41 | 78 |
| 集賢殿 | 집현전 | 22 | 10 | 22 |
| 對馬島 | 대마도 | 27 | 25 | 27 |
| 大內 | 대내씨 | 14 | 2 | 14 |
| 小貳殿 | 소이전/소이씨 | 1 | 1 | 1 |
| 事大交隣 | 사대교린 | 2 | 1 | 2 |
| 崇儒抑佛 | 숭유억불 | 2 | 0 | 2 |
| 弘文館 | 홍문관 | 14 | 9 | 14 |
| 奎章閣 | 규장각 | 2 | 0 | 2 |
| 蕩平策 | 탕평책 | 1 | 0 | 1 |
| 大同法 | 대동법 | 5 | 2 | 5 |

해석:

```text
정규화 전에는 한자만 있고 한글 검색어가 없는 문서가 많았다.
정규화 후에는 alias 사전에 있는 한자 용어가 모두 한글 검색어를 포함한다.
```

## 대표 질의 비교

아래 비교는 OpenAI 재임베딩을 돌리지 않은 오프라인 키워드 매칭 기준이다. 실제 embedding 검색 품질은 정규화된 chunk를 재임베딩한 뒤 다시 평가해야 한다.

| 질의 | 정규화 전 | 정규화 후 | 해석 |
|---|---:|---:|---|
| 정미약조 대마도 통교 재개 | 4점, `(2) 사량진왜변과 정미약조` | 4점, `(2) 조일국교의 재개` | 이미 한글 표기가 일부 있어 전/후 모두 잡히지만, 정규화 후 조일 국교 재개 맥락 문서도 강해짐 |
| 대내씨 소이씨 대마도 교역 | 3점, `(4) 삼포왜란 이후의 왜변` | 4점, `(2) 사량진왜변과 정미약조` | `大內`, `小貳殿`에 한글 별칭이 붙으면서 질의어 매칭이 개선됨 |
| 병자호란 조선 후기 정치 | 4점, `(3) 조선백자의 변천` | 4점, `(3) 조선백자의 변천` | 단순 키워드 매칭의 한계. `조선/후기` 같은 일반어가 강해서 주제와 다른 문서가 올라올 수 있음 |
| 집현전 세종 유교정치 | 3점, `개요` | 3점, `개요` | 별칭 보강은 되지만, 개괄 문서의 큰 덩어리 구조 때문에 세부 항목보다 개요가 강하게 잡힘 |
| 경국대전 조선 통치 체제 | 4점, `(2) 세조대의 정치` | 4점, `(2) 세조대의 정치` | 이미 관련 한글/한자 표현이 많아 큰 변화는 적음 |

## 200개 재임베딩 실제 비교

실행 명령:

```powershell
cd backend
python scripts/embed_rag_chunks.py --limit 200 --batch-size 100
```

실행 전 DB 상태:

```text
documents=3752 chunks=5429 embedded=5429 missing=0
```

실행 후 DB 상태:

```text
documents=4706 chunks=10332 embedded=5033 missing=5299
history_overview_documents=954 sillok_documents=3745
```

문서와 chunk 수가 증가한 이유는 정규화 때문만이 아니다. 기존 `_find_existing_seed_document()`가 `sillok.history.go.kr/id/` 형태의 실록 URL만 고유 source로 보고, `contents.history.go.kr` 신편 한국사 문서는 제목으로만 기존 문서를 찾고 있었다. 신편 한국사는 `개요`, `(1) ...`, `(2) ...`처럼 중복 제목이 많아서 서로 다른 문서가 같은 제목으로 합쳐질 수 있었다. 이를 `contents.history.go.kr/front/nh/view.do?levelId=` URL도 고유 source로 보도록 고쳤다.

즉 이번 실행은 두 가지를 함께 반영했다.

```text
1. chunk.content 정규화
2. 신편 한국사 source_url 기준 문서 분리
```

### Vector-only 결과

아래 결과는 fallback 없이 `embedding_json`이 있는 chunk만 대상으로 cosine similarity cutoff `0.45`를 적용한 결과다.

| 질의 | 재임베딩 전 | 200개 재임베딩 후 | 해석 |
|---|---|---|---|
| 정미약조 대마도 통교 재개 | 결과 없음 | 결과 없음 | 관련 chunk는 생겼지만 아직 미임베딩 상태 |
| 대내씨 소이씨 대마도 교역 | 결과 없음 | 결과 없음 | alias 정규화는 됐지만 관련 chunk가 아직 미임베딩 상태 |
| 병자호란 조선 후기 정치 | 0.456, `현종실록: 병조가 궁성 밖의 호위를 맡았던 두 국 군대를 철수케 할 것을 청하다` | 동일 | 낮은 점수의 실록 chunk만 cutoff를 넘음. 주제 적합도는 낮음 |
| 집현전 세종 유교정치 | 결과 없음 | 0.577, `6) 유교적 민본정치의 전개` / 0.511, `5) 유교적 국정운영체제의 성립` / 0.508, `개요` | 200개 안에 관련 overview chunk가 포함되어 의미 있는 개선 확인 |
| 경국대전 조선 통치 체제 | 결과 없음 | 결과 없음 | 일부 경국대전 chunk는 embedding이 있지만 cutoff를 넘는 vector 결과가 없음 |

`정미약조` 관련 chunk 상태:

```text
chunk_id=6297 missing (2) 조일국교의 재개
chunk_id=6333 missing (2) 사량진왜변과 정미약조
chunk_id=6334 missing (2) 사량진왜변과 정미약조
chunk_id=9899 missing (4) 삼포왜란 이후의 왜변
```

이번 `--limit 200` 실행은 `last_chunk_id=5873`까지 처리했다. 따라서 `정미약조` 관련 chunk가 아직 vector 검색에 들어가지 못한 것은 정상이다.

### 검색 API fallback 결과

현재 검색 API는 vector 결과가 없으면 keyword fallback을 사용한다. 정규화된 `content`는 embedding이 없어도 keyword fallback에는 바로 반영된다.

| 질의 | fallback 상위 결과 | 해석 |
|---|---|---|
| 정미약조 대마도 통교 재개 | `(2) 조일국교의 재개`, `(2) 사량진왜변과 정미약조`, `(4) 삼포왜란 이후의 왜변` | 정규화와 source_url 분리 효과가 바로 보임 |
| 대내씨 소이씨 대마도 교역 | `(2) 사량진왜변과 정미약조`, `(4) 삼포왜란 이후의 왜변`, `(2) 해외무역` | `大內`, `小貳殿` 계열 표현 보강 효과가 있음 |
| 경국대전 조선 통치 체제 | `(2) 세조대의 정치`, `개요`, `1) 관료체제의 특징` | keyword fallback은 관련 문서를 찾지만, 일반어 영향으로 정렬 품질은 아직 거칠다 |

## 200개 비교 결론

200개 재임베딩만으로도 `집현전 세종 유교정치`는 vector 검색 품질 개선이 확인됐다. 반면 `정미약조`, `대내씨/소이씨`는 정규화된 관련 chunk가 DB에는 존재하지만 아직 embedding되지 않아 vector 결과에는 나타나지 않았다.

따라서 이번 결과는 “정규화가 효과 없음”이 아니라 “정규화된 chunk 중 일부만 embedding되어 평가 범위가 아직 좁음”으로 봐야 한다.

다음 비교를 더 정확히 하려면 다음 중 하나가 필요하다.

```text
1. --limit을 늘려 chunk_id 6334 이후까지 포함되게 재임베딩
2. 대표 평가 질의와 연결된 chunk를 우선 재임베딩하는 targeted embedding 스크립트 추가
3. overview/sillok/curated source_type별로 검색 결과를 분리해 평가
```

## 결론

이번 정규화는 다음 문제에는 효과가 있다.

```text
한자로만 적힌 역사 용어가 현대 한국어 질의에 안 잡히는 문제
각주 번호와 HTML entity가 검색 텍스트에 섞이는 문제
RAG citation에 검색 친화성이 낮은 표현이 그대로 노출되는 문제
```

하지만 이 문제까지 해결하지는 못한다.

```text
너무 일반적인 키워드가 관련 없는 문서를 끌어올리는 문제
개괄 문서와 실록 문서가 같은 top_k에서 경쟁하는 문제
긴 개요 문서가 세부 항목보다 강하게 잡히는 문제
embedding 재생성 전에는 vector 검색 품질이 바뀌지 않는 문제
```

## 다음 작업

1. `source_type` 기반 검색 분리

```text
overview RAG
sillok RAG
curated RAG
```

개괄 문서와 실록 문서를 같은 top_k에서 경쟁시키지 말고, Agent가 먼저 overview를 보고 필요할 때 sillok을 보게 한다.

2. 정규화된 chunk 소량 재임베딩

```powershell
cd backend
python scripts/embed_rag_chunks.py --limit 200 --batch-size 100
```

3. 대표 질의 평가셋 작성

예:

```text
정미약조 대마도 통교 재개
대내씨 소이씨 대마도 교역
병자호란 조선 후기 정치
집현전 세종 유교정치
경국대전 조선 통치 체제
```

각 질의마다 기대 source/title을 정하고 `Recall@3`, `weak_evidence`, `source_type mix`를 기록한다.

4. Alias 사전 확장

현재 alias 사전은 시작점이다. 검색 로그에서 자주 실패하는 한자 용어를 추가해야 한다.

예:

```text
小貳殿 → 소이전/소이씨
大內 → 대내씨
室町幕府 → 무로마치 막부
中宗反正 → 중종반정
仁祖反正 → 인조반정
```

## 운영 주의

정규화 코드가 배포된 뒤 seed 동기화가 실행되면 일부 기존 chunk가 삭제/재생성되고 `embedding_json`이 비게 된다. 이때 검색 API가 자동 대량 임베딩을 하지 않도록 수정했다.

재임베딩은 반드시 작은 단위로 실행한다.

```powershell
python scripts/embed_rag_chunks.py --limit 200 --batch-size 100
```

결과를 확인한 뒤 점진적으로 `--limit`를 늘린다.
