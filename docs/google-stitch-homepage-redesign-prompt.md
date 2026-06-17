# Google Stitch Homepage Redesign Prompt

## Reference Input Guide

레퍼런스는 아래 형태 중 아무거나 사용할 수 있다.

- 이미지 파일: 원하는 웹/앱 스크린샷, 무드보드, 컬러 팔레트 이미지
- URL: 비슷한 느낌의 서비스, 랜딩 페이지, 커뮤니티, 미디어 사이트
- 텍스트: "전통적이지만 촌스럽지 않게", "더 화려하게", "네이버 블로그보다 현대적으로" 같은 감성 설명
- Stitch 생성 결과: 마음에 드는 시안 캡처 또는 내보낸 코드

Google Stitch에서 조작할 때는 프롬프트 입력창에 아래 프롬프트를 넣고, 레퍼런스 업로드 기능이 보이면 이미지를 같이 첨부하면 된다.

## Homepage Prompt

Design a polished, dynamic Korean web community homepage for a Next.js historical discussion board named "역사 덕담".

The product is a Korean-language community where users share Joseon dynasty history stories, questions, source-based debates, AI-assisted writing drafts, and RAG-backed historical citations. Keep all existing product functions visible, but redesign the UI to feel more premium, lively, and culturally Korean without becoming old-fashioned.

Core screen requirements:

1. Sticky top navigation
   - Brand name: "역사 덕담"
   - Navigation actions: Login, Register, Write
   - If admin state is shown, include AI Playground, 토론거리 관리, Thumbnail Lab
   - Use compact icon buttons with Korean labels where appropriate

2. Homepage hero area
   - Main title: "역사 덕담"
   - Supporting copy: "조선시대 역사 썰과 토론이 모이는 게시판"
   - Include a prominent search bar for title search
   - Include a primary "글쓰기" action and a secondary "오늘의 토론 보기" action
   - Add subtle Korean visual cues: hanji paper texture, ink brush accent, palace roof line silhouette, dancheong-inspired accent colors, archival document feel
   - The style should be contemporary and digital, not museum-like or dusty

3. "오늘의 토론거리" section
   - Show three AI-recommended discussion cards
   - Each card includes: source badge, title, summary, bold discussion question, reason, citation links, tags, and "초안으로 글쓰기" button
   - Make the three cards visually rich and differentiated
   - Add dynamic hover effects: card lift, soft glow, citation row highlight
   - Include a small badge: "날짜별 AI 추천"

4. Filter controls
   - Post type segmented buttons: 전체, 질문, 토론, 발견, 사료 해석 요청, 가벼운 썰
   - Category select: 왕과 권력, 붕당과 정치, 전쟁과 외교, 인물 열전, 생활사와 문화, 사건 사고, 사료 발견, 오늘의 떡밥
   - Sort select: 최신순, 댓글 많은 순, AI 근거 있는 글
   - Reset filter action
   - Make controls compact and easy to scan

5. Post list
   - Show a vertical feed of post cards
   - Each post card includes optional thumbnail, post type badge, category badge, AI evidence status, title, author nickname, comment count, view count, date, and tags
   - Use stronger hierarchy than the current plain card list
   - Cards should feel like modern Korean editorial/community content
   - Add hover movement and thumbnail zoom effect

6. Floating AI chat widget
   - Bottom-right floating circular button
   - Visual identity should match the redesigned page
   - When open, it is a resizable assistant panel named "AI 챗봇"
   - It helps with historical writing and source checking

Visual direction:

- Korean contemporary editorial style
- Warm ivory base, deep ink text, refined crimson, jade green, muted indigo, and brass/gold accents
- Avoid a one-note beige or brown palette
- Use elegant contrast, readable typography, and sophisticated spacing
- Use Korean typography sensibility: strong title weight, clean body text, compact metadata
- Use subtle motion ideas: page entrance fade, card lift, shimmer on AI badges, soft animated ink underline, search focus glow
- Add a refined Korean "발/죽렴/대발" interaction motif:
  - Use the idea of a thin bamboo blind or summer shade hung across a window or daecheong floor.
  - When opening panels, expanding cards, focusing search, clicking filters, or opening the AI chat widget, show a very subtle blind-like reveal: fine vertical bamboo lines sliding down/up, a soft shadow sweep, or a translucent woven screen passing over the surface.
  - Keep it elegant and minimal, like a premium editorial micro-interaction. It must not look like a cartoon curtain, stage curtain, heavy wood shutter, or cheap decorative pattern.
  - The motif should appear only during interaction states or as a faint texture layer in selected surfaces, not as a busy full-page background.
  - Use thin lines, low opacity, warm natural shadow, and smooth 180-280ms motion.
  - It should feel like filtered summer sunlight through a Korean bamboo blind, not a literal illustration.
- Desktop first, but include responsive mobile layout
- No marketing landing page; this must be the actual usable board homepage

Output expectations:

- Create a complete homepage UI mockup
- Include desktop and mobile responsive states if supported
- Preserve Korean labels exactly
- Do not remove any existing product functionality
- Make the design implementable with React, Tailwind CSS, lucide-react icons, and shadcn-style components
