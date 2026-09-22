# tama4u-tools

## 개요
다마고치 컬러(P's/4U/iD/iDL) 커스텀 다운로드 아이템 RE + 에디터.
- tama4u/ : 파이썬 코어(container, sprites, outing, editor 등)
- web/    : JS 미러(core.js, api.js) → docs/index.html 웹빌드
- 데스크톱 에디터: `python3 -m tama4u edit -p 8477`

## 핵심 사실 (재도출 금지)
- CPU = Epson S1C33 (6502/unSP 아님). 상세는 메모리 참조.
- 외출지 리사이즈 해법·기종별 파라미터 → [[outing-engine-sprite-lock]]
- 아이템 포맷 해독 상태 → [[t4u-item-format]]

## 작업 규칙
- 실기 검증은 사용자가 수행. 버그 리포트 시 재현 환경·증상 범위 먼저 확인.
- 검증 완료 단위로 커밋. 큰 파일은 통째로 읽지 말 것.
- Python 수정 시 web/ JS 미러도 동기화(바이트 일치 유지).

## 미검증/보류
- iD/iDL 실기 미검증(코드는 정합). Plus Color 계열(0x00C00000) 파일 미확보.
