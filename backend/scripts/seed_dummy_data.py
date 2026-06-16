from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.comment import Comment
from app.models.post import Post
from app.models.user import User
from app.services.tags import extract_tag_names, get_or_create_tags

DUMMY_PASSWORD = "password123"
GENERATED_MARKER = "<!-- seed:manual-community -->"

USERS = [
    {"email": "admin@example.com", "nickname": "관리자"},
    {"email": "sejo_fan@example.com", "nickname": "계유논객"},
    {"email": "sillok_reader@example.com", "nickname": "실록읽는밤"},
    {"email": "history_meme@example.com", "nickname": "조선밈장인"},
    {"email": "munjong_note@example.com", "nickname": "문종재평가단"},
    {"email": "hunmin_scholar@example.com", "nickname": "훈민정음탐정"},
    {"email": "dummy_user_001@example.com", "nickname": "야사수집가"},
    {"email": "dummy_user_002@example.com", "nickname": "왕실관찰자"},
    {"email": "dummy_user_003@example.com", "nickname": "한양구경꾼"},
    {"email": "dummy_user_004@example.com", "nickname": "실록밑줄러"},
    {"email": "dummy_user_005@example.com", "nickname": "사극검열반"},
    {"email": "dummy_user_006@example.com", "nickname": "궁궐잡담꾼"},
    {"email": "dummy_user_007@example.com", "nickname": "조선생활사"},
    {"email": "dummy_user_008@example.com", "nickname": "붕당알못"},
    {"email": "dummy_user_009@example.com", "nickname": "경연출석부"},
    {"email": "dummy_user_010@example.com", "nickname": "왕평가보류"},
    {"email": "dummy_user_011@example.com", "nickname": "고증은중요"},
    {"email": "dummy_user_012@example.com", "nickname": "별별실록"},
    {"email": "dummy_user_013@example.com", "nickname": "댓글만읽음"},
    {"email": "dummy_user_014@example.com", "nickname": "인물관계도"},
    {"email": "dummy_user_015@example.com", "nickname": "오늘도태종"},
]

BASE_POSTS = [
    {
        "email": "sejo_fan@example.com",
        "title": "세조의 왕위 찬탈, 조선 안정의 선택이었을까?",
        "post_type": "토론",
        "category": "왕과 권력",
        "view_count": 128,
        "content": (
            "계유정난을 보면 세조를 단순한 악역으로만 보기도 어렵고, 그렇다고 명분이 충분했다고 보기도 어려운 것 같습니다.\n\n"
            "결과적으로 조선 왕권이 안정됐다는 평가가 있다면, 그 결과가 단종 폐위를 정당화할 수 있을까요?\n\n"
            "#세조 #단종 #계유정난 #왕권"
        ),
        "comments": [
            ("sillok_reader@example.com", "결과와 명분을 분리해서 봐야 할 것 같습니다."),
            ("history_meme@example.com", "댓글 싸움 나기 좋은 주제네요. 그래도 단종 쪽 명분이 너무 강해 보여요."),
            ("munjong_note@example.com", "문종이 오래 살았다면 이 구도가 완전히 달라졌을지도 궁금합니다."),
        ],
    },
    {
        "email": "sillok_reader@example.com",
        "title": "실록에서 이상한 기록 발견함: 세종도 과로 문제 있었나?",
        "post_type": "발견",
        "category": "사료 발견",
        "view_count": 76,
        "content": (
            "세종 시기 기록을 읽다 보면 업무량이 너무 많았던 흔적이 자주 보입니다.\n\n"
            "요즘 기준으로 보면 과로 이슈처럼 읽히는 장면도 있는데, 이걸 현대식 노동 관점으로 봐도 될까요?\n\n"
            "#세종 #실록 #생활사"
        ),
        "comments": [
            ("hunmin_scholar@example.com", "현대 개념을 바로 대입하긴 어렵지만 비교 관점은 재밌습니다."),
        ],
    },
    {
        "email": "munjong_note@example.com",
        "title": "문종은 짧은 재위 때문에 과소평가된 왕일까?",
        "post_type": "질문",
        "category": "인물 열전",
        "view_count": 92,
        "content": (
            "문종은 항상 세종의 뒤를 이은 짧은 재위의 왕으로만 기억되는 느낌입니다.\n\n"
            "실제로는 제도 운영 능력이 꽤 있었다는 이야기도 있던데, 문종을 독립적인 군주로 다시 평가할 수 있을까요?\n\n"
            "#문종 #세종 #왕평가"
        ),
        "comments": [
            ("sejo_fan@example.com", "문종 평가가 약한 건 재위 기간보다 사후 정치 구도가 더 큰 것 같아요."),
        ],
    },
    {
        "email": "hunmin_scholar@example.com",
        "title": "훈민정음 창제는 애민정신만으로 설명할 수 있을까?",
        "post_type": "사료 해석 요청",
        "category": "생활사와 문화",
        "view_count": 111,
        "content": (
            "훈민정음은 보통 애민정신으로 설명되지만, 행정과 지식 보급의 측면도 컸을 것 같습니다.\n\n"
            "문자 창제를 정치적 프로젝트로 보는 해석은 어디까지 설득력이 있을까요?\n\n"
            "#훈민정음 #세종 #문화"
        ),
        "comments": [
            ("sillok_reader@example.com", "행정 문서와 교육 확산까지 같이 보면 정치적 의미도 있다고 봅니다."),
        ],
    },
]

