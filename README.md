# 🐋 하이퍼리퀴드 고래 포지션 추적기

하이퍼리퀴드는 온체인 DEX라 **모든 계정의 포지션이 공개**됩니다.
진입가 · 청산가 · 미실현손익 · 레버리지가 추정이 아니라 실제 값입니다.
(바이낸스는 개별 포지션을 공개하지 않아 이런 추적이 불가능합니다)

- `collector.py` — 30분마다 스냅샷을 수집해 `data/`에 누적
- `app.py` — Streamlit 대시보드
- `.github/workflows/snapshot.yml` — GitHub Actions 무료 cron

## 무료 배포 — 15분이면 끝납니다

### 1단계. GitHub 저장소 만들기

**공개(Public) 저장소**로 만드세요. 공개면 Actions 실행 시간이 무제한입니다.
(비공개는 월 2,000분 제한 — 30분 주기면 월 약 1,400분이라 빠듯합니다)

```bash
cd hl-whale-tracker
git init && git add . && git commit -m "init"
git branch -M main
git remote add origin https://github.com/<사용자명>/hl-whale-tracker.git
git push -u origin main
```

### 2단계. Actions 권한 켜기

저장소 → **Settings → Actions → General → Workflow permissions**
→ **Read and write permissions** 선택 → Save

이걸 안 하면 수집 결과를 커밋하지 못합니다.

### 3단계. 첫 실행

**Actions** 탭 → `whale-snapshot` → **Run workflow** 버튼

30분마다 자동 실행되지만, 첫 스냅샷은 수동으로 돌려 확인하세요.
`data/agg_BTC.csv` 가 생기면 성공입니다.

> GitHub의 예약 실행은 혼잡 시 몇 분 지연될 수 있고, **60일간 저장소에
> 활동이 없으면 자동 중단**됩니다. 가끔 커밋하거나 수동 실행하면 유지됩니다.

### 4단계. 대시보드 배포

[share.streamlit.io](https://share.streamlit.io) → GitHub 로그인 → **New app**

| 항목 | 값 |
|---|---|
| Repository | `<사용자명>/hl-whale-tracker` |
| Branch | `main` |
| Main file path | `app.py` |

Deploy를 누르면 `https://<앱이름>.streamlit.app` 주소가 나옵니다.

## 설정

`.github/workflows/snapshot.yml` 의 `env:` 에서 조정합니다.

| 변수 | 기본 | 설명 |
|---|---|---|
| `COINS` | `BTC,ETH,SOL` | 추적 종목 (232개 지원) |
| `MIN_VALUE` | `5e6` | 계정 자산 하한 ($5M → 약 660개) |
| `MAX_ACCOUNTS` | `800` | 조회 상한 |
| `WORKERS` | `6` | 동시 요청 수 (너무 올리면 429) |

주기는 `cron: "*/30 * * * *"` 를 바꾸세요. 최소 5분이지만 **30분 이상**을 권합니다.

## 저장되는 데이터

| 파일 | 형태 | 내용 |
|---|---|---|
| `data/agg_{COIN}.csv` | append | 스냅샷별 롱/숏 명목가, 가중평균 진입가, OI, 펀딩 |
| `data/positions_{COIN}.csv` | 덮어쓰기 | 현재 개별 고래 포지션 |
| `data/events_{COIN}.csv` | append | $100K 이상 포지션 변화 (OPEN/CLOSE/ADD/REDUCE) |

집계 20,000행, 이벤트 50,000행을 넘으면 오래된 것부터 자동 정리됩니다.
30분 주기 기준 집계는 약 1년치가 유지됩니다.

## 데이터 동기화

`data/` 는 GitHub Actions 가 5분마다 커밋하는 영역이라 **원격이 기준**입니다.
로컬에서 `collector.py` 를 돌리면 이 폴더가 수정되어 `git pull` 이 막힙니다.

```bash
./sync.sh          # 로컬 변경 백업·폐기 후 최신 데이터로 맞춤
```

로컬에서 수집기를 시험할 때는 저장 위치를 따로 지정하세요.

```bash
DATA_DIR=/tmp/hl python collector.py     # git 추적 폴더를 건드리지 않음
```

## 로컬 실행

```bash
pip install -r requirements.txt
python collector.py                       # 스냅샷 1회
streamlit run app.py                      # 대시보드
```

## 주의

- 온체인 공개 데이터입니다. 매매 신호가 아니라 **상황 인식 도구**입니다
- 바이낸스 고래와는 다른 집단입니다 (하이퍼리퀴드 BTC 미결제약정은 바이낸스의 약 1/3)
- 투자 조언이 아닙니다
