"""
調査用の使い捨てスクリプト(job=probe で実行)

2026-09-27: yen-joy.net の選手ページが GitHub Actions からだと 404 になる原因調べ。
ブラウザ(日本の回線)からは 200 で取れている。
User-Agent の書式で変わるのか、接続元(IP)で変わるのかを切り分ける。
リクエストは合計6回・2秒間隔。ページの中身は保存しない(状態と長さだけ表示)。

  python probe_race.py [登録番号]
"""

import re
import sys
import time

import requests

SNUM = sys.argv[1] if len(sys.argv) > 1 else "012970"
PAGE = f"https://www.yen-joy.net/racer/data/{SNUM}"
UA_NOW = "keirin-taisha-bot/0.1 (personal research; low frequency)"
UA_STD = "Mozilla/5.0 (compatible; keirin-taisha/0.1; +https://greengiant7773.github.io/keirin-taisha/)"

CASES = [
    ("今のUA", PAGE, {"User-Agent": UA_NOW}),
    ("標準書式のbot UA", PAGE, {"User-Agent": UA_STD}),
    ("requests既定のUA", PAGE, {}),
    ("標準書式+Accept", PAGE, {"User-Agent": UA_STD, "Accept": "text/html,application/xhtml+xml",
                               "Accept-Language": "ja,en;q=0.8"}),
    ("トップページ", "https://www.yen-joy.net/", {"User-Agent": UA_STD}),
    ("robots.txt", "https://www.yen-joy.net/robots.txt", {"User-Agent": UA_NOW}),
]


def main() -> None:
    try:
        ip = requests.get("https://api.ipify.org", timeout=10).text
    except Exception as e:
        ip = f"不明({e})"
    print(f"接続元IP: {ip}\n")
    for label, url, headers in CASES:
        try:
            r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            body = r.text
            ng = bool(re.search(r'<script id="ng-state"', body))
            zenki = re.search(r'"zenki_avg_toktn":"([^"]*)"', body)
            print(f"[{label}] {r.status_code} {len(body):,}字 ng-state={ng} "
                  f"zenki={zenki.group(1) if zenki else '-'} "
                  f"server={r.headers.get('server')} x-cache={r.headers.get('x-cache')} "
                  f"final={r.url}")
            if r.status_code != 200:
                title = re.search(r"<title>(.*?)</title>", body, re.S)
                print(f"    title={title.group(1).strip()[:80] if title else '-'} "
                      f"先頭={body[:160]!r}")
        except Exception as e:
            print(f"[{label}] 例外: {e}")
        time.sleep(2)


if __name__ == "__main__":
    main()
