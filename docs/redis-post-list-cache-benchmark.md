# Redis 게시글 목록 캐시 성능 비교

## 목적

게시판에서 사용자가 가장 자주 체감하는 화면은 첫 진입 시 보이는 게시글 목록이다. 그래서 이번 테스트는 `GET /api/posts?page=1&size=10&sort=latest`를 기준으로 Redis 캐시 적용 전후 응답 시간을 비교했다.

AI/RAG/썸네일 캐시는 이미 비용 절감 효과가 명확하지만, 일반 게시판 API에 Redis를 붙였을 때 실제 체감 성능 차이가 있는지 확인하는 것이 목적이다.

## 적용 위치

- API: `GET /api/posts`
- 코드: `backend/app/api/posts.py`
- 캐시 유틸: `backend/app/services/cache.py`
- 설정:
  - `REDIS_URL`
  - `POST_LIST_CACHE_TTL_SECONDS`
- 기본 TTL: 10초

캐시 키는 다음 조건을 포함한다.

```text
page
size
q
post_type
category
sort
```

즉, 최신글 1페이지와 검색 결과, 카테고리 필터 결과는 서로 다른 캐시로 저장된다.

## 무효화 정책

다음 작업 이후에는 게시글 목록 캐시를 삭제한다.

- 글 작성
- 글 수정
- 글 삭제
- 게시글 썸네일 생성
- 게시글 썸네일 선택

조회수 증가 시에는 목록 캐시를 삭제하지 않았다. 조회수까지 매번 즉시 반영하려고 하면 글 상세 클릭마다 목록 캐시가 무효화되어 캐시 효과가 거의 사라지기 때문이다.

따라서 현재 정책은 다음과 같다.

```text
목록의 글 존재 여부, 제목, 작성자, 태그, 썸네일: 비교적 빨리 반영
목록의 조회수: 최대 TTL 10초 정도 늦게 보일 수 있음
```

## 측정 환경

- 날짜: 2026-06-16
- 서버: Docker Compose 로컬 환경
- Backend: `http://127.0.0.1:8000`
- Redis: `redis:7-alpine`
- DB: PostgreSQL + pgvector
- 데이터 규모: 게시글 50개
- 측정 방식: PowerShell에서 같은 API를 순차적으로 200회 호출
- 프론트엔드 캐시 제외: 브라우저가 아니라 백엔드 API를 직접 호출

## 측정 명령

```powershell
$url = 'http://127.0.0.1:8000/api/posts?page=1&size=10&sort=latest'
$times = New-Object System.Collections.Generic.List[double]

1..10 | ForEach-Object {
  Invoke-RestMethod -Uri $url -Method Get | Out-Null
}

$swTotal = [System.Diagnostics.Stopwatch]::StartNew()
1..200 | ForEach-Object {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  Invoke-RestMethod -Uri $url -Method Get | Out-Null
  $sw.Stop()
  $times.Add($sw.Elapsed.TotalMilliseconds)
}
$swTotal.Stop()

$sorted = $times | Sort-Object
$avg = ($times | Measure-Object -Average).Average
$p50 = $sorted[[int]([Math]::Ceiling($sorted.Count * 0.50)) - 1]
$p95 = $sorted[[int]([Math]::Ceiling($sorted.Count * 0.95)) - 1]
$rps = 200 / $swTotal.Elapsed.TotalSeconds
```

## 결과

| 상태 | 요청 수 | 평균 | p50 | p95 | 처리량 | 총 소요 |
|---|---:|---:|---:|---:|---:|---:|
| Redis 목록 캐시 적용 전 | 200 | 6.28ms | 5.98ms | 7.57ms | 156.97 req/s | 1.27s |
| Redis 목록 캐시 적용 후 | 200 | 3.61ms | 3.33ms | 4.95ms | 274.31 req/s | 0.73s |

캐시 적용 후 첫 요청은 Redis miss라서 DB를 조회하고 Redis에 저장한다. 컨테이너 재시작 직후 측정된 첫 miss는 321.52ms였지만, 이후 반복 조회는 Redis hit로 처리되었다.

Redis 키 생성도 확인했다.

```text
post_list:v1:70584d248038c014f2f5e1a2addb49baa2874236635d3119781573638f27b7c9
```

## 해석

현재 데이터가 50개뿐이라 DB 조회 자체가 이미 빠르다. 그럼에도 평균 응답 시간은 약 42.5% 줄었다.

```text
6.28ms -> 3.61ms
```

처리량은 약 74.8% 증가했다.

```text
156.97 req/s -> 274.31 req/s
```

사용자 체감으로는 단일 요청에서 극적인 차이까지는 아닐 수 있다. 하지만 여러 사용자가 동시에 메인 목록을 반복 조회하거나, 게시글 수가 늘어나고 필터/정렬 비용이 커지면 DB 쿼리를 줄이는 효과가 더 커진다.

## 사용자 체감 기준에서의 판단

게시글 목록 캐시는 사용자 체감 성능 개선 후보로 적절하다. 이유는 다음과 같다.

- 첫 화면에서 가장 자주 호출되는 API다.
- 비로그인/로그인 사용자 모두 같은 목록을 볼 수 있어 개인화 캐시 위험이 낮다.
- 짧은 TTL을 쓰면 최신성 손실을 작게 유지할 수 있다.
- 글 작성/수정/삭제 시 캐시를 지우면 "글을 썼는데 목록에 안 보임" 문제를 줄일 수 있다.

다만 지금 프로젝트에서 Redis의 우선순위는 여전히 다음 순서가 더 적절하다.

1. AI/RAG/썸네일처럼 비용이 드는 API
2. 게시글 목록 첫 페이지
3. 인기글 랭킹
4. 조회수/댓글수 집계
5. rate limit

## 한계

이번 테스트는 순차 요청 기준이다. 실제 부하 상황을 보려면 동시 요청 테스트가 추가로 필요하다.

현재 DB 데이터가 50개뿐이라 대량 데이터에서의 차이는 아직 확인하지 않았다. 게시글이 1천 개, 1만 개 이상일 때는 정렬, 필터, 태그 join 비용 때문에 차이가 더 커질 수 있다.

조회수는 목록 캐시 TTL 동안 늦게 보일 수 있다. 조회수를 실시간으로 보여주는 것이 중요해지면 목록 응답에서 조회수만 Redis counter와 합산하거나, 조회수 표시를 상세 페이지 중심으로 분리하는 설계가 필요하다.

## 결론

우리 프로젝트에서는 게시글 목록 Redis 캐시를 적용할 가치가 있다. 다만 TTL은 짧게 유지하는 것이 좋다.

추천 기본값:

```text
POST_LIST_CACHE_TTL_SECONDS=10
```

운영에서 글 작성량이 많아져 캐시가 자주 무효화되면, 목록 전체 캐시보다 인기글 랭킹이나 조회수 counter처럼 Redis 자료구조를 직접 활용하는 방식으로 넘어가는 것이 더 적절하다.
