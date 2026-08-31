"""
racerprofile(robots.txtで許可済み)に当日のレース番号が
載っているかを調べる使い捨てスクリプト

  python probe_race.py

開催中(racing_now)の選手2人のプロフィールを取り、
「出場予定」「本日」「◯R」等の周辺テキストと表をそのまま出す。
レース番号が取れるなら、同一(会場,R)の選手を束ねるだけで
出走メンバー表を許可ページのみで再構成できる。
"""

import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent":
           "keirin-taisha-bot/0.1 (personal research; low frequency)"}
PROFILE = "https://keirin.jp/pc/racerprofile?snum={}"

# 今朝のスナップショットで racing_now が入っていた選手
TARGETS = ["011341", "011451"]   # 黒崎直行(いわき平) / 重一徳(いわき平)


def main() -> None:
    for snum in TARGETS:
        print("=" * 60)
        url = PROFILE.format(snum)
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = r.apparent_encoding
        print(f"[get] {url} -> {r.status_code} / {len(r.text):,}字")
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        # 「R」を含む数字表記
        rs = re.findall(r"\d{1,2}\s*[RＲ]", text)
        print("  R表記:", sorted(set(rs))[:20])

        # キーワード周辺を出す
        for kw in ("出場予定", "本日", "開催中", "出走"):
            for m in re.finditer(kw, text):
                s = max(0, m.start() - 20)
                print(f"  [{kw}] …{text[s:m.start() + 120]}…")
                break  # 各キーワード最初の1箇所だけ

        # 表の中に R を含むものを出す
        for i, t in enumerate(soup.find_all("table")):
            tt = t.get_text(" ", strip=True)
            if re.search(r"\d{1,2}\s*[RＲ]", tt):
                print(f"  --- R入りの表{i} ---")
                for tr in t.find_all("tr")[:8]:
                    cells = [c.get_text(strip=True)[:12]
                             for c in tr.find_all(["th", "td"])]
                    if any(cells):
                        print("   ", " | ".join(cells))


if __name__ == "__main__":
    main()
