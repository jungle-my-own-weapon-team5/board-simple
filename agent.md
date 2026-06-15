# FitLog Agent Notes

1. Main goal: build a weight-loss strategy adjustment agent.
2. Do not make image RAG part of the main flow yet.
3. Main flow: goal -> meal log -> daily report -> strategy advice.
4. Existing board features should remain unless explicitly changed.
5. FitLog must be a separate backend/frontend domain.
6. Users must only access their own FitLog data.
7. First version uses manual food nutrition input.
8. Meal image upload is optional.
9. Canvas crop is optional and single-rectangle only.
10. Store image files on disk, not in DB.
11. Store image paths and crop coordinates in DB.
12. Image search test must return hardcoded candidates.
13. Do not implement real ResNet inference yet.
14. Do not implement projection layer training yet.
15. Do not implement pgvector image search yet.
16. Strategy Agent uses text RAG, not image RAG.
17. Text RAG starts with keyword scoring.
18. OpenAI model names must come from env settings.
19. Never hardcode model names inside services.
20. Strategy output must include today and tomorrow strategy.
21. Responses must avoid medical diagnosis or treatment claims.
22. No extreme weight-loss recommendations.
23. Missing goal should produce a goal setup prompt.
24. Missing meals should produce a meal logging prompt.
25. Meal totals must be calculated server-side.
26. Updating meal foods must recalculate totals.
27. Successful strategy responses should be persisted.
28. Backend tests should mock OpenAI calls.
29. Frontend must pass `npm run build`.
30. Backend should pass `pytest` when dependencies are installed.
