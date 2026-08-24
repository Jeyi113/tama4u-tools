# 스크린샷

README에서 참조하는 이미지 5장. 다시 찍어야 할 때 아래 순서로 재현한다.

```bash
python3 -m tama4u edit          # http://127.0.0.1:8477
```

브라우저 창은 **1280×720 이상**이어야 2열 레이아웃이 유지된다.
촬영은 `Cmd+Shift+4` → 스페이스바 → 창 클릭, 또는 `screencapture -iw docs/01-editor.png`.

| 파일명 | 장면 | 여는 파일 |
|---|---|---|
| `01-editor.png` | 아이템 편집 기본 화면 | `4u-download-pack/meals/cup-noodles-meal.jpg` |
| `02-character.png` | 캐릭터 내장 액세서리 합성 14쌍 + 좌표 편집 | `characters/fk00002/fk00002_1-kururutchi.jpg` → **↳ 옷장 패킷** 선택 |
| `03-id-accessory.png` | iD 액세서리 (7프레임 구성, 비활성 필드) | `TMGC-ID-download-pack/.../FlowerHairBand_LMv.JPG` |
| `04-nested.png` | 중첩 패킷 — 외출지 + 보상 아이템 4개 | `4u-download-pack/outings/chubu-outing.jpg` |
| `05-id-version-likes.png` | 펌웨어 버전 변환 · 기종 변환 · 호불호 11칸 | 위 iD 파일에서 좌측 하단으로 스크롤 |
