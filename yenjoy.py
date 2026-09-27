"""
yen-joy.net(日刊プロスポーツ新聞社)の選手データから、代謝判定に必要な
  前期得点 / 今期級班・前期級班・前々期級班 / 引退フラグ
を取って yenjoy.csv に保存する。

  python yenjoy.py            … 未取得 or 取得から7日より古い選手だけ更新
  python yenjoy.py --all      … 対象全員を取り直す
  python yenjoy.py --todo     … 手打ちが必要な選手(前々期が空欄)を一覧
  python yenjoy.py 012970     … 1人だけ取って表示(取得テスト)

対象: history_master.csv の全員 ＋ 最新スナップショットで A3・今期70点未満の選手

データの在りか:
  https://www.yen-joy.net/racer/data/<登録番号> の HTML に
  <script id="ng-state" type="application/json"> として埋め込まれている。
  値の例(2026-09-27 実測):
    kyuhn_cd_now / kyuhn_cd_before / kyuhn_cd_before2 … {"kyuhn_nm": "Ａ級３班"}
    racer_ssk_toktn … {"m4_avg_toktn": "64.204", "konki_avg_toktn": "64.323",
                       "zenki_avg_toktn": "64.948"}   ※小数3桁。公表値は切り捨て2桁
    retire_flg … "0"/"1"
  robots.txt(2026-05-23版)は一般クローラー許可(/register /mypage /login のみ不可)。
  会員規約の禁止は記事・写真等の無断転載。数値だけを使い、低頻度(1秒間隔)で取る。
"""

import csv
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
JST = timezone(timedelta(hours=9))

MASTER = HERE / "history_master.csv"
SNAPDIR = HERE / "snapshots"
OUT = HERE / "yenjoy.csv"

URL = "https://www.yen-joy.net/racer/data/{}"
HEADERS = {"User-Agent": "keirin-taisha-bot/0.1 (personal research; low frequency)"}
WAIT = 1.0          # 秒。サイトに負荷をかけない
TIMEOUT = 20
MAX_AGE_DAYS = 7    # これより古い行は取り直す(級班・前期得点は期の途中では変わらない)

FIELDS = ["reg_no", "name", "kyuhn_now", "kyuhn_before", "kyuhn_before2", "kyuhn_next",
          "konki", "zenki", "m4", "konki_kido", "zenki_kido", "retire", "grad_period", "fetched"]

NG_STATE = re.compile(r'<script id="ng-state"[^>]*>(.*?)</script>', re.S)


def today_jst():
    return datetime.now(JST).date()


def normalize_grade(s: str) -> str:
    """'Ａ級３班' -> 'A3', 'Ｓ級Ｓ班' -> 'SS', '' -> ''"""
    if not s:
        return ""
    s = s.translate(str.maketrans("ＳＡＬＢ０１２３４５６７８９", "SALB0123456789"))
    m = re.search(r"([SALB])級([S0-9])班", s)
    return f"{m.group(1)}{m.group(2)}" if m else s


