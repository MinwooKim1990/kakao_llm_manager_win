# LLM For Kakao Front Ver

`npm run build` 와 `npm run start` 만으로 띄우는 카카오톡 재고문의 UI입니다. Python 가상환경을 먼저 활성화해 두면 `npm install` 단계에서 현재 가상환경에 백엔드 의존성이 자동 설치됩니다.

## 빠른 시작

1. Windows에서 Python 가상환경을 활성화합니다.
2. 이 디렉토리에서 `npm install` 을 실행합니다.
3. `npm run build`
4. `npm run start`
5. 브라우저에서 `http://localhost:3000`

`postinstall` 에서 `python backend/service_cli.py bootstrap-python` 이 자동 실행됩니다.

## 전제 조건

- Windows에서 카카오톡 PC가 로그인된 상태여야 합니다.
- `python` 명령이 활성화한 가상환경 Python을 가리켜야 합니다.
- 첫 작업 실행 시 Hugging Face에서 모델이 자동 다운로드될 수 있습니다.
- 기본 모델은 `Qwen/Qwen3.5-4B` 이며 화면에서 다른 모델 ID로 바꿀 수 있습니다.
- 이미 `npm run start` 가 켜져 있으면 먼저 종료한 뒤 다시 `npm run build` 해야 합니다.
- 현재 카카오 자동화 방식은 전경 포커스와 클립보드에 의존합니다. 즉 완전한 백그라운드 자동화가 아니며, 작업 중에는 PC 사용이 불편해질 수 있습니다.

## 예제 파일

- 주문 CSV: `storage/examples/orders_example.csv`
- 다중 도매처 예제: `storage/examples/orders_multi_vendor_example.csv`
- 프론트 공개 샘플: `public/sample-orders.csv`
- 매핑 샘플: `public/sample-vendor-mapping.csv`

## 화면에서 할 수 있는 일

- 주문 CSV 업로드 및 작업용 CSV 선택
- 로컬 Python/모델/패키지 상태 확인
- 모델 ID, 타임아웃, polling 간격, follow-up 횟수 설정
- 실제 재고문의 작업 시작
- 결과 CSV, transcript, summary, 작업 로그 확인
- 백엔드가 사용자에게 남긴 assistant message 확인

## 작업 결과 위치

- 업로드 CSV: `storage/uploads`
- 결과 CSV: `storage/results`
- 대화 transcript / summary: `storage/transcripts`
- 작업 메타데이터와 로그: `storage/jobs`

## 빌드 중 `EPERM unlink .next/...` 가 날 때

이 경우는 보통 실행 중인 `npm run start` 가 이전 빌드 산출물을 점유하고 있어서 생깁니다.

1. 실행 중인 서버를 `Ctrl+C` 로 종료합니다.
2. 필요하면 `npm run clean` 으로 `.next` 를 정리합니다.
3. 다시 `npm run build`
