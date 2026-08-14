"""
「最近の成績」の解析

着順はテキストではなく背景画像で表現されている。ファイル名に情報が入る:
  setP-normal-4   … 通常戦の4着
  setP-Wcircle-1  … 白丸(準決勝・選抜の勝ち上がり)の1着
  setP-Bcircle-3  … 黒丸(初日特選・2日目優秀・単発・決勝)の3着
  setP-normal-M   … 未実施
  その他の英字     … 欠場/失格/落車/棄権など(凡例: 欠 落 棄 失 未)

ここから今期(7/1以降 or 1/1以降)の出走回数と失格回数を数える。
"""

import re
from datetime import date

BADGE = re.compile(r"setP-(normal|Wcircle|Bcircle)-([0-9A-Za-z]+)\.png", re.I)
DATE = re.compile(r"^(\d{2})/(\d{2})$")

# 着順以外の記号。凡例より
SPECIAL = {"M": "未実施"}


def term_range(today: date) -> tuple[date, date]:
    """今期の期間。前期=1〜6月 / 後期=7〜12月"""
    if today.month <= 6:
        return date(today.year, 1, 1), date(today.year, 6, 30)
    return date(today.year, 7, 1), date(today.year, 12, 31)


def parse_recent(soup, today: date | None = None) -> dict:
    """直近20開催から、今期分の出走回数・着順・失格回数を集計する。"""
    today = today or date.today()
    start, end = term_range(today)

    out = {"starts": 0, "places": [], "dq": 0, "absent": 0, "meets": 0}

    for cell in soup.find_all("table", class_="seiseki_kobetsu"):
        text = cell.get_text("\n", strip=True)
        m = re.search(r"(\d{2})/(\d{2})", text)
        if not m:
            continue
        mm, dd = int(m.group(1)), int(m.group(2))
        # 表示に年がないため、今年として組んで未来になるなら前年の開催と判断する
        try:
            d = date(today.year, mm, dd)
        except ValueError:
            continue
        if d > today:
            try:
                d = date(today.year - 1, mm, dd)
            except ValueError:
                continue
        if not (start <= d <= end):
            continue

        out["meets"] += 1
        if "欠場" in text or "不参加" in text:
            out["absent"] += 1

        for p in cell.find_all("p"):
            b = BADGE.search(p.get("style", ""))
            if not b:
                continue
            kind, val = b.group(1), b.group(2)
            if val.isdigit():
                out["starts"] += 1
                out["places"].append((kind, int(val)))
            elif val.upper() not in SPECIAL:
                # 数字でも未実施でもない = 失格・落車・欠場など
                out["dq"] += 1
    return out


def needed_average(target, total, starts: int, remaining: int):
    """あと remaining 走で target に届くために必要な、残り走の平均点。"""
    from decimal import Decimal, ROUND_DOWN
    if remaining <= 0:
        return None
    v = (Decimal(target) * (starts + remaining) - Decimal(total)) / remaining
    return v.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
