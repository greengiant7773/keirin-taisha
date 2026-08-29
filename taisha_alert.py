"""
代謝危機の選手が出走する日に、時間帯ごとの出走通知を作る

  python taisha_alert.py            … 今日の分をプレビュー
  python taisha_alert.py --write    … posts/ に書き出す
  python taisha_alert.py 20260901   … 日付を指定

代謝ボーダー投稿(週2回・全体像)に対して、こちらは
「今日この選手が走る」という当日の実況側。
消除圏内の選手を優先し、圏外でもボーダー付近なら載せる。

判定は taisha.py、出走の拾い方と時間帯は shobugake.py を再利用する。
"""

import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from schedule import load_month, races_on
from shobugake import (load_snapshot, riding_on, same_jo, hashtags,
                       OUTDIR)
from taisha import load_master, apply_latest, judge, QUOTA

HERE = Path(__file__).parent

MAX_RIDERS = 6            # 1投稿に載せる上限
NEAR = Decimal("1.50")    # ボーダーからこの範囲までは圏外でも載せる
X_LIMIT = 280
DISCLAIMER = "※非公式・個人集計"
JST = timezone(timedelta(hours=9))


def today_jst() -> date:
    return datetime.now(JST).date()


def x_len(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "FWA" else 1 for c in s)


def danger_riders(target: date):
    """代謝の危険度が高い順に、その日走る選手を返す。"""
    master = load_master()
    apply_latest(master)
    rows, border = judge(master)

    # 出走予定はスナップショット側にしか無いので、登録番号で突き合わせる
    snap = {r["reg_no"].strip().zfill(6): r for r in load_snapshot()}
    out = []
    for r in rows:
        if border is not None and not r["in_danger"]:
            if r["avg"] - border > NEAR:
                continue          # ボーダーから離れた圏外は対象外
        s = snap.get(r["reg_no"])
        if s:
            out.append({**r, "snap": s})
    return out, border


def build_post(slot: str, venues: list[str], riders: list[dict],
               d: date, border: Decimal | None) -> str:
    head = f"【{d.month}/{d.day} {slot}・代謝危機の選手】"
    where = "／".join(venues)
    line = (f"下位{QUOTA}位ライン {border}（3期平均）" if border is not None
            else f"対象者が{QUOTA}名未満のためボーダー未成立")
    foot = f"{line}\n{DISCLAIMER}\n{hashtags(venues)}"

    def fmt(r):
        if border is None:
            state = ""
        elif r["in_danger"]:
            state = f"消除圏内{r['rank']}位"
        else:
            state = f"あと{r['avg'] - border}で圏内"
        return f"・{r['name']} {r['avg']}［{state}］"

    lines = [fmt(r) for r in riders[:MAX_RIDERS]]
    rest = len(riders) - len(lines)

    def assemble(ls, extra):
        body = "\n".join(ls) + (f"\n他{extra}名" if extra else "")
        return f"{head}\n{where}\n\n{body}\n\n{foot}"

    text = assemble(lines, rest)
    while x_len(text) > X_LIMIT and lines:
        lines.pop()
        rest = len(riders) - len(lines)
        text = assemble(lines, rest)
    return text


def main(target: date, write: bool) -> None:
    kaisai = load_month(target.year, target.month)
    today = races_on(kaisai, target)
    print(f"\n{target:%m/%d} の開催 {len(today)}件")
    if not today:
        print("開催なし")
        return

    riders, border = danger_riders(target)
    print(f"代謝危機の対象 {len(riders)}人 / ボーダー {border}")

    by_slot: dict[str, list] = {}
    for k in today:
        by_slot.setdefault(k.slot, []).append(k)

    for slot, ks in by_slot.items():
        venues = [k.jo for k in ks]
        grp = [r for r in riders
               if riding_on(r["snap"], target, venues)]
        if not grp:
            print(f"\n{slot}: 該当なし")
            continue

        text = build_post(slot, [f"{k.jo}{k.grade}" for k in ks],
                          grp, target, border)
        print(f"\n--- {slot} ({len(grp)}人 / {x_len(text)}字) ---\n{text}")

        if write:
            OUTDIR.mkdir(exist_ok=True)
            path = OUTDIR / f"{target:%Y%m%d}_{slot}_代謝危機.txt"
            path.write_text(text, encoding="utf-8")
            print(f"-> {path.name}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--write"]
    d = (datetime.strptime(args[0], "%Y%m%d").date() if args
         else today_jst())
    main(d, "--write" in sys.argv)