MANUAL_COMMUNITY_POSTS = [
    {
        "email": "dummy_user_001@example.com",
        "title": "양녕대군 고양이 사건, 너무 사소해서 더 기억남",
        "post_type": "가벼운 썰",
        "category": "왕실 TMI",
        "view_count": 184,
        "content": (
            "양녕대군이 남의 금빛 고양이를 탐냈다는 이야기를 보는데, 큰 정치 사건보다 이런 장면이 더 오래 기억납니다.\n\n"
            "폐세자 이미지가 워낙 강해서 그런지, 그냥 철없는 왕족의 일화인지 성격을 보여주는 단서인지 애매하네요.\n\n"
            "#양녕대군 #고양이 #왕실TMI\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_002@example.com", "금빛 고양이라는 표현부터 이미 너무 강합니다."),
            ("history_meme@example.com", "태종 입장에서는 진짜 머리 아팠을 듯."),
            ("sillok_reader@example.com", "이런 짧은 기록은 맥락 없이 보면 과장되기 쉬워서 원문 확인이 필요합니다."),
            ("dummy_user_013@example.com", "고양이 때문에 폐세자 된 건 아니겠지만 이미지에는 확실히 남네요."),
        ],
    },
    {
        "email": "dummy_user_007@example.com",
        "title": "조선 왕들도 단 음식 좋아했는지 궁금함",
        "post_type": "질문",
        "category": "생활사와 문화",
        "view_count": 97,
        "content": (
            "왕들의 식단이나 병환 기록을 읽다 보면 정치 이야기보다 먹는 이야기가 더 궁금해질 때가 있습니다.\n\n"
            "세종은 건강 이야기가 자주 붙고, 영조는 장수 이미지가 강한데 실제로 뭘 즐겨 먹었는지 정리된 자료가 있을까요?\n\n"
            "#음식 #세종 #생활사\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_004@example.com", "수라상 메뉴보다 의관 기록 쪽을 보면 단서가 있을 것 같습니다."),
            ("dummy_user_012@example.com", "왕의 식성으로 인물 보는 글 재밌네요."),
        ],
    },
    {
        "email": "dummy_user_005@example.com",
        "title": "사극에서 배운 연산군이랑 실록 연산군은 얼마나 다를까",
        "post_type": "사료 해석 요청",
        "category": "오늘의 떡밥",
        "view_count": 221,
        "content": (
            "연산군은 사극 이미지가 너무 강해서 기록을 읽기 전부터 머릿속에 장면이 생깁니다.\n\n"
            "폭군이라는 큰 틀은 이해되는데, 구체적인 일화 하나하나가 후대 이미지 때문에 더 세게 읽히는 건 아닌지 궁금합니다.\n\n"
            "#연산군 #사극 #실록\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_011@example.com", "사극으로 먼저 알면 기록을 읽을 때 이미 표정이 상상돼서 문제입니다."),
            ("history_meme@example.com", "연산군은 제목만 써도 조회수 나오는 인물."),
            ("dummy_user_010@example.com", "그래도 기록 자체가 워낙 세긴 해서 재평가도 조심해야 할 듯합니다."),
        ],
    },
    {
        "email": "dummy_user_009@example.com",
        "title": "성종 경연 기록 보면 왕도 계속 시험 보는 느낌",
        "post_type": "발견",
        "category": "생활사와 문화",
        "view_count": 63,
        "content": (
            "경연 기록을 보다 보면 신하들이 왕에게 계속 공부하자고 말하는 장면이 반복됩니다.\n\n"
            "왕이 최고 권력자인데도 공부 압박을 받는 구조가 흥미롭습니다. 성종은 이걸 꽤 성실하게 받아들인 왕으로 보이기도 하고요.\n\n"
            "#성종 #경연 #공부\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_013@example.com", "왕도 출석 체크 당하는 느낌이라 웃깁니다."),
            ("hunmin_scholar@example.com", "경연은 단순 공부가 아니라 통치 체계 일부라서 더 중요합니다."),
            ("dummy_user_008@example.com", "이런 걸 보면 조선 정치가 생각보다 토론 구조가 있긴 했네요."),
        ],
    },
    {
        "email": "dummy_user_003@example.com",
        "title": "궁궐 안 소문은 진짜 빨랐을 것 같지 않나요",
        "post_type": "가벼운 썰",
        "category": "생활사와 문화",
        "view_count": 142,
        "content": (
            "실록을 보면 누가 누구에게 말했다, 누가 들었다, 이런 흐름이 은근 자주 나옵니다.\n\n"
            "궁궐이 엄청 격식 있는 공간처럼 보이지만 사람 모인 곳이라 소문도 빠르고 눈치도 엄청 봤을 것 같습니다.\n\n"
            "#궁궐 #소문 #왕실\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_006@example.com", "궁궐 단체방 있었으면 하루 종일 불났을 듯."),
            ("dummy_user_004@example.com", "실록에도 말이 전해지는 경로가 남는 게 재밌습니다."),
            ("dummy_user_014@example.com", "인물관계도 그리면 소문 경로도 보일 것 같아요."),
            ("dummy_user_002@example.com", "엄숙한 공간인데 동시에 직장 같았을 것 같습니다."),
            ("dummy_user_013@example.com", "이런 생활사 글 좋습니다."),
        ],
    },
    {
        "email": "dummy_user_010@example.com",
        "title": "광해군 재평가, 어느 순간 너무 반대로 간 느낌도 있음",
        "post_type": "토론",
        "category": "인물 재평가",
        "view_count": 238,
        "content": (
            "광해군은 예전에는 폐위된 왕 이미지가 강했는데, 요즘은 중립외교와 실리 외교 쪽으로 꽤 높게 평가되는 것 같습니다.\n\n"
            "기존 평가가 단순했던 것도 맞지만, 재평가가 또 다른 단순화가 되는 건 아닌지 궁금합니다.\n\n"
            "#광해군 #재평가 #외교\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("sejo_fan@example.com", "정치 결과와 외교 판단을 따로 봐야 할 듯합니다."),
            ("dummy_user_005@example.com", "대중문화가 광해군 이미지를 많이 바꾼 건 확실합니다."),
            ("dummy_user_008@example.com", "저는 재평가 필요하지만 과열도 있다고 봅니다."),
            ("sillok_reader@example.com", "시기별 기록을 나눠서 봐야 균형이 맞을 것 같습니다."),
            ("dummy_user_013@example.com", "댓글만 봐도 이미 갈리네요."),
            ("dummy_user_011@example.com", "고증보다 인상비평이 앞서는 순간이 많습니다."),
        ],
    },
    {
        "email": "dummy_user_014@example.com",
        "title": "문종이 오래 살았으면 세조 이야기는 아예 달라졌을까",
        "post_type": "질문",
        "category": "왕과 권력",
        "view_count": 205,
        "content": (
            "문종이 조금만 더 오래 재위했다면 단종 즉위기의 불안정성이 줄었을까요?\n\n"
            "세조의 선택이나 계유정난을 이야기할 때 늘 문종의 짧은 재위가 배경처럼 따라붙는데, 실제로 얼마나 큰 변수였는지 궁금합니다.\n\n"
            "#문종 #세조 #단종\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("munjong_note@example.com", "제가 늘 하는 말이 이겁니다. 문종 재위 기간은 너무 큰 변수예요."),
            ("sejo_fan@example.com", "그래도 권력 욕망 자체가 사라졌을지는 모르겠습니다."),
            ("dummy_user_010@example.com", "가정이라 조심스럽지만 정치 구도는 확실히 달랐을 듯합니다."),
            ("dummy_user_013@example.com", "문종 오래 살았으면 조선 전기 드라마 장르가 바뀜."),
        ],
    },
    {
        "email": "dummy_user_012@example.com",
        "title": "정조 편지 말투 은근 매움",
        "post_type": "발견",
        "category": "인물 열전",
        "view_count": 174,
        "content": (
            "정조는 개혁 군주 이미지가 강한데 편지나 지시문을 보면 감정선이 꽤 직접적으로 느껴질 때가 있습니다.\n\n"
            "왕도 결국 사람이라 답답하면 말투가 날카로워지는구나 싶어서 갑자기 가까워 보였습니다.\n\n"
            "#정조 #편지 #말투\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_009@example.com", "정조는 공부 잘하는데 말도 센 학생회장 느낌이 있습니다."),
            ("dummy_user_004@example.com", "편지 자료는 인물 성격 볼 때 진짜 좋습니다."),
            ("dummy_user_005@example.com", "사극 대사보다 실제 문장이 더 강할 때가 있죠."),
        ],
    },
    {
        "email": "dummy_user_008@example.com",
        "title": "붕당 정치 설명 들을 때마다 머리가 아픈 이유",
        "post_type": "질문",
        "category": "붕당과 정치",
        "view_count": 88,
        "content": (
            "동인 서인 남인 북인까지는 외웠는데, 어느 순간부터 사건마다 입장이 바뀌는 것처럼 느껴져서 따라가기 어렵습니다.\n\n"
            "붕당을 단순 당파 싸움이 아니라 공론 정치로 봐야 한다는 말도 이해는 되는데, 입문자용 설명이 필요합니다.\n\n"
            "#붕당 #사림 #정치\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_004@example.com", "사건 순서보다 쟁점 중심으로 보면 조금 낫습니다."),
            ("sillok_reader@example.com", "초기 붕당과 후기 세도정치를 섞어서 배우면 더 헷갈립니다."),
            ("dummy_user_013@example.com", "저도 이름 외우다가 포기했습니다."),
            ("dummy_user_009@example.com", "경연과 언론 구조까지 같이 보면 덜 뜬금없습니다."),
        ],
    },
    {
        "email": "dummy_user_006@example.com",
        "title": "왕의 잔소리 기록만 모아도 재밌을 듯",
        "post_type": "가벼운 썰",
        "category": "사료 발견",
        "view_count": 119,
        "content": (
            "신하들에게 술 줄이라, 일 똑바로 하라, 공부하라 하는 기록을 보면 왕의 말이 거의 회사 공지처럼 느껴질 때가 있습니다.\n\n"
            "근엄한 왕명 말고 잔소리 모음으로 보면 조선 정치가 갑자기 현실적으로 보입니다.\n\n"
            "#왕 #잔소리 #실록\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("history_meme@example.com", "조선판 공지사항 모음집 있으면 봅니다."),
            ("dummy_user_003@example.com", "신하들도 읽씹하고 싶었을까요."),
            ("dummy_user_007@example.com", "생활사 관점으로 보면 이런 기록이 더 귀합니다."),
        ],
    },
    {
        "email": "dummy_user_011@example.com",
        "title": "사극에서 본 장면이 실록에 나오면 반갑긴 한데",
        "post_type": "사료 해석 요청",
        "category": "사료 발견",
        "view_count": 151,
        "content": (
            "드라마로 먼저 본 장면이 실제 기록과 연결될 때 반갑지만, 동시에 각색이 머릿속에 너무 강하게 남습니다.\n\n"
            "실록 원문을 읽을 때도 배우 얼굴이 떠오르면 해석에 방해가 되는 걸까요?\n\n"
            "#사극 #실록 #고증\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_005@example.com", "고증 확인하다가 드라마 연출의 힘을 더 느끼는 경우가 많습니다."),
            ("dummy_user_012@example.com", "그래도 사극 덕분에 찾아보게 되는 것도 사실입니다."),
            ("sillok_reader@example.com", "각색과 사료를 분리해서 보는 습관이 필요합니다."),
            ("dummy_user_013@example.com", "배우 얼굴 떠오르는 거 너무 공감합니다."),
        ],
    },
    {
        "email": "dummy_user_015@example.com",
        "title": "태종은 좋은 아버지였을까 무서운 정치가였을까",
        "post_type": "토론",
        "category": "왕과 권력",
        "view_count": 203,
        "content": (
            "태종은 조선 왕권을 다지는 데 큰 역할을 했지만, 가족사를 보면 정치가 너무 앞서는 인물처럼 보입니다.\n\n"
            "양녕대군을 폐하고 충녕대군을 세운 선택도 아버지와 군주의 판단이 겹쳐 있어서 간단히 평가하기 어렵습니다.\n\n"
            "#태종 #양녕대군 #세종\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_002@example.com", "왕실 가족사는 가족극이면서 정치극이라 더 복잡합니다."),
            ("sejo_fan@example.com", "왕권 관점에서는 냉정함이 장점이기도 합니다."),
            ("dummy_user_010@example.com", "좋은 아버지 기준으로 보면 점수 주기 어렵죠."),
            ("dummy_user_014@example.com", "이방원 관계도는 항상 피곤합니다."),
            ("dummy_user_013@example.com", "태종 글은 늘 댓글이 진지해짐."),
        ],
    },
    {
        "email": "dummy_user_002@example.com",
        "title": "왕실 취미 생활만 모아도 캐릭터가 보일 것 같음",
        "post_type": "질문",
        "category": "생활사와 문화",
        "view_count": 69,
        "content": (
            "활쏘기, 서화, 독서, 음악 같은 취미를 보면 정치사와 다른 결의 인물상이 보일 것 같습니다.\n\n"
            "왕이나 왕족의 취미를 정리한 자료가 있으면 추천 부탁드립니다.\n\n"
            "#취미 #왕실 #생활사\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_007@example.com", "생활사 자료는 이런 식으로 들어가면 재밌습니다."),
            ("dummy_user_009@example.com", "경연 기록과 취미 기록을 같이 보면 왕 성향이 보일 수도 있겠네요."),
        ],
    },
    {
        "email": "dummy_user_004@example.com",
        "title": "허준은 의학자 이미지가 너무 강해서 관료였다는 걸 자꾸 잊음",
        "post_type": "발견",
        "category": "생활사와 문화",
        "view_count": 104,
        "content": (
            "허준을 생각하면 바로 동의보감과 의학자 이미지가 떠오르지만, 실제로는 관료 체계 안에서 움직인 인물이기도 합니다.\n\n"
            "업적 하나가 너무 유명하면 다른 면이 거의 안 보이는 사례 같습니다.\n\n"
            "#허준 #동의보감 #의학\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_011@example.com", "드라마 이미지도 한몫했다고 봅니다."),
            ("dummy_user_007@example.com", "의학사와 관료제를 같이 봐야겠네요."),
            ("dummy_user_013@example.com", "허준은 이름부터 이미 장르가 고정된 느낌."),
        ],
    },
    {
        "email": "dummy_user_013@example.com",
        "title": "장희빈 이야기는 왜 늘 드라마 장면부터 떠오를까",
        "post_type": "오늘의 떡밥",
        "category": "오늘의 떡밥",
        "view_count": 190,
        "content": (
            "장희빈은 실록보다 드라마 이미지가 먼저 떠오르는 대표 인물 같습니다.\n\n"
            "숙종, 인현왕후, 장희빈 구도는 너무 강해서 실제 기록을 읽어도 이미 서사가 만들어져 있는 느낌입니다.\n\n"
            "#장희빈 #숙종 #사극\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_005@example.com", "이건 배우 이미지가 너무 큽니다."),
            ("dummy_user_010@example.com", "악녀 서사로만 읽는 건 조심해야 할 듯합니다."),
            ("history_meme@example.com", "장희빈은 이름만 나와도 댓글창 자동 재생."),
            ("sillok_reader@example.com", "기록과 후대 서사를 분리해야 합니다."),
        ],
    },
    {
        "email": "dummy_user_003@example.com",
        "title": "과거 시험 준비생들 멘탈 괜찮았을까",
        "post_type": "질문",
        "category": "생활사와 문화",
        "view_count": 82,
        "content": (
            "과거 시험을 준비하다가 몇 번씩 낙방하는 사람들 이야기를 보면 현대 수험생과 겹쳐 보입니다.\n\n"
            "당시 유생들도 자기들끼리 하소연하고, 시험 제도 욕하고, 합격자 부러워했을까요?\n\n"
            "#과거시험 #유생 #공부\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_009@example.com", "공부 기록은 시대가 달라도 마음이 비슷할 것 같습니다."),
            ("dummy_user_013@example.com", "조선판 수험 커뮤니티 있었으면 난리였을 듯."),
            ("dummy_user_004@example.com", "상소문에도 억울함이 묻어나는 경우가 있죠."),
            ("dummy_user_007@example.com", "교육사 쪽으로 보면 재밌는 주제입니다."),
        ],
    },
    {
        "email": "dummy_user_008@example.com",
        "title": "숙종 환국 정치는 머리로는 이해해도 마음은 못 따라감",
        "post_type": "토론",
        "category": "붕당과 정치",
        "view_count": 177,
        "content": (
            "숙종의 환국 정치를 보면 왕이 주도권을 잡은 것 같기도 하고, 조정을 계속 흔든 것 같기도 합니다.\n\n"
            "능력 있는 정치 운영인지 위험한 균형 깨기인지 판단이 어렵습니다.\n\n"
            "#숙종 #환국 #붕당\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_008@example.com", "붕당 알못 입장에서는 여기서부터 난이도가 올라갑니다."),
            ("sejo_fan@example.com", "왕권 강화로 보면 이해되는 면이 있습니다."),
            ("sillok_reader@example.com", "사건별로 어느 당파가 어떤 입장이었는지 봐야 합니다."),
            ("dummy_user_013@example.com", "숙종 파트는 댓글 보기만 해도 어렵습니다."),
        ],
    },
    {
        "email": "dummy_user_012@example.com",
        "title": "신숙주를 배신자 한 단어로 끝내기엔 너무 복잡함",
        "post_type": "토론",
        "category": "인물 재평가",
        "view_count": 166,
        "content": (
            "신숙주는 집현전과 세조 집권 사이에서 평가가 크게 갈리는 인물입니다.\n\n"
            "배신자라는 말이 강하게 남아 있지만, 외교와 학문 쪽 업적까지 같이 보면 한 단어로 닫히지 않는 사람 같습니다.\n\n"
            "#신숙주 #세조 #집현전\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("hunmin_scholar@example.com", "학문적 역할과 정치적 선택을 분리해서 봐야 합니다."),
            ("dummy_user_010@example.com", "그래도 그 선택이 너무 커서 이미지가 바뀌기 어렵습니다."),
            ("dummy_user_004@example.com", "기록을 나눠 읽어야 하는 대표 사례네요."),
            ("history_meme@example.com", "한 줄 별명이 사람 평가를 너무 오래 끌고 갑니다."),
        ],
    },
    {
        "email": "dummy_user_006@example.com",
        "title": "조선 왕 이름보다 별명이 더 잘 기억나는 문제",
        "post_type": "가벼운 썰",
        "category": "오늘의 떡밥",
        "view_count": 134,
        "content": (
            "정식 이름이나 묘호보다 별명, 이미지, 사극 대사로 먼저 기억나는 인물들이 많습니다.\n\n"
            "역사 공부가 어느 순간 캐릭터 관계도 외우기처럼 느껴질 때가 있어요.\n\n"
            "#조선 #별명 #인물\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("history_meme@example.com", "킬방원 같은 별명은 너무 강합니다."),
            ("dummy_user_014@example.com", "관계도 없으면 조선 전기부터 힘듭니다."),
            ("dummy_user_013@example.com", "별명으로 외우면 시험에는 위험하지만 기억은 잘 납니다."),
        ],
    },
    {
        "email": "dummy_user_005@example.com",
        "title": "김종서는 무장인가 정치가인가",
        "post_type": "질문",
        "category": "왕과 권력",
        "view_count": 121,
        "content": (
            "김종서는 북방 개척 이미지도 있고, 단종 시기 권력 구도의 핵심 인물 이미지도 있습니다.\n\n"
            "무장으로 기억해야 할지 정치가로 봐야 할지, 아니면 둘 다 봐야 하는지 궁금합니다.\n\n"
            "#김종서 #단종 #세조\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("sejo_fan@example.com", "계유정난 맥락에서는 정치가로 볼 수밖에 없습니다."),
            ("dummy_user_010@example.com", "북방 이미지가 강해서 더 입체적인 인물 같아요."),
            ("sillok_reader@example.com", "시기별 행적을 나눠 보면 답이 조금 보일 것 같습니다."),
        ],
    },
    {
        "email": "dummy_user_007@example.com",
        "title": "왕의 병환 기록은 읽을수록 인간적임",
        "post_type": "발견",
        "category": "생활사와 문화",
        "view_count": 101,
        "content": (
            "왕의 병환 기록은 정치적으로도 중요하지만, 읽다 보면 그냥 아픈 사람의 일상처럼 느껴지는 순간이 있습니다.\n\n"
            "약을 먹고, 쉬어야 한다는 말을 듣고, 그래도 일을 보는 장면들이 반복되면 왕이라는 자리가 꽤 혹독해 보입니다.\n\n"
            "#병환 #왕실 #생활사\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_004@example.com", "의관 기록은 생활사 자료로도 중요해 보입니다."),
            ("dummy_user_012@example.com", "왕도 아프면 일하기 싫었겠죠."),
            ("munjong_note@example.com", "문종 사례가 특히 떠오릅니다."),
            ("dummy_user_013@example.com", "갑자기 현실 직장 생각나네요."),
        ],
    },
    {
        "email": "dummy_user_011@example.com",
        "title": "정도전은 조선 설계자라는 말이 너무 멋있어서 손해도 봄",
        "post_type": "토론",
        "category": "개혁과 제도",
        "view_count": 159,
        "content": (
            "정도전을 조선 설계자라고 부르면 멋있지만, 그 표현 때문에 실제 정치적 갈등이 너무 깔끔하게 정리되는 느낌도 있습니다.\n\n"
            "이방원과의 대립도 선명한 서사로 소비되지만, 제도 구상과 권력 투쟁이 같이 있었다고 봐야 할 것 같습니다.\n\n"
            "#정도전 #조선건국 #이방원\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_015@example.com", "이방원 쪽에서 보면 또 완전히 다르게 보입니다."),
            ("dummy_user_004@example.com", "제도사와 정치사를 같이 봐야 하는 인물입니다."),
            ("history_meme@example.com", "조선 설계자라는 별칭은 진짜 너무 강합니다."),
            ("dummy_user_010@example.com", "멋진 별명일수록 해석을 고정시키는 문제가 있네요."),
        ],
    },
    {
        "email": "dummy_user_009@example.com",
        "title": "영조 탕평책은 성공한 갈등 해결이었나 관리였나",
        "post_type": "사료 해석 요청",
        "category": "붕당과 정치",
        "view_count": 147,
        "content": (
            "영조의 탕평책은 교과서에서는 갈등을 줄이려는 정책으로 배우지만, 실제로는 갈등을 없앴다기보다 관리한 것에 가까운지 궁금합니다.\n\n"
            "탕평이라는 말이 너무 좋은 말이라 실제 효과를 더 좋게 느끼는 건 아닌가 싶습니다.\n\n"
            "#영조 #탕평 #붕당\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_008@example.com", "붕당을 없앴다기보다 왕 중심으로 재배치한 느낌도 있습니다."),
            ("sillok_reader@example.com", "정책 이름과 실제 운영을 나눠 봐야겠습니다."),
            ("dummy_user_010@example.com", "사도세자 사건까지 같이 떠올라서 더 복잡합니다."),
        ],
    },
    {
        "email": "dummy_user_001@example.com",
        "title": "고종 기록은 읽을 때마다 마음이 복잡함",
        "post_type": "토론",
        "category": "전쟁과 외교",
        "view_count": 196,
        "content": (
            "고종은 시대 자체가 너무 어려워서 개인 능력만으로 평가하기가 조심스럽습니다.\n\n"
            "그렇다고 모든 책임을 시대 탓으로 돌릴 수도 없어서, 읽을수록 판단이 어려운 왕입니다.\n\n"
            "#고종 #대한제국 #근대\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_010@example.com", "근대사는 결과를 알고 읽어서 더 냉정해지기 어렵습니다."),
            ("dummy_user_011@example.com", "이 시기는 고증보다 감정이 먼저 올라오는 것 같아요."),
            ("sillok_reader@example.com", "자료 성격도 조선 전기와 다르게 봐야 합니다."),
            ("dummy_user_013@example.com", "이건 댓글도 조심스러워지네요."),
        ],
    },
    {
        "email": "dummy_user_003@example.com",
        "title": "순종은 늘 마지막 왕이라는 말에 가려지는 느낌",
        "post_type": "질문",
        "category": "인물 열전",
        "view_count": 78,
        "content": (
            "순종은 조선의 마지막 왕, 대한제국의 마지막 황제라는 설명이 너무 강해서 개인으로는 거의 보이지 않는 것 같습니다.\n\n"
            "실제 인물 순종을 보려면 어떤 자료부터 읽어야 할까요?\n\n"
            "#순종 #대한제국 #인물\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_004@example.com", "마지막이라는 수식어가 너무 커서 사람 자체가 가려집니다."),
            ("dummy_user_010@example.com", "근대 정치 상황을 같이 봐야 할 것 같습니다."),
        ],
    },
    {
        "email": "dummy_user_004@example.com",
        "title": "황희는 청백리 이미지가 너무 강해서 오히려 낯설다",
        "post_type": "인물 재평가",
        "category": "인물 재평가",
        "view_count": 116,
        "content": (
            "황희 하면 청백리 이미지가 먼저 떠오르는데, 오래 정치한 인물인 만큼 실제 기록은 훨씬 복잡할 것 같습니다.\n\n"
            "좋은 이미지가 너무 강하면 오히려 현실 정치인으로서의 면이 잘 안 보이는 듯합니다.\n\n"
            "#황희 #세종 #청백리\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_010@example.com", "좋은 이미지도 일종의 고정관념이 될 수 있네요."),
            ("sillok_reader@example.com", "장기 재임 인물은 사건별로 나눠 봐야 합니다."),
            ("dummy_user_013@example.com", "청백리 한 단어로 끝내기엔 너무 오래 일했습니다."),
        ],
    },
    {
        "email": "dummy_user_006@example.com",
        "title": "조선에도 오늘의 운세 같은 문화가 있었을까",
        "post_type": "질문",
        "category": "생활사와 문화",
        "view_count": 73,
        "content": (
            "택일, 점, 길흉 같은 기록을 보면 조선 사람들도 일상에서 꽤 많이 따졌을 것 같습니다.\n\n"
            "국가 의례와 개인 생활 사이에서 이런 믿음이 어떻게 작동했는지 궁금합니다.\n\n"
            "#생활사 #길흉 #조선\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_007@example.com", "생활사로 보면 진짜 재밌는 주제입니다."),
            ("dummy_user_004@example.com", "국가 기록에 남은 길흉 표현부터 보면 좋을 듯합니다."),
        ],
    },
    {
        "email": "dummy_user_005@example.com",
        "title": "인현왕후는 왜 늘 조용한 피해자 이미지로만 남을까",
        "post_type": "사료 해석 요청",
        "category": "인물 열전",
        "view_count": 138,
        "content": (
            "장희빈 이야기를 하다 보면 인현왕후는 상대적으로 조용한 피해자 이미지로 고정되는 느낌입니다.\n\n"
            "실제 정치적 위치나 주변 세력까지 같이 보면 더 입체적으로 볼 수 있을까요?\n\n"
            "#인현왕후 #장희빈 #숙종\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_005@example.com", "사극 구도가 이미 너무 강합니다."),
            ("dummy_user_010@example.com", "피해자 이미지가 맞더라도 정치적 맥락은 따로 봐야겠네요."),
            ("sillok_reader@example.com", "왕비 관련 기록은 주변 세력까지 같이 봐야 합니다."),
        ],
    },
    {
        "email": "dummy_user_009@example.com",
        "title": "왕이 공부 안 하면 신하들이 진짜 답답했을 듯",
        "post_type": "가벼운 썰",
        "category": "생활사와 문화",
        "view_count": 91,
        "content": (
            "경연을 빼먹거나 공부에 소극적인 왕을 보면 신하들이 얼마나 답답했을지 상상됩니다.\n\n"
            "권력자는 왕인데 공부하라고 계속 말해야 하는 신하들도 쉽지 않았을 것 같습니다.\n\n"
            "#경연 #왕 #공부\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_009@example.com", "경연 출석부 닉값으로 말하면 이건 중요합니다."),
            ("history_meme@example.com", "조선판 담임 선생님과 학생회장 구도네요."),
            ("dummy_user_013@example.com", "공부하라는 말은 시대를 안 가립니다."),
        ],
    },
    {
        "email": "dummy_user_012@example.com",
        "title": "조선 시대에도 유행어 같은 게 있었을까",
        "post_type": "질문",
        "category": "생활사와 문화",
        "view_count": 67,
        "content": (
            "문체나 표현이 시대마다 다르다면, 당시 사람들이 자주 쓰던 말투나 유행 표현도 있었을 것 같습니다.\n\n"
            "공식 기록에서는 잘 안 보이겠지만 편지나 야담 쪽에는 흔적이 있을까요?\n\n"
            "#말투 #문화 #조선\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_012@example.com", "야담 자료에 이런 느낌이 남아 있을 것 같습니다."),
            ("hunmin_scholar@example.com", "문체 변화와 문자 생활을 같이 보면 흥미롭겠습니다."),
        ],
    },
    {
        "email": "dummy_user_014@example.com",
        "title": "왕자의 난은 이름부터 너무 드라마 제목 같음",
        "post_type": "오늘의 떡밥",
        "category": "왕과 권력",
        "view_count": 165,
        "content": (
            "왕자의 난은 이름만 들어도 이미 가족극, 정치극, 액션이 다 들어간 느낌입니다.\n\n"
            "그만큼 사건 구조가 강렬해서 이방원 이미지가 너무 선명하게 굳어진 것 같기도 합니다.\n\n"
            "#왕자의난 #이방원 #태종\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_015@example.com", "오늘도 태종이네요."),
            ("dummy_user_014@example.com", "관계도 없이 보면 바로 길 잃습니다."),
            ("history_meme@example.com", "제목 자체가 이미 흥행 보장입니다."),
            ("sejo_fan@example.com", "왕권 형성 과정으로 보면 무겁게 봐야 합니다."),
        ],
    },
    {
        "email": "dummy_user_007@example.com",
        "title": "조선 사람들은 여행 가면 뭐가 제일 힘들었을까",
        "post_type": "질문",
        "category": "생활사와 문화",
        "view_count": 59,
        "content": (
            "왕의 행차 기록 말고 일반 사람들이 이동할 때는 숙박, 음식, 길 상태가 제일 문제였을 것 같습니다.\n\n"
            "교통사나 여행 기록을 보면 생활감이 확 살아날 것 같아요.\n\n"
            "#여행 #교통 #생활사\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_003@example.com", "한양 밖으로 나가는 것부터 큰일이었을 듯합니다."),
            ("dummy_user_007@example.com", "생활사 자료로 길과 숙박은 진짜 중요합니다."),
        ],
    },
    {
        "email": "dummy_user_002@example.com",
        "title": "왕비들의 정치적 존재감은 생각보다 큰 것 같음",
        "post_type": "토론",
        "category": "왕과 권력",
        "view_count": 143,
        "content": (
            "왕비를 단순히 왕의 배우자로만 보면 조선 정치의 중요한 축을 놓치는 것 같습니다.\n\n"
            "왕실 혼인, 대비, 외척, 후계 구도까지 연결되면 왕비의 존재감이 꽤 큽니다.\n\n"
            "#왕비 #외척 #왕실\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_002@example.com", "왕실을 관찰하면 왕비와 대비를 빼놓을 수 없습니다."),
            ("dummy_user_014@example.com", "외척까지 넣으면 관계도가 갑자기 복잡해집니다."),
            ("sillok_reader@example.com", "후계 구도와 함께 봐야 할 주제입니다."),
        ],
    },
    {
        "email": "dummy_user_011@example.com",
        "title": "고증 틀린 사극을 어디까지 봐줄 수 있을까",
        "post_type": "토론",
        "category": "오늘의 떡밥",
        "view_count": 210,
        "content": (
            "사극은 재미도 중요하지만, 고증이 너무 틀리면 몰입이 깨집니다.\n\n"
            "다만 모든 걸 정확히 맞추면 드라마가 안 될 수도 있어서 어디까지 허용해야 하는지 매번 헷갈립니다.\n\n"
            "#사극 #고증 #역사콘텐츠\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_011@example.com", "핵심 사건을 바꾸는 건 어렵고, 의상 정도는 장르에 따라 봐줄 수 있습니다."),
            ("history_meme@example.com", "재밌으면 보긴 보는데 검색은 따로 하게 됩니다."),
            ("sillok_reader@example.com", "고증과 각색을 구분해서 표시해주면 좋겠습니다."),
            ("dummy_user_005@example.com", "사극 이미지가 실제 역사처럼 굳는 게 문제입니다."),
        ],
    },
    {
        "email": "dummy_user_010@example.com",
        "title": "세종은 너무 완벽한 이미지라 오히려 질문하기 어려움",
        "post_type": "토론",
        "category": "인물 재평가",
        "view_count": 188,
        "content": (
            "세종은 성군 이미지가 너무 강해서 다른 각도의 질문을 하면 괜히 조심스러워집니다.\n\n"
            "하지만 건강, 가족, 제도 운영, 신하들과의 관계까지 보면 훨씬 입체적인 인물일 것 같습니다.\n\n"
            "#세종 #성군 #인물재평가\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("hunmin_scholar@example.com", "세종을 낮추자는 게 아니라 더 입체적으로 보자는 뜻이면 좋습니다."),
            ("dummy_user_010@example.com", "완벽한 이미지는 질문을 막는 효과가 있습니다."),
            ("dummy_user_009@example.com", "경연 기록을 보면 세종도 계속 논쟁 속에 있었습니다."),
        ],
    },
    {
        "email": "dummy_user_013@example.com",
        "title": "역사 글은 댓글이 본문보다 재밌을 때가 있음",
        "post_type": "가벼운 썰",
        "category": "오늘의 떡밥",
        "view_count": 122,
        "content": (
            "역사 커뮤니티 글은 본문도 재밌지만 댓글에서 갑자기 사료 링크, 반박, 사극 얘기, 밈이 한꺼번에 나올 때가 제일 재밌습니다.\n\n"
            "이런 흐름 때문에 게시판형 서비스가 잘 맞는 것 같아요.\n\n"
            "#커뮤니티 #댓글 #역사덕후\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_013@example.com", "닉값합니다. 댓글이 제일 재밌습니다."),
            ("dummy_user_004@example.com", "좋은 댓글은 거의 보조 사료입니다."),
            ("history_meme@example.com", "댓글에서 밈이 생기는 순간이 진짜입니다."),
        ],
    },
    {
        "email": "dummy_user_004@example.com",
        "title": "짧은 실록 기사는 근거로 쓰기 애매한 듯",
        "post_type": "사료 해석 요청",
        "category": "사료 발견",
        "view_count": 99,
        "content": (
            "임금이 어디에 갔다, 돌아왔다 정도의 짧은 기사는 사실 확인에는 좋지만 해석 근거로 쓰기에는 약한 것 같습니다.\n\n"
            "RAG에서 이런 자료가 citation으로 뜨면 사용자가 실망할 수도 있을 것 같아요.\n\n"
            "#실록 #RAG #사료\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("sillok_reader@example.com", "짧은 기사는 고유명사 검색에는 의미가 있지만 해석에는 약합니다."),
            ("dummy_user_004@example.com", "검색 결과에서 weak 표시가 있으면 좋겠습니다."),
            ("dummy_user_013@example.com", "사용자 입장에서는 내용이 너무 짧으면 당황할 듯합니다."),
        ],
    },
    {
        "email": "dummy_user_015@example.com",
        "title": "이방원은 밈이 너무 강해서 실제 정치가 잘 안 보임",
        "post_type": "토론",
        "category": "왕과 권력",
        "view_count": 231,
        "content": (
            "이방원은 킬방원 같은 밈이 너무 강해서, 실제 제도 정비와 왕권 강화 과정이 오히려 덜 보일 때가 있습니다.\n\n"
            "밈은 입문에는 좋은데 거기서 멈추면 인물 평가가 납작해지는 것 같습니다.\n\n"
            "#이방원 #태종 #왕권\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_015@example.com", "태종은 밈으로 시작해도 결국 정치 구조로 가야 합니다."),
            ("history_meme@example.com", "밈 담당으로서 찔립니다."),
            ("sejo_fan@example.com", "왕권 강화의 맥락을 같이 봐야 합니다."),
            ("dummy_user_010@example.com", "강한 이미지일수록 반대쪽 자료를 봐야겠네요."),
        ],
    },
    {
        "email": "dummy_user_001@example.com",
        "title": "왕실 동물 일화 더 없나요",
        "post_type": "질문",
        "category": "왕실 TMI",
        "view_count": 87,
        "content": (
            "양녕대군 고양이 이야기를 보고 나니 왕실 동물 관련 일화가 더 궁금해졌습니다.\n\n"
            "말, 매, 개, 고양이 같은 동물이 기록에 어떻게 등장하는지 모아보면 꽤 재밌을 것 같습니다.\n\n"
            "#왕실TMI #동물 #실록\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_001@example.com", "저는 고양이부터 찾아보겠습니다."),
            ("dummy_user_007@example.com", "동물사는 생활사랑도 연결됩니다."),
            ("dummy_user_012@example.com", "매사냥 기록도 많을 것 같습니다."),
        ],
    },
    {
        "email": "dummy_user_006@example.com",
        "title": "궁궐 사람들도 퇴근하고 싶었겠지",
        "post_type": "가벼운 썰",
        "category": "생활사와 문화",
        "view_count": 112,
        "content": (
            "궁궐 기록을 읽다 보면 너무 격식 있는 공간처럼 느껴지지만, 그 안에서 일하는 사람들은 결국 직장인이었을 것 같습니다.\n\n"
            "밤늦게 부름받고, 행사 준비하고, 눈치 보는 일도 많았겠죠.\n\n"
            "#궁궐 #직장인 #생활사\n"
            f"{GENERATED_MARKER}"
        ),
        "comments": [
            ("dummy_user_006@example.com", "궁궐도 결국 거대한 직장이라는 말 공감합니다."),
            ("dummy_user_013@example.com", "퇴근 못 하는 사관 생각하면 갑자기 슬픕니다."),
            ("dummy_user_003@example.com", "한양구경꾼 입장에서는 밖에서 보는 것과 안에서 일하는 건 다르겠죠."),
        ],
    },
]


