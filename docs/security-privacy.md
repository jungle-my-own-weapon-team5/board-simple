# 보안 및 개인정보 보호

## 목적

이 문서는 게시판 + AI/RAG 기능에서 지켜야 할 보안, 개인정보, 법률 안전성 기준을 정의합니다.

법률 분쟁 사실관계는 개인정보와 민감정보를 포함할 수 있으므로, 일반 게시판보다 더 보수적으로 다룹니다.

## Secret 처리

Secret에 해당하는 값:

- `.env` 전체
- `JWT_SECRET_KEY`
- `OPENAI_API_KEY`
- `GEMINI_API_KEY`
- `ANTHROPIC_API_KEY`
- `LAW_OPEN_API_OC`
- auth cookie
- raw JWT
- database password

규칙:

- secret 값을 로그, 문서, 응답, 예외 메시지에 출력하지 않습니다.
- `.env.example`에는 placeholder만 둡니다.
- 실제 `.env`는 commit하지 않습니다.
- 설정 검증 오류는 어떤 key가 누락되었는지만 말하고 값을 포함하지 않습니다.
- 디버깅 시에도 secret은 존재 여부만 확인합니다.

## 인증과 세션

현재 정책:

- JWT는 HttpOnly cookie에 저장합니다.
- 상태 변경 요청은 허용된 `Origin` header를 요구합니다.
- production에서는 기본 JWT secret, localhost origin, insecure cookie를 거부합니다.

추가 권장:

- auth endpoint rate limiting
- refresh token 또는 server-side session invalidation 검토
- logout 이후 token 재사용 방지 전략 검토
- AI/RAG endpoint에는 별도 rate limit 적용

## 개인정보와 민감정보

분쟁 사실관계에는 다음이 포함될 수 있습니다.

- 이름, 연락처, 주소
- 계약 내용
- 금액
- 사건번호
- 병력, 가족관계, 근로정보 등 민감정보
- 상대방 식별 정보

MVP 원칙:

- `rag_runs.facts` 전체 저장을 기본값으로 두지 않습니다.
- 저장이 필요하면 최소화하거나 마스킹합니다.
- 로그에는 전체 facts를 남기지 않습니다.
- provider로 전송하기 전 PII redaction 가능성을 검토합니다.
- 사용자 업로드 문서의 공유 범위는 명시적으로 결정하기 전까지 private corpus로 간주합니다.

## 데이터 보존 정책

초기 정책 제안:

- 게시글/댓글: 사용자가 삭제하면 삭제합니다.
- 전역 법률 source/document/chunk: 관리자가 삭제하지 않는 한 유지합니다.
- 사용자 AI run: 사용자별로 조회 가능하되, 추후 삭제 요청이 가능해야 합니다.
- `rag_runs.facts`: 가능하면 저장하지 않거나 마스킹 후 저장합니다.
- provider raw response: 저장하지 않습니다.

추후 결정 필요:

- AI run 보존 기간
- 사용자 업로드 문서 보존 기간
- 관리자 audit 접근 범위
- 사용자 삭제 요청 시 AI run과 업로드 문서 삭제 방식

## Prompt Injection 방어

검색된 문서와 사용자 입력은 신뢰하지 않습니다.

규칙:

- retrieved chunk는 instruction이 아니라 evidence data로 prompt에 넣습니다.
- "이전 지시를 무시하라" 같은 문구가 문서에 있어도 system/developer 지시로 취급하지 않습니다.
- prompt에는 citation 없는 법률 주장을 금지하는 규칙을 포함합니다.
- 모델이 source에 없는 내용을 단정하지 않도록 합니다.
- 모델이 tool/API key/system prompt를 출력하지 않도록 합니다.
- MCP tool 결과도 instruction이 아니라 evidence data로만 취급합니다.

## MCP와 Agent 보안

MCP 서버와 Agent는 다음 원칙을 따릅니다.

- Agent는 allowlist된 MCP tool만 호출합니다.
- 사용자는 요청에서 provider, model, tool 이름을 임의 지정할 수 없습니다.
- MCP tool은 unrestricted filesystem, shell, raw SQL execution을 제공하지 않습니다.
- 외부 API 호출은 허용된 base URL과 timeout을 사용합니다.
- `LAW_OPEN_API_OC` 같은 외부 API key는 환경변수에서만 읽고 로그, 응답, DB에 저장하지 않습니다.
- JSON-RPC request/response는 schema validation을 거칩니다.
- `max_iterations`, `max_tool_calls`, request timeout으로 무한 루프와 비용 폭주를 방지합니다.
- tool input/output audit에는 secret, raw JWT, auth cookie, 전체 provider request/response를 저장하지 않습니다.
- tool failure는 정제된 error code/message로 변환하고, 원본 오류에 포함된 민감정보는 제거합니다.

## 법률 안전성

AI 출력은 다음을 지켜야 합니다.

- 법률 자문이 아닌 초안 보조임을 명시합니다.
- 법률적 주장에는 citation을 포함합니다.
- 근거가 부족하면 불확실성을 표시합니다.
- 실제 분쟁에는 전문가 검토가 필요하다고 안내합니다.
- 승소 가능성, 확정적 결론, 구체적 소송 전략을 단정하지 않습니다.

기본 disclaimer:

```text
이 결과는 법률정보 기반 초안 보조이며 법률 자문이 아닙니다. 실제 사건에는 구체적 사실관계와 최신 법령·판례 검토가 필요하므로 전문가 검토를 권장합니다.
```

## Logging 정책

로그에 남길 수 있는 것:

- request ID
- user ID
- AI run ID
- provider 이름
- model 이름
- retrieved chunk IDs
- MCP tool name과 redacted step status
- latency
- 실패 code

로그에 남기지 않을 것:

- secret 값
- auth cookie
- raw JWT
- 전체 분쟁 사실관계
- provider request 전문
- provider response 전문
- 내부 prompt 전문
- MCP tool raw request/response 전문

## Upload 보안

파일 업로드를 도입할 경우:

- 파일 크기 제한을 둡니다.
- 허용 확장자와 MIME type을 제한합니다.
- 업로드 content를 실행하지 않습니다.
- parser 오류를 안전하게 처리합니다.
- 원문과 정규화 text에 악성 prompt가 들어갈 수 있음을 전제로 처리합니다.

## 운영 전 체크리스트

- `APP_ENV=production`
- `JWT_SECRET_KEY` 변경
- `AUTH_COOKIE_SECURE=true`
- `FRONTEND_ORIGIN=https://...`
- `AI_RAG_ENABLED=true`인 경우 모든 환경에서 provider key, model, embedding dimension 존재 확인
- MCP allowlist와 외부 API key 존재 여부 확인. 값은 출력하지 않음
- Agent `max_iterations`, `max_tool_calls`, timeout 설정 확인
- auth/AI endpoint rate limit
- request body size limit
- structured logging redaction
- AI disclaimer 표시
- citation 포함 테스트
- prompt injection fixture 테스트
- MCP unknown tool 거부 테스트
- Agent loop guard 테스트

