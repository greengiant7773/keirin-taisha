"""
出走表(racelist)ページの構造を調べる使い捨てスクリプト

  python probe_race.py

今日の開催会場を schedule.py から取り、最初の会場の出走表
  https://keirin.jp/pc/dfw/dataplaza/guest/racelist?KCD=<場>&KBI=<日付>
を取得して、表の構造(レース番号・車番・選手・得点・府県)をログに出す。

構造が分かったら race.py として本実装に起こす。
"""

import re
from datetime import date, datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from schedule import load_month, races_on

HEADERS = {"User-Agent":
           "keirin-taisha-bot/0.1 (personal research; low frequency)"}
RACELIST = "https://keirin.jp/pc/dfw/dataplaza/guest/racelist?KCD={}&KBI={}"
JST = timezone(timedelta(hours=9))

# 競輪場コード(全国共通の場コード)
KCD = {
    "函館": 11, "青森": 12, "いわき平": 13,
    "弥彦": 21, "前橋": 22, "取手": 23, "宇都宮": 24, "大宮": 25,
    "西武園": 26, "京王閣": 27, "立川": 28,
    "松戸": 31, "千葉": 32, "川崎": 34, "平塚": 35, "小田原": 36,
    "伊東": 37, "静岡": 38,
    "名古屋": 41, "岐阜": 42, "大垣": 43, "豊橋": 44, "富山": 45,
    "松阪": 46, "四日市": 47,
    "福井": 51, "奈良": 52, "向日町": 53, "和歌山": 54, "岸和田": 55,
    "玉野": 61, "広島": 62, "防府": 63,
    "高松": 71, "小松島": 72, "高知": 73, "松山": 74,
    "小倉": 81, "久留米": 83, "武雄": 84, "佐世保": 85, "別府": 86,
    "熊本": 87,
}


def today_jst() -> date:
    return datetime.now(JST).date()


def main() -> None:
    target = today_jst()
    kaisai = races_on(load_month(target.year, target.month), target)
    print(f"{target:%m/%d} の開催: "
          + " / ".join(f"{k.jo}({k.slot})" for k in kaisai))
    if not kaisai:
        print("開催なしのため終了")
        return

    for k in kaisai[:2]:
        code = KCD.get(k.jo)
        print("\n" + "=" * 60)
        print(f"■ {k.jo} (KCD={code})")
        if not code:
            print("  場コード不明のためスキップ")
            continue

        url = RACELIST.format(code, f"{target:%Y%m%d}")
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = r.apparent_encoding
        print(f"  [get] {url} -> {r.status_code} / {len(r.text):,}字")
        if not r.ok:
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        tables = soup.find_all("table")
        print(f"  表が {len(tables)} 個")
        for i, t in enumerate(tables[:10]):
            rows = t.find_all("tr")
            print(f"  --- 表{i} ({len(rows)}行) ---")
            for tr in rows[:12]:
                cells = [c.get_text(strip=True)[:10]
                         for c in tr.find_all(["th", "td"])]
                if any(cells):
                    print("   ", " | ".join(cells))

        text = soup.get_text(" ", strip=True)
        races = sorted(set(re.findall(r"(\d{1,2})Ｒ|(\d{1,2})R", text)))
        print(f"  レース番号らしき表記: {races[:15]}")
        if len(tables) == 0:
            print("  → 表なし。全文の先頭500字:")
            print(" ", text[:500])


if __name__ == "__main__":
    main()