def local_database_url() -> str:
    raw_url = os.environ.get("DATABASE_URL") or get_settings().database_url
    return raw_url.replace("@db:5432/", "@localhost:5432/")


def make_search_summary(item: dict[str, object]) -> str:
    return (
        f"제목: {item['title']}\n"
        f"글 유형: {item['post_type']}\n"
        f"카테고리: {item['category']}\n"
        f"본문 요약: {str(item['content']).replace(chr(10), ' ')[:700]}"
    )


def get_or_create_user(db: Session, email: str, nickname: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is not None:
        return user

    user = User(
        email=email,
        nickname=nickname,
        password_hash=hash_password(DUMMY_PASSWORD),
    )
    db.add(user)
    db.flush()
    return user


def upsert_post(db: Session, users: dict[str, User], item: dict[str, object]) -> Post:
    post = db.scalar(select(Post).where(Post.title == item["title"]))
    if post is None:
        post = Post(title=str(item["title"]), author_id=users[str(item["email"])].id)
        db.add(post)
    post.author_id = users[str(item["email"])].id
    post.content = str(item["content"])
    post.post_type = str(item["post_type"])
    post.category = str(item["category"])
    post.view_count = int(item["view_count"])
    post.comment_count = 0
    post.ai_search_summary = make_search_summary(item)
    post.tags = get_or_create_tags(db, extract_tag_names(str(item["content"])))
    db.flush()
    return post


def seed() -> None:
    engine = create_engine(local_database_url(), pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as db:
        db.execute(delete(Comment).where(Comment.post_id.in_(select(Post.id).where(Post.content.contains("seed:")))))
        db.execute(delete(Post).where(Post.content.contains("seed:")))
        db.flush()

        users = {item["email"]: get_or_create_user(db, item["email"], item["nickname"]) for item in USERS}
        all_posts = BASE_POSTS + MANUAL_COMMUNITY_POSTS

        total_comments = 0
        for item in all_posts:
            post = upsert_post(db, users, item)
            db.execute(delete(Comment).where(Comment.post_id == post.id))
            post.comment_count = 0
            for email, content in item["comments"]:
                db.add(Comment(post_id=post.id, author_id=users[email].id, content=content))
                post.comment_count += 1
                total_comments += 1

        db.commit()
        print(f"Seeded {len(USERS)} users, {len(all_posts)} posts, {total_comments} comments.")
        print(f"Manual community posts: {len(MANUAL_COMMUNITY_POSTS)}")
        print(f"Dummy user password: {DUMMY_PASSWORD}")


if __name__ == "__main__":
    seed()
