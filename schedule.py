"""
開催日程カレンダーの解析

開催日程ページ(/pc/raceschedule)には2種類の情報がある:
  1. pc0101_json … その日の開催だけ。明日以降は別リクエストが必要
  2. 月間カレンダーの表 … その月の全開催。時間帯アイコン付き

2の方が先の予定まで一度に取れるので、こちらを使う。

表の構造:
  地区ごとに <table class="chiku_tbl">
  ヘッダ行に 1〜31 の日付
  各行が競輪場。開催セルは class="bk_kaisai" で、colspan が開催日数
  セル内の ico_kaisai_N.png が時間帯、ico_fN.png / ico_gN.png がグレード
"""

import re
from datetime import date
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

URL = "https://keirin.jp/pc/raceschedule"
HEADERS = {"User-Agent": "keirin-taisha-bot/0.1 (personal research; low frequency)"}
TIMEOUT = 20

# ico_kaisai_N -> 時間帯名
KUBUN = {"8": "モーニング", "1": "デイ", "3": "ナイター", "5": "ミッドナイト"}


@dataclass
class Kaisai:
    jo: str          # 競輪場名
    grade: str       # F1 / F2 / G3 ...
    slot: str        # モーニング / デイ / ナイター / ミッドナイト
    start: date
    end: date

    def covers(self, d: date) -> bool:
        return self.start <= d <= self.end

    def __str__(self) -> str:
        return (f"{self.jo}{self.grade}({self.slot}) "
                f"{self.start:%m/%d}-{self.end:%m/%d}")


def fetch(year: int, month: int) -> str:
    r = requests.get(f"{URL}?scyy={year}&scym={month:02d}",
                     headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def parse(html: str, year: int, month: int) -> list[Kaisai]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Kaisai] = []

    for table in soup.select("table.chiku_tbl"):
        body = table.find("tbody")
        if not body:
            continue
        for row in body.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue
            # 1列目が競輪場名
            jo = cells[0].get_text(strip=True)
            if not jo:
                continue

            day = 1                      # いま何日の列にいるか
            for td in cells[1:]:
                span = int(td.get("colspan", 1))
                if "bk_kaisai" in (td.get("class") or []):
                    k = build(td, jo, year, month, day, span)
                    if k:
                        out.append(k)
                day += span
    return out


def build(td, jo: str, year: int, month: int, day: int, span: int):
    srcs = [img.get("src", "") for img in td.find_all("img")]
    joined = " ".join(srcs)

    m = re.search(r"ico_kaisai_(\d+)\.png", joined)
    slot = KUBUN.get(m.group(1), "デイ") if m else "デイ"

    g = re.search(r"ico_(f\d|g\d|gp)\.png", joined)
    grade = g.group(1).upper() if g else ""

    try:
        start = date(year, month, day)
        end = date(year, month, min(day + span - 1, last_day(year, month)))
    except ValueError:
        return None
    return Kaisai(jo, grade, slot, start, end)


def last_day(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def load_month(year: int, month: int) -> list[Kaisai]:
    return parse(fetch(year, month), year, month)


def races_on(kaisai: list[Kaisai], d: date) -> list[Kaisai]:
    return [k for k in kaisai if k.covers(d)]


if __name__ == "__main__":
    from datetime import timedelta
    today = date.today()
    ks = load_month(today.year, today.month)
    print(f"{today:%Y年%m月} の開催 {len(ks)}件\n")

    for label, d in (("今日", today), ("明日", today + timedelta(days=1))):
        rs = races_on(ks, d)
        print(f"--- {label} {d:%m/%d} : {len(rs)}件 ---")
        by_slot: dict[str, list[str]] = {}
        for k in rs:
            n = (d - k.start).days + 1
            by_slot.setdefault(k.slot, []).append(f"{k.jo}{k.grade}({n}日目)")
        for slot, items in by_slot.items():
            print(f"  {slot}: {' / '.join(items)}")
        print()
