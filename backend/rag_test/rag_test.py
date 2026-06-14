# 1. 지식 문서
documents = [
    "환불은 구매 후 14일 이내에 가능합니다.",
    "배송은 보통 2~3일 정도 걸립니다.",
    "교환은 상품 수령 후 7일 이내에 신청할 수 있습니다.",
]

# 2. 사용자 질문
question = "환불은 며칠 안에 할 수 있어?"

# 3. 검색: 질문과 가장 단어가 많이 겹치는 문서 찾기
def retrieve(query, docs):
    query_words = set(query.replace("?", "").split())

    best_doc = None
    best_score = 0

    for doc in docs:
        doc_words = set(doc.replace(".", "").split())
        score = len(query_words & doc_words)

        if score > best_score:
            best_score = score
            best_doc = doc

    return best_doc

# 4. 생성: 찾은 문서를 근거로 답변 만들기
def generate_answer(query, context):
    if context is None:
        return "관련 문서를 찾지 못했습니다."

    return f"질문: {query}\n근거 문서: {context}\n답변: {context}"

context = retrieve(question, documents)
answer = generate_answer(question, context)

print(answer)