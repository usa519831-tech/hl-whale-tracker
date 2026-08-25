#!/usr/bin/env bash
# GitHub Actions 가 수집한 최신 데이터로 안전하게 동기화한다.
#
# data/ 는 원격(Actions)이 계속 커밋하는 영역이라 원격이 authoritative 다.
# 로컬에서 collector.py 를 돌리면 이 폴더가 수정되어 pull 이 막히므로,
# 로컬 변경은 백업 후 폐기한다.
set -euo pipefail
cd "$(dirname "$0")"

git fetch -q origin

if ! git diff --quiet -- data/ 2>/dev/null; then
  bk="/tmp/hl_data_backup_$(date +%Y%m%d_%H%M%S)"
  cp -r data "$bk"
  echo "로컬 data/ 변경을 폐기합니다 (백업: $bk)"
  git checkout -- data/
fi

git pull --rebase --autostash origin main
echo "동기화 완료 → $(git log -1 --format='%h  %s')"
echo "집계 $(( $(wc -l < data/agg_BTC.csv) - 1 ))행 · 최신 $(tail -1 data/agg_BTC.csv | cut -d, -f1)"
