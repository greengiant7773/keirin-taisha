"""
「最近の成績」の解析

着順はテキストではなく背景画像で表現されている。ファイル名に情報が入る:
  setP-normal-4   … 通常戦の4着
  setP-Wcircle-1  … 白丸(準決勝・選抜の勝ち上がり)の1着
  setP-Bcircle-3  … 黒丸(初日特選・2日目優秀・単発・決勝)の3着
  setP-normal-M   … 未実施
  その他の英字     … 欠場/失格/落車/棄権など(凡例: 欠 落 棄 失 未)

ここから今期の出走回数・失格回数(parse_recent)と、
直近5走の絶好調/不調バッジ(recent_form)を作る。
"""

import re
from datetime import date, timedelta

BADGE = re.compile(r"setP-(normal|Wcircle|Bcircle)-([0-9A-Za-z]+)\.png", re.I)

# 着順以外の記号(ローマ字の頭文字)。評価点から3点引かれるのは失格だけ。
SPECIAL = {
    "S": "失格",       # Shikkaku  -> 評価点 -3
    "R": "落車",       # Rakusha
    "Ke": "棄権",      # Kiken
    "to": "途中欠場",  # 途
    "M": "未実施",
}
DQ_CODES = {"S"}      # 減点対象

# 直近5走の絶好調/不調バッジ判定
FORM_MIN_STARTS = 3          # これ未満の走数しかなければ判定しない(サンプル不足)
FORM_STALE_DAYS = 30         # 最終出走からこの日数を超えたら判定しない(休養明け対策)
FORM_HOT_AVG = 2.0           # 平均着順がこれ以下 -> 🚀
FORM_COLD_AVG = 5.5          # 平均着順がこれ以上 -> 🥺


def term_range(today: date) -> tuple[date, date]:
    """今期の期間。前期=1〜6月 / 後期=7〜12月"""
    if today.month <= 6:
        return date(today.year, 1, 1), date(today.year, 6, 30)
    return date(today.year, 7, 1), date(today.year, 12, 31)


def _resolve_date(mm: int, dd: int, today: date) -> date | None:
    """表示に年が無いため、今年として組んで未来になれば前年の開催と判断する。"""
    try:
        d = date(today.year, mm, dd)
    except ValueError:
        return None
    if d > today:
        try:
            d = date(today.year - 1, mm, dd)
        except ValueError:
            return None
    return d


def _iter_meets(soup, today: date):
    """『最近の成績』の各開催セルを、新しい順に (日付, セル要素, 本文) で返す。
    期(前期/後期)の境界を気にせず、ページ上の全件(最大20開催)を対象にする。"""
    for cell in soup.find_all("table", class_="seiseki_kobetsu"):
        text = cell.get_text("\n", strip=True)
        m = re.search(r"(\d{2})/(\d{2})", text)
        if not m:
            continue
        d = _resolve_date(int(m.group(1)), int(m.group(2)), today)
        if d is None:
            continue
        yield d, cell, text


def parse_recent(soup, today: date | None = None) -> dict:
    """今期分(7/1以降 or 1/1以降)の出走回数・失格回数を集計する。"""
    today = today or date.today()
    start, end = term_range(today)

    out = {"starts": 0, "places": [], "dq": 0, "absent": 0, "meets": 0,
           "marks": []}

    for d, cell, text in _iter_meets(soup, today):
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
            else:
                out["marks"].append(val)
                if val in DQ_CODES:      # 失格だけが減点対象
                    out["dq"] += 1
    return out


def recent_form(soup, today: date | None = None) -> dict:
    """直近5走(欠場・失格などを除く、実際に着順が付いた5走)から
    絶好調(🚀)/不調(🥺)を判定する。期はまたいで良い(休養明けの誤判定は
    『最終出走から30日以上』で別途除外する)。"""
    today = today or date.today()

    last_race_date = None
    places: list[int] = []

    for d, cell, text in _iter_meets(soup, today):
        for p in cell.find_all("p"):
            b = BADGE.search(p.get("style", ""))
            if not b:
                continue
            val = b.group(2)
            if not val.isdigit():
                continue
            if last_race_date is None:
                last_race_date = d          # ページは新しい順なので最初の1件でよい
            if len(places) < 5:
                places.append(int(val))
        if len(places) >= 5 and last_race_date is not None:
            break

    out = {"recent5": places, "last_race_date": last_race_date,
           "avg5": None, "emoji": ""}

    if last_race_date is None or len(places) < FORM_MIN_STARTS:
        return out                                   # サンプル不足
    if (today - last_race_date) > timedelta(days=FORM_STALE_DAYS):
        return out                                   # 休養明け等、判定対象外

    avg = sum(places) / len(places)
    out["avg5"] = round(avg, 2)
    if avg <= FORM_HOT_AVG:
        out["emoji"] = "🚀"
    elif avg >= FORM_COLD_AVG:
        out["emoji"] = "🥺"
    return out


def needed_average(target, total, starts: int, remaining: int):
    """あと remaining 走で target に届くために必要な、残り走の平均点。"""
    from decimal import Decimal, ROUND_DOWN
    if remaining <= 0:
        return None
    v = (Decimal(target) * (starts + remaining) - Decimal(total)) / remaining
    return v.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