def fetch(reg_no: str) -> str:
    last = None
    for attempt in range(2):
        try:
            r = requests.get(URL.format(reg_no), headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:          # 1回だけ待って再試行
            last = e
            time.sleep(5)
    raise last


def parse(html: str, reg_no: str) -> dict:
    """ng-state の JSON から必要な項目だけ抜く。構造が変わったら例外で止める。"""
    m = NG_STATE.search(html)
    if not m:
        raise ValueError("ng-state が見つからない(ページ構造が変わった?)")
    state = json.loads(m.group(1))
    key = next((k for k in state if k.startswith("racer-base-data-")), None)
    if key is None:
        raise ValueError("racer-base-data が見つからない")
    b = state[key]["base"]
    if b.get("racer_no") and b["racer_no"] != reg_no:
        raise ValueError(f"登録番号が違う: {b['racer_no']}")
    t = b.get("racer_ssk_toktn") or {}
    return {
        "reg_no": reg_no,
        "name": f"{b.get('racer_snm_fam', '')} {b.get('racer_snm_fir', '')}".strip(),
        "kyuhn_now": normalize_grade((b.get("kyuhn_cd_now") or {}).get("kyuhn_nm", "")),
        "kyuhn_before": normalize_grade((b.get("kyuhn_cd_before") or {}).get("kyuhn_nm", "")),
        "kyuhn_before2": normalize_grade((b.get("kyuhn_cd_before2") or {}).get("kyuhn_nm", "")),
        "kyuhn_next": normalize_grade((b.get("kyuhn_cd_next") or {}).get("kyuhn_nm", "")),
        "konki": t.get("konki_avg_toktn", ""),
        "zenki": t.get("zenki_avg_toktn", ""),
        "m4": t.get("m4_avg_toktn", ""),
        "konki_kido": "{nendo}-{kido}".format(**(b.get("konki_keirin_nendo_kido") or {"nendo": "", "kido": ""})),
        "zenki_kido": "{nendo}-{kido}".format(**(b.get("zenki_keirin_nendo_kido") or {"nendo": "", "kido": ""})),
        "retire": b.get("retire_flg", ""),
        "grad_period": b.get("grad_period", ""),
        "fetched": today_jst().isoformat(),
    }


def load() -> dict[str, dict]:
    if not OUT.exists():
        return {}
    return {r["reg_no"]: r for r in csv.DictReader(open(OUT, encoding="utf-8-sig"))}


def save(rows: dict[str, dict]) -> None:
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for k in sorted(rows):
            w.writerow({c: rows[k].get(c, "") for c in FIELDS})


def targets() -> dict[str, str]:
    """reg_no -> name。マスタ全員 + 最新スナップショットの A3・今期70点未満(引退除く)"""
    out = {}
    if MASTER.exists():
        for r in csv.DictReader(open(MASTER, encoding="utf-8-sig")):
            out[r["reg_no"].strip().zfill(6)] = r["name"]
    snaps = sorted(SNAPDIR.glob("*.csv"))
    if snaps:
        for r in csv.DictReader(open(snaps[-1], encoding="utf-8-sig")):
            k = r["reg_no"].strip().zfill(6)
            if (r.get("grade") == "A3" and r.get("score") and float(r["score"]) < 70
                    and not r.get("retired")):
                out.setdefault(k, r["name"])
    return out


def mode_update(force: bool) -> None:
    rows = load()
    tg = targets()
    limit = (today_jst() - timedelta(days=MAX_AGE_DAYS)).isoformat()
    todo = [k for k in sorted(tg)
            if force or k not in rows or (rows[k].get("fetched") or "") < limit]
    print(f"対象 {len(tg)}人 / 取得 {len(todo)}人 (間隔{WAIT}秒, 約{len(todo) * WAIT / 60:.0f}分)")
    ok = ng = 0
    for i, k in enumerate(todo, 1):
        try:
            rows[k] = parse(fetch(k), k)
            ok += 1
            r = rows[k]
            print(f"[{i}/{len(todo)}] {k} {r['name']} 前々期={r['kyuhn_before2'] or '-'} "
                  f"前期={r['kyuhn_before'] or '-'} 前期得点={r['zenki'] or '-'}")
        except Exception as e:
            ng += 1
            print(f"[{i}/{len(todo)}] {k} {tg[k]} 失敗: {e}")
        if i % 10 == 0:
            save(rows)          # 途中で落ちても取れた分は残す
        time.sleep(WAIT)
    save(rows)
    print(f"\n完了: 成功{ok} 失敗{ng} -> {OUT.name} ({len(rows)}人)")
    if ng:
        sys.exit(1)             # ワークフローを赤にして気付けるようにする


def mode_todo() -> None:
    """手打ちが必要な選手 = A3在籍3期(前々期・前期・今期ともA3)なのに前々期得点が空欄"""
    rows = load()
    master = {}
    if MASTER.exists():
        for r in csv.DictReader(open(MASTER, encoding="utf-8-sig")):
            t1col = next(c for c in r if c.startswith("t1_"))
            master[r["reg_no"].strip().zfill(6)] = r[t1col].strip()
    todo, later = [], []
    for k, y in sorted(rows.items()):
        if y["kyuhn_before"] == "A3" and y["kyuhn_before2"] == "A3" and y["retire"] != "1":
            if not master.get(k):
                # 前期か今期が70以上なら今期は対象になり得ない(2期連続70未満が条件)
                under = all(v and float(v) < 70 for v in (y["zenki"], y["konki"]))
                (todo if under else later).append(y)
    print(f"前々期の手打ちが必要: {len(todo)}人 (A3在籍3期・前期と今期が70未満・前々期得点なし)")
    for y in sorted(todo, key=lambda y: float(y["konki"] or 99)):
        print(f"  {y['reg_no']} {y['name']:8s} 前期{y['zenki']:>7} 今期{y['konki']:>7}"
              f"  {'マスタ未登録' if y['reg_no'] not in master else '前々期空欄'}")
    print(f"\n急がない: {len(later)}人 (前期か今期が70以上なので今期は対象外。"
          f"来期に備えて入れておくなら対象)")
    for y in later:
        print(f"  {y['reg_no']} {y['name']:8s} 前期{y['zenki']:>7} 今期{y['konki']:>7}")


def mode_one(reg_no: str) -> None:
    r = parse(fetch(reg_no), reg_no)
    for k, v in r.items():
        print(f"{k:14s}: {v}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--all":
        mode_update(force=True)
    elif arg == "--todo":
        mode_todo()
    elif re.fullmatch(r"\d{6}", arg):
        mode_one(arg)
    else:
        mode_update(force=False)
