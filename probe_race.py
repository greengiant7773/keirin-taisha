"""
出走表の取得元を調べるための使い捨てスクリプト

  python probe_race.py 013333

やること:
  1. 選手の「出場予定レース」ページを取り、レース番号がどこに書かれているか探す
  2. 見つかった出走表ページを取り、メンバー表(車番・選手名・得点・府県)を探す

構造が分かったら、この内容を race.py として本実装に起こす。
ここでは判断せず、素材をログに出すことに徹する。
"""

import re
import sys

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": ("keirin-taisha-bot/0.1 (personal research; low frequency)")
}
ENTRY = "https://keirin.jp/mb/racerentryrace?snum={}"


def get(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    print(f"[get] {url} -> {r.status_code} / {len(r.text):,}字")
    return BeautifulSoup(r.text, "html.parser")


def show_tables(soup: BeautifulSoup, limit: int = 4) -> None:
    """ページ内の表を、中身が分かる程度に出す。"""
    tables = soup.find_all("table")
    print(f"  表が {len(tables)} 個")
    for i, t in enumerate(tables[:limit]):
        rows = t.find_all("tr")
        print(f"  --- 表{i} ({len(rows)}行) ---")
        for tr in rows[:6]:
            cells = [c.get_text(strip=True)[:14]
                     for c in tr.find_all(["th", "td"])]
            if any(cells):
                print("   ", " | ".join(cells))


def main(reg_no: str) -> None:
    print("=" * 60)
    print(f"■ 出場予定レース: {reg_no}")
    soup = get(ENTRY.format(reg_no))
    show_tables(soup)

    # 「1R」「12R」のような表記と、その周辺のリンクを探す
    text = soup.get_text(" ", strip=True)
    races = re.findall(r"(\d{1,2})\s*[Rレース]", text)
    print(f"  レース番号らしき数字: {sorted(set(races))[:15]}")

    links = [a.get("href") for a in soup.find_all("a", href=True)]
    cand = [h for h in links
            if any(k in h for k in ("race", "detail", "syutsuba", "entry"))]
    print(f"  出走表らしきリンク {len(cand)}件:")
    for h in cand[:8]:
        print("   ", h)

    if not cand:
        print("\n→ リンクが取れなかった。ページ全文の先頭を確認する:")
        print(text[:600])
        return

    # 最初の候補を開いて、メンバー表が取れるか見る
    url = cand[0]
    if url.startswith("/"):
        url = "https://keirin.jp" + url
    print("\n" + "=" * 60)
    print(f"■ 出走表候補: {url}")
    try:
        show_tables(get(url), limit=6)
    except Exception as e:
        print(f"  取得できず: {e}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "013333")
