"""
X への投稿

  python post.py            … 明日分をプレビューするだけ(投稿しない)
  python post.py --post     … 実際に投稿する
  python post.py 8/20       … 指定日をプレビュー
  python post.py 8/20 --post

事故防止のため:
  - 既定はプレビュー。--post を付けたときだけ実際に投稿する
  - 投稿済みは posted.log に記録し、二度と投稿しない
  - 1回の実行で投稿できる本数に上限(MAX_PER_RUN)を設ける
  - URLを含む投稿は課金が跳ね上がるため、含んでいたら止める

必要なもの:
  pip install requests requests-oauthlib
  環境変数 X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_SECRET
"""

import os
import re
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import requests

API = "https://api.twitter.com/2/tweets"
HERE = Path(__file__).parent
OUTDIR = HERE / "posts"
LOG = HERE / "posted.log"

MAX_PER_RUN = 6          # 1回の実行で投稿する上限
X_LIMIT = 280            # 全角=2 で数えたときの上限


def x_len(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "FWA" else 1 for c in s)


def auth():
    from requests_oauthlib import OAuth1   # 投稿時だけ必要
    keys = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"]
    vals = [os.environ.get(k) for k in keys]
    missing = [k for k, v in zip(keys, vals) if not v]
    if missing:
        raise SystemExit("環境変数が未設定です: " + ", ".join(missing))
    return OAuth1(*vals)


def already_posted() -> set[str]:
    if not LOG.exists():
        return set()
    return {line.split("\t")[0] for line in
            LOG.read_text(encoding="utf-8").splitlines() if line.strip()}


def record(key: str, tweet_id: str) -> None:
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{key}\t{tweet_id}\n")


def check(text: str) -> str | None:
    """投稿してよいか。問題があれば理由を返す。"""
    if x_len(text) > X_LIMIT:
        return f"文字数超過 ({x_len(text)}/{X_LIMIT})"
    if re.search(r"https?://|[\w.-]+\.(com|jp|net|org)\b", text):
        # URL入りは1件$0.20と桁違いに高いので、意図しない混入を止める
        return "URLが含まれている(課金が跳ね上がるため中止)"
    if not text.strip():
        return "本文が空"
    return None


def send(text: str, oauth) -> str:
    r = requests.post(API, json={"text": text}, auth=oauth, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["data"]["id"]


def main(target: date, do_post: bool) -> None:
    files = sorted(OUTDIR.glob(f"{target:%Y%m%d}_*.txt"))
    if not files:
        print(f"{target:%m/%d} の投稿文がありません。先に shobugake.py を実行してください")
        return

    done = already_posted()
    oauth = auth() if do_post else None
    sent = 0

    for path in files:
        key = path.stem
        text = path.read_text(encoding="utf-8").strip()
        head = f"[{key}] {x_len(text)}字"

        if key in done:
            print(f"{head} … 投稿済みのためスキップ")
            continue
        ng = check(text)
        if ng:
            print(f"{head} … 中止: {ng}")
            continue
        if sent >= MAX_PER_RUN:
            print(f"{head} … 上限{MAX_PER_RUN}本に達したため見送り")
            continue

        if not do_post:
            print(f"\n{head} … プレビュー(未投稿)\n{'-' * 40}\n{text}\n{'-' * 40}")
            continue

        try:
            tid = send(text, oauth)
            record(key, tid)
            sent += 1
            print(f"{head} … 投稿しました  id={tid}")
        except Exception as e:
            print(f"{head} … 失敗: {e}")

    if not do_post:
        print(f"\n計{len(files)}本。実際に投稿するには --post を付けてください")
    else:
        print(f"\n{sent}本を投稿しました")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--post"]
    do_post = "--post" in sys.argv
    arg = args[0] if args else "1"
    if "/" in arg:
        m, d = map(int, arg.split("/"))
        t = date(date.today().year, m, d)
    else:
        t = date.today() + timedelta(days=int(arg))
    main(t, do_post)
