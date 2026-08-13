"""
勝負駆けアラート

  python shobugake.py          … 明日分の投稿文を時間帯ごとに作成
  python shobugake.py 0        … 今日分(検証用)
  python shobugake.py 8/20     … 指定日(検証用)

なぜ「明日分」なのか:
  選手プロフィールの「出場予定」は、その開催が始まると消える。
  当日の朝に見ても、その日走る開催はもう載っていない。
  よって前日のうちに翌日分を作る。リマインドとしてもこの方が機能する。

文字数:
  Xは全角を2文字として数えるため、日本語だと実質140文字が上限。
  重み付きで280を超えないように削る。
"""

import csv
import sys
import unicodedata
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from border import class_borders, near_line
from schedule import load_month, races_on

HERE = Path(__file__).parent
SNAPDIR = HERE / "snapshots"
OUTDIR = HERE / "posts"

SPAN = Decimal("0.50")      # ボーダーから何点以内を「争い」とみなすか
MAX_RIDERS = 6              # 1投稿に載せる人数の上限
X_LIMIT = 280               # 全角=2 で数えたときの上限
DISCLAIMER = "※非公式・個人集計"


# ---------------------------------------------------------------- 文字数

def x_len(s: str) -> int:
    """Xの数え方。全角(F/W/A)は2、それ以外は1。"""
    return sum(2 if unicodedata.east_asian_width(c) in "FWA" else 1 for c in s)


# ---------------------------------------------------------------- 選手

def load_snapshot() -> list[dict]:
    snaps = sorted(SNAPDIR.glob("*.csv"))
    if not snaps:
        raise SystemExit("スナップショットがありません。先に scrape.py を実行してください")
    print(f"使用データ: {snaps[-1].name}")
    with open(snaps[-1], encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def parse_entries(rider: dict) -> list[tuple[str, tuple, tuple]]:
    """'伊東@09/02-09/04;大垣@09/13-09/15' を [(場,(月,日),(月,日))] に。"""
    out = []
    for span in (rider.get("entries") or "").split(";"):
        jo, _, rest = span.partition("@")
        if not rest:
            jo, rest = "", span
        if "-" not in rest:
            continue
        try:
            s, e = rest.split("-")
            out.append((jo, tuple(map(int, s.split("/"))),
                        tuple(map(int, e.split("/")))))
        except ValueError:
            continue
    return out


def same_jo(a: str, b: str) -> bool:
    """競輪場名の照合。表記ゆれに備えて先頭2文字で見る(西武園/西武 など)。"""
    a, b = a.strip(), b.strip()
    return bool(a and b and (a.startswith(b[:2]) or b.startswith(a[:2])))


def riding_on(rider: dict, d: date, venues: list[str]) -> list[str]:
    """その日に出走する競輪場。出場予定と、開催中のレース欄の両方を見る。"""
    hit = []
    cur = (d.month, d.day)
    for jo, s, e in parse_entries(rider):
        inside = (s <= cur <= e) if s <= e else (cur >= s or cur <= e)
        if inside and jo:
            hit.append(jo)

    # 開催中のレース欄は日付を持たないので、その日開催中の場と一致したときだけ採用
    now = (rider.get("racing_now") or "").strip()
    if now and any(same_jo(now, v) for v in venues):
        hit.append(now)
    return hit


# 追う対象。(表示名, 対象級班, どのラインか)
# A級は全班を得点順に並べた上位200名がS級へ上がるため、A2からの昇級もある。
# A1昇級(A2→A1)は当落の重みが軽いので追わない。
TRACKS = [
    ("S級昇級", ("A1", "A2"), "S級"),
]


def contenders(snap: list[dict]):
    """各ライン付近の選手と、ライン値一式。"""
    alive = [{**r, "score": Decimal(r["score"])}
             for r in snap if not r.get("retired") and r.get("score")]
    lines = class_borders(alive)

    out = []
    for label, grades, key in TRACKS:
        pool = [r for r in alive if r["grade"] in grades]
        for r in near_line(pool, lines[key], SPAN):
            out.append({**r, "_kind": label})
    return out, lines


# ---------------------------------------------------------------- 出力

def build_post(slot: str, venues: list[str], riders: list[dict],
               d: date, border: Decimal, kind: str) -> str:
    head = f"【{d.month}/{d.day} {slot}・{kind}争い】"
    where = "／".join(venues)
    foot = f"{kind}ライン{border}\n{DISCLAIMER}"

    def fmt(r):
        g = r["gap"]
        grade = r.get("grade", "")
        if g > 0:
            state = f"圏内+{g}"
        elif g == 0:
            state = "ライン上"
        else:
            state = f"あと{-g}"
        return f"・{r['name']}({grade}) {r['score']}［{state}］"

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


def main(target: date) -> None:
    kaisai = load_month(target.year, target.month)
    todays = races_on(kaisai, target)
    print(f"\n{target:%m/%d} の開催 {len(todays)}件")
    if not todays:
        print("開催がありません")
        return

    snap = load_snapshot()
    cands, lines = contenders(snap)
    print("ライン: " + " / ".join(f"{k}={v}" for k, v in lines.items()))
    print(f"対象(±{SPAN}点) {len(cands)}人")

    venues = [k.jo for k in todays]
    OUTDIR.mkdir(exist_ok=True)

    by_slot: dict[str, list] = {}
    for k in todays:
        by_slot.setdefault(k.slot, []).append(k)

    for slot, ks in by_slot.items():
        jos = [k.jo for k in ks]
        hit = []
        for r in cands:
            ride = riding_on(r, target, venues)
            if any(same_jo(x, j) for x in ride for j in jos):
                hit.append(r)
        if not hit:
            print(f"\n{slot}: 該当なし")
            continue

        for kind in sorted({r["_kind"] for r in hit}):
            grp = [r for r in hit if r["_kind"] == kind]
            if not grp:
                continue
            # ラインに近い順(=当落線上の選手を先に)
            grp.sort(key=lambda r: abs(r["gap"]))
            text = build_post(slot, [f"{k.jo}{k.grade}" for k in ks],
                              grp, target, grp[0]["border"], kind)
            path = OUTDIR / f"{target:%Y%m%d}_{slot}_{kind}.txt"
            path.write_text(text, encoding="utf-8")
            print(f"\n--- {slot}/{kind} ({len(grp)}人 / {x_len(text)}字) "
                  f"-> {path.name} ---")
            print(text)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "1"
    if "/" in arg:
        m, d = map(int, arg.split("/"))
        t = date(date.today().year, m, d)
    else:
        t = date.today() + timedelta(days=int(arg))
    main(t)
