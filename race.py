"""
当日のレース単位で出走メンバーを組み立てる

scrape.py が各選手のプロフィールから拾う today_race 列
    平Ｆ２@08/30/4R;平Ｆ２@08/31/5R
を使って、「同じ会場・同じ日・同じレース番号」の選手を束ねる。

出走表そのもののページは keirin.jp の robots.txt で自動取得が
許可されていないため、許可されている選手プロフィールだけで
出走メンバーを再構成する方針を取っている。

そのため取れるのは「誰が同じレースに出るか」までで、
車番・並びまでは分からない。得点順に並べて出す。
"""

import re
from collections import defaultdict
from datetime import date
from decimal import Decimal


def parse_today_race(cell: str, target: date):
    """today_race セルから、その日の (会場略称, レース番号) を取る。

    例: "平Ｆ２@08/30/4R;平Ｆ２@08/31/5R" で 8/31 なら ("平Ｆ２", 5)
    該当日が無ければ None。
    """
    if not cell:
        return None
    want = f"{target:%m/%d}"
    for part in cell.split(";"):
        m = re.match(r"(.*)@(\d{2}/\d{2})/(\d{1,2})R", part.strip())
        if m and m.group(2) == want:
            return m.group(1), int(m.group(3))
    return None


def build_races(snapshot: list[dict], target: date) -> dict:
    """その日の全レースを {(会場, R): [選手, ...]} で返す。

    選手は得点の高い順に並べる（車番が取れないため）。
    """
    races = defaultdict(list)
    for r in snapshot:
        got = parse_today_race(r.get("today_race", ""), target)
        if not got:
            continue
        jo, rno = got
        races[(jo, rno)].append(r)

    for key in races:
        races[key].sort(
            key=lambda r: Decimal(r["score"]) if r.get("score") else Decimal(0),
            reverse=True)
    return dict(races)


def format_race(members: list[dict], marked: set[str],
                pref: dict[str, str] | None = None) -> list[str]:
    """1レース分のメンバー表を行のリストで返す。

    marked … 注目選手(勝負駆け・代謝危機)の登録番号。★を付ける
    pref   … 登録番号 -> 府県。ラインの推測材料として添える
    """
    lines = []
    for r in members:
        star = " ★" if r["reg_no"] in marked else ""
        ken = (pref or {}).get(r["reg_no"], "")
        ken = f"{ken} " if ken else ""
        lines.append(f"　{r['name']}　{ken}{r['grade']}　{r['score']}{star}")
    return lines
