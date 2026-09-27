"""
代謝ボーダー（A3・登録消除）の集計と投稿文の生成

  python taisha.py           … 集計してプレビュー
  python taisha.py --write   … posts/ に投稿文を書き出す

判定(男子A3):
  対象者 … 直近2期が連続で70点未満、かつ3期平均も70点未満
  消除  … 対象者のうち3期平均の下位30名
  同点  … 規程は「30番目の3期平均を超えたとき回避」。同点は回避できない
  在籍  … 前々期・前期ともA級3班でなければ判定外(A3在籍3期未満=まだ2期目以下)

データ:
  history_master.csv … reg_no, name, t1_<前々期>, t2_<前期>, 今期  (前々期は手打ち)
  yenjoy.csv         … yenjoy.py が取る 前期得点・級班履歴(前々期/前期/今期)。
                       あれば前期得点はこちらを正とし、級班履歴で在籍期数を確認する
  snapshots/最新.csv … 今期得点を最新に差し替えるために使う
"""

import csv
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

HERE = Path(__file__).parent

JST = timezone(timedelta(hours=9))


def today_jst() -> date:
    """実行環境はUTCなので、日付は必ず日本時間で決める。"""
    return datetime.now(JST).date()

MASTER = HERE / "history_master.csv"
YENJOY = HERE / "yenjoy.csv"
SNAPDIR = HERE / "snapshots"
OUTDIR = HERE / "posts"

THRESHOLD = Decimal("70.00")
QUOTA = 30
SCORE_OK = re.compile(r"\d{2,3}\.\d{1,2}")   # 公表形式(小数1〜2桁)以外は未確認扱い
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
    reader = csv.DictReader(open(MASTER, encoding="utf-8-sig"))
    # 列名は t1_2025後期 / t2_2026前期 のように期名が付くので、接頭辞で探す
    # (期が替わって列名を付け直しても動くようにする)
    t1col = next((c for c in reader.fieldnames if c.startswith("t1_")), None)
    t2col = next((c for c in reader.fieldnames if c.startswith("t2_")), None)
    if not (t1col and t2col):
        raise SystemExit(f"{MASTER.name} に t1_ / t2_ で始まる列がありません")
    for r in reader:
        k = r["reg_no"].strip().zfill(6)
        out[k] = {"name": r["name"], "t1": r[t1col].strip(),
                  "t2": r[t2col].strip(), "cur": r["今期"].strip()}
    return out


def load_yenjoy() -> dict[str, dict]:
    """yenjoy.py の出力。無ければ空(従来どおりマスタだけで判定)。"""
    if not YENJOY.exists():
        return {}
    return {r["reg_no"].strip().zfill(6): r
            for r in csv.DictReader(open(YENJOY, encoding="utf-8-sig"))}


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


def judge(master: dict[str, dict], yenjoy: dict[str, dict] | None = None):
    """代謝対象者を3期平均の昇順で返す。"""
    if yenjoy is None:
        yenjoy = load_yenjoy()
    rows = []
    unverified = []     # 手打ち値が公表形式でない(仮置きの疑い)
    short = []          # A3在籍3期未満(前々期 or 前期がA3でない)
    mismatch = []       # マスタの前期がyen-joyと違う
    for reg, m in master.items():
        y = yenjoy.get(reg)
        t2 = m["t2"]
        t2_verified = False
        if y:
            if y.get("retire") == "1":
                continue
            g1, g2 = y.get("kyuhn_before", ""), y.get("kyuhn_before2", "")
            # 前々期・前期にA級3班でなかった期があれば、その期の得点は数えない
            # (＝まだA3で2期目以下)。梶應弘樹(2025後期A2)の指摘で追加
            if g1 != "A3" or g2 != "A3":
                short.append(f"{m['name']}(前々期={g2 or '-'}/前期={g1 or '-'})")
                continue
            # 前期得点は yen-joy(小数3桁)を切り捨て2桁にしたものを正とする
            if y.get("zenki"):
                zt = str(floor2(Decimal(y["zenki"])))
                if t2 and Decimal(t2) != Decimal(zt):
                    mismatch.append(f"{m['name']}(マスタ{t2}→{zt})")
                t2 = zt
                t2_verified = True
        if not (m["t1"] and t2 and m["cur"]):
            continue
        # 競走得点は必ず小数付きで公表される。小数のない手打ち値は仮置きの
        # 可能性が高いので、確認が取れるまで判定から外す(誤って名指ししない)。
        # yen-joy で確認できた前期は整数でも本物なので対象外。
        checks = [("t1", m["t1"])] + ([] if t2_verified else [("t2", t2)])
        bad = [k for k, v in checks if not SCORE_OK.fullmatch(v.strip())]
        if bad:
            vals = {"t1": m["t1"], "t2": t2}
            unverified.append(f"{m['name']}({'/'.join(bad)}={'/'.join(vals[k] for k in bad)})")
            continue
        a, b, c = Decimal(m["t1"]), Decimal(t2), Decimal(m["cur"])
        if not (b < THRESHOLD and c < THRESHOLD):
            continue                        # 2期連続で70点未満でなければ対象外
        avg = floor2((a + b + c) / 3)
        if avg >= THRESHOLD:
            continue
        rows.append({"reg_no": reg, "name": m["name"], "avg": avg,
                     "t1": a, "t2": b, "cur": c})
    if yenjoy:
        print(f"[info] yen-joy データ {len(yenjoy)}人分を使用 "
              f"(最終取得 {max(r.get('fetched', '') for r in yenjoy.values())})")
    if short:
        print(f"[info] A3在籍3期未満のため判定外: {len(short)}人")
        for s in short:
            print(f"        {s}")
    if mismatch:
        print(f"[warn] マスタの前期得点がyen-joyと不一致(yen-joyを採用): {len(mismatch)}人")
        for s in mismatch:
            print(f"        {s}")
    if unverified:
        print(f"[warn] 手打ち値が未確認(小数なし)のため判定外: {len(unverified)}人")
        for u in unverified:
            print(f"        {u}")
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

    text = build_post(rows, border, today_jst())
    print(f"\n--- 投稿文 ({x_len(text)}字) ---\n{text}")

    if write:
        OUTDIR.mkdir(exist_ok=True)
        p = OUTDIR / f"{today_jst():%Y%m%d}_代謝ボーダー.txt"
        p.write_text(text, encoding="utf-8")
        print(f"\n-> {p.name}")


if __name__ == "__main__":
    main("--write" in sys.argv)
