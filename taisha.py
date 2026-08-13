"""
代謝ボーダー（A3・登録消除）の集計と投稿文の生成

  python taisha.py           … 集計してプレビュー
  python taisha.py --write   … posts/ に投稿文を書き出す

判定(男子A3):
  対象者 … 直近2期が連続で70点未満、かつ3期平均も70点未満
  消除  … 対象者のうち3期平均の下位30名
  同点  … 規程は「30番目の3期平均を超えたとき回避」。同点は回避できない

データ:
  history_master.csv … reg_no, name, 2025後期, 2026前期, 今期
  snapshots/最新.csv … 今期得点を最新に差し替えるために使う
"""

import csv
import sys
import unicodedata
from datetime import date
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

HERE = Path(__file__).parent
MASTER = HERE / "history_master.csv"
SNAPDIR = HERE / "snapshots"
OUTDIR = HERE / "posts"

THRESHOLD = Decimal("70.00")
QUOTA = 30
TOP_N = 8                 # 投稿に載せる人数
X_LIMIT = 280
DISCLAIMER = "※非公式・個人集計"


def x_len(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "FWA" else 1 for c in s)


def floor2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def load_master() -> dict[str, dict]:
    if not MASTER.exists():
        raise SystemExit(f"{MASTER.name} がありません")
    out = {}
    for r in csv.DictReader(open(MASTER, encoding="utf-8-sig")):
        k = r["reg_no"].strip().zfill(6)
        out[k] = {"name": r["name"], "t1": r["t1_2025後期"].strip(),
                  "t2": r["t2_2026前期"].strip(), "cur": r["今期"].strip()}
    return out


def apply_latest(master: dict[str, dict]) -> str:
    """今期得点を最新スナップショットで上書きする。"""
    snaps = sorted(SNAPDIR.glob("*.csv"))
    if not snaps:
        return "(スナップショットなし)"
    for r in csv.DictReader(open(snaps[-1], encoding="utf-8-sig")):
        k = r["reg_no"].strip().zfill(6)
        if k in master:
            if r.get("retired"):
                master[k]["cur"] = ""       # 引退は判定から外す
            elif r.get("score"):
                master[k]["cur"] = r["score"]
    return snaps[-1].name


def judge(master: dict[str, dict]):
    """代謝対象者を3期平均の昇順で返す。"""
    rows = []
    for reg, m in master.items():
        if not (m["t1"] and m["t2"] and m["cur"]):
            continue
        a, b, c = Decimal(m["t1"]), Decimal(m["t2"]), Decimal(m["cur"])
        if not (b < THRESHOLD and c < THRESHOLD):
            continue                        # 2期連続で70点未満でなければ対象外
        avg = floor2((a + b + c) / 3)
        if avg >= THRESHOLD:
            continue
        rows.append({"reg_no": reg, "name": m["name"], "avg": avg,
                     "t1": a, "t2": b, "cur": c})
    rows.sort(key=lambda r: r["avg"])
    border = rows[QUOTA - 1]["avg"] if len(rows) >= QUOTA else None
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        # 「ボーダーを超えた」場合のみ圏外。同点は圏内(危険側)に数える
        r["in_danger"] = border is None or r["avg"] <= border
    return rows, border


def build_post(rows: list[dict], border: Decimal | None, d: date) -> str:
    head = f"【{d.month}/{d.day}時点 A3代謝ボーダー】"
    if border is None:
        line = f"対象者が{QUOTA}名未満のためボーダー未成立"
    else:
        line = f"下位{QUOTA}位ライン {border}（3期平均）"

    def fmt(r):
        return f"{r['rank']}. {r['name']} {r['avg']}"

    lines = [fmt(r) for r in rows[:TOP_N]]
    n = len(rows)

    def assemble(ls):
        rest = f"\n他{n - len(ls)}名" if n > len(ls) else ""
        return (f"{head}\n{line}\n対象{n}名\n\n" + "\n".join(ls) + rest
                + f"\n\n{DISCLAIMER}")

    text = assemble(lines)
    while x_len(text) > X_LIMIT and lines:
        lines.pop()
        text = assemble(lines)
    return text


def main(write: bool) -> None:
    master = load_master()
    used = apply_latest(master)
    print(f"マスタ {len(master)}人 / 今期得点は {used} で更新")

    rows, border = judge(master)
    print(f"代謝対象者 {len(rows)}人  ボーダー({QUOTA}位): {border}\n")

    for r in rows[:QUOTA + 3]:
        mark = " ←ボーダー" if r["rank"] == QUOTA else ""
        state = "" if r["in_danger"] else "  (圏外)"
        print(f"{r['rank']:3d}位 {r['avg']} {r['name']}"
              f"  [{r['t1']}/{r['t2']}/{r['cur']}]{mark}{state}")

    text = build_post(rows, border, date.today())
    print(f"\n--- 投稿文 ({x_len(text)}字) ---\n{text}")

    if write:
        OUTDIR.mkdir(exist_ok=True)
        p = OUTDIR / f"{date.today():%Y%m%d}_代謝ボーダー.txt"
        p.write_text(text, encoding="utf-8")
        print(f"\n-> {p.name}")


if __name__ == "__main__":
    main("--write" in sys.argv)
