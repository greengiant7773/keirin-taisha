"""
競輪 代謝ボーダー / 勝負駆け 集計スクリプト

使い方:
  python scrape.py test          … 1人だけ取得してHTMLを保存(最初にこれ)
  python scrape.py               … 全員取得してスナップショット作成
  python scrape.py judge         … 保存済みデータから代謝判定

必要なもの:
  pip install requests beautifulsoup4
"""

import csv
import re
import sys
import time
from datetime import date
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from results import parse_recent, recent_form

# ---------------------------------------------------------------- 設定

BASE = "https://keirin.jp/pc/racerprofile?snum={}"
WAIT = 1.0          # リクエスト間隔(秒)。公式に負荷をかけないため短くしない
TIMEOUT = 20

HERE = Path(__file__).parent
ROSTER = HERE / "roster.csv"
SNAPDIR = HERE / "snapshots"
DEBUG = HERE / "debug.html"

HEADERS = {
    "User-Agent": "keirin-taisha-bot/0.1 (personal research; low frequency)"
}

TEST_ID = "012618"   # 武智尚之。今期得点66.11、出場予定3件が入っている選手


# ---------------------------------------------------------------- 取得

def fetch(reg_no: str) -> str:
    r = requests.get(BASE.format(reg_no), headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding      # 文字化け対策
    return r.text


# ---------------------------------------------------------------- 解析

def parse(html: str) -> dict:
    """プロフィールから必要な項目だけ抜く。
    ページ構造が変わると壊れるので、失敗時は None を返して呼び出し側で弾く。"""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    out = {
        "name": None,
        "grade": None,
        "score": None,       # 今期得点
        "entries": [],       # 出場予定 [(開催場, 開始, 終了), ...]
        "racing_now": "",    # 開催中のレースの開催場
        "starts": 0,         # 今期の出走回数
        "dq": 0,             # 今期の失格等の回数
        "form_emoji": "",    # 直近5走の絶好調(🚀)/不調(🥺)バッジ
        "form_avg": None,    # 直近5走の平均着順(参考値)
        "retired": False,
    }

    # 引退表記
    if "引退" in text and re.search(r"引退(され|し)ました", text):
        out["retired"] = True

    # 級班: 'Ａ級３班' のような全角表記
    m = re.search(r"([ＳSAＡ]級[０-９0-9１-９]班|Ｓ級Ｓ班)", text)
    if m:
        out["grade"] = normalize_grade(m.group(1))

    # 今期得点
    out["score"] = extract_score(soup, text)

    # 開催中のレース: '■開催中のレース　富山Ｆ２' のように場名だけが入る。
    # 出場予定には載らないので別に拾う(本日出走の判定に必要)。
    m2 = re.search(r"開催中のレース\s*\n?\s*([^\n]{1,12}?)[ＦFＧG][ＩI１２2３3]", text)
    if m2:
        jo = m2.group(1).replace("　", "").strip()
        if jo and "出場しており" not in jo:
            out["racing_now"] = jo

    # 今期の出走回数と失格回数(「最近の成績」の着順アイコンから数える)
    rec = parse_recent(soup)
    out["starts"] = rec["starts"]
    out["dq"] = rec["dq"]

    form = recent_form(soup)
    out["form_emoji"] = form["emoji"]
    out["form_avg"] = form["avg5"]

    # 級班の履歴情報: [(級班, 年月日), ...] 新しい順
    out["grade_history"] = extract_grade_history(text)

    # 出場予定: '伊東 Ｆ２  09/02～09/04' のような行。開催場も一緒に拾う
    sect = text.split("出場予定")
    if len(sect) > 1:
        block = sect[1][:400]
        for mm in re.finditer(
                r"([^\s\n]+?)\s*[ＦFＧG][ＩI１２2３3ＩI]*\s*\n?\s*"
                r"(\d{2}/\d{2})\s*[～~]\s*(\d{2}/\d{2})", block):
            jo = mm.group(1).replace("　", "").strip()
            out["entries"].append((jo, mm.group(2), mm.group(3)))
        if not out["entries"]:      # 開催場が取れない書式なら日付だけ
            for mm in re.finditer(r"(\d{2}/\d{2})\s*[～~]\s*(\d{2}/\d{2})", block):
                out["entries"].append(("", mm.group(1), mm.group(2)))

    out["today_race"] = extract_today_race(text)
    return out


def extract_today_race(text: str) -> str:
    """開催中のレースから「会場,日付,レース番号」を取る。

    プロフィールに「■開催中のレース」という節があり、
        平F2  08/30 08/31 09/01
        A級チャ予選/4R  A級チャ準決/5R
    のように、日付の並びとレースの並びが対応している。
    日付とレースの個数が合わない書式もあるので、その時は空にする。

    戻り値は "平F2@08/31/5R" の形。取れなければ空文字。
    """
    m = re.search(r"開催中のレース(.{0,300})", text, re.S)
    if not m:
        return ""
    block = m.group(1)

    head = re.match(r"\s*([^\s]+?[ＦFＧG][ＩI１２2３3ＩI]*)", block)
    jo = head.group(1) if head else ""

    days = re.findall(r"(\d{2}/\d{2})", block)
    races = re.findall(r"/(\d{1,2})[RＲ]", block)
    # 未確定の日があると個数が合わないので、先頭から対応させる
    if not days or not races:
        return ""

    return ";".join(f"{jo}@{d}/{r}R" for d, r in zip(days, races))


SCORE_RE = re.compile(r"^\d{1,3}\.\d{2}$")


def extract_score(soup: BeautifulSoup, text: str):
    """今期得点を取る。
    ページ構造は「見出し行 / 値行」の2段組で、見出しと値は同じ列に並ぶ:
        期別 | 級班 | 級班所属日 | 次期級班 | 脚質 | 今期得点
        70期 | Ａ級３班 | 2024/07/01 | - | 追 | 66.11
    そこで『今期得点』セルの列番号を調べ、次の行の同じ列を読む。
    表として読めなかった場合だけ、テキストから拾う方式にフォールバックする。"""

    # --- 方法1: 表の列位置で拾う(本命) ---
    for cell in soup.find_all(["th", "td"]):
        if cell.get_text(strip=True) != "今期得点":
            continue
        row = cell.find_parent("tr")
        if row is None:
            continue
        idx = [c for c in row.find_all(["th", "td"])].index(cell)
        nxt = row.find_next_sibling("tr")
        if nxt is None:
            continue
        cells = nxt.find_all(["th", "td"])
        if idx < len(cells):
            v = cells[idx].get_text(strip=True)
            if SCORE_RE.match(v):
                return Decimal(v)
            return None          # '-' や空欄 = 今期未出走

    # --- 方法2: 見出し以降の狭い範囲から最初の得点らしき数値を拾う ---
    pos = text.find("今期得点")
    if pos >= 0:
        window = text[pos:pos + 120]      # 値行の右端までは届き、次の節までは行かない幅
        m = re.search(r"\b(\d{1,3}\.\d{2})\b", window)
        if m:
            return Decimal(m.group(1))
    return None


def extract_grade_history(text: str) -> list[tuple[str, str]]:
    """級班の履歴情報。過去にA2だった期があるかの判定に使う。"""
    pos = text.find("級班の履歴情報")
    if pos < 0:
        return []
    block = text[pos:pos + 300]
    out = []
    for m in re.finditer(r"([ＳSAＡ]級[０-９0-9]班|Ｓ級Ｓ班)\s*\n?\s*(\d{4}/\d{2}/\d{2})", block):
        out.append((normalize_grade(m.group(1)), m.group(2)))
    return out


def normalize_grade(s: str) -> str:
    z2h = str.maketrans("ＳＡ０１２３４５６７８９", "SA0123456789")
    s = s.translate(z2h)
    m = re.search(r"([SA])級([S0-9])班", s)
    return f"{m.group(1)}{m.group(2)}" if m else s


# ---------------------------------------------------------------- 名簿

def load_roster() -> list[dict]:
    with open(ROSTER, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def targets(roster: list[dict], grades: list[str]) -> list[dict]:
    """巡回対象を級班で絞る。
    代謝判定(A3)は3期分の履歴が要るが、昇級判定はその期の得点だけなので
    新人も含めて全員を取る。"""
    return [r for r in roster if r["grade"] in grades]


# ---------------------------------------------------------------- モード

def mode_test() -> None:
    print(f"テスト取得: {TEST_ID}")
    html = fetch(TEST_ID)
    DEBUG.write_text(html, encoding="utf-8")
    print(f"HTMLを保存しました -> {DEBUG}  ({len(html):,} 文字)")

    got = parse(html)
    print("\n--- 読み取り結果 ---")
    print(f"級班      : {got['grade']}")
    print(f"今期得点  : {got['score']}")
    print(f"出場予定  : {got['entries']}")
    print(f"開催中    : {got.get('racing_now') or '(なし)'}")
    print(f"今期出走  : {got.get('starts')}走  失格等 {got.get('dq')}回")
    print(f"直近の調子: {got.get('form_emoji') or '(判定対象外)'}  "
          f"平均着順{got.get('form_avg')}")
    print(f"級班履歴  : {got.get('grade_history')}")
    print(f"引退      : {got['retired']}")
    # 得点は開催のたびに動くので固定値では判定しない。
    # 「今期得点 × 出走回数」が整数になるかで、両方の取得が正しいか検算する。
    ok = []
    ok.append(("級班", got["grade"] == "A3"))
    ok.append(("今期得点", got["score"] is not None))
    ok.append(("出場予定", len(got["entries"]) > 0))
    ok.append(("出走回数", got.get("starts", 0) > 0))
    if got["score"] is not None and got.get("starts"):
        total = got["score"] * got["starts"]
        ok.append((f"検算(合計{total})", total == total.to_integral_value()))

    print()
    for name, good in ok:
        print(f"  {'OK ' if good else 'NG '} {name}")
    if all(g for _, g in ok):
        print("\n→ すべて正常。本番を実行できます。")
    else:
        print("\n→ NGあり。debug.html を渡してパーサーを直します。")


def mode_scrape(grades: list[str]) -> None:
    roster = load_roster()
    tg = targets(roster, grades)
    print(f"級班: {'/'.join(grades)}")
    SNAPDIR.mkdir(exist_ok=True)
    outfile = SNAPDIR / f"{date.today():%Y%m%d}.csv"

    # 中断しても続きから再開できるようにする
    done = set()
    if outfile.exists():
        with open(outfile, encoding="utf-8-sig", newline="") as f:
            done = {row["reg_no"] for row in csv.DictReader(f)}
        print(f"再開: {len(done)}件は取得済み")

    todo = [r for r in tg if r["reg_no"] not in done]
    print(f"対象 {len(tg)}人 / 今回取得 {len(todo)}人  (間隔{WAIT}秒)")
    print(f"想定所要時間: 約{len(todo) * WAIT / 60:.0f}分\n")

    new = not outfile.exists()
    with open(outfile, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["reg_no", "name", "grade", "score", "entries",
                        "racing_now", "today_race", "starts", "dq", "form_emoji",
                        "form_avg", "retired"])

        for i, r in enumerate(todo, 1):
            try:
                got = parse(fetch(r["reg_no"]))
                w.writerow([
                    r["reg_no"], r["name"], got["grade"] or "",
                    got["score"] if got["score"] is not None else "",
                    ";".join(f"{jo}@{a}-{b}" for jo, a, b in got["entries"]),
                    got.get("racing_now", ""),
                    got.get("today_race", ""),
                    got.get("starts", 0),
                    got.get("dq", 0),
                    got.get("form_emoji", ""),
                    got.get("form_avg") if got.get("form_avg") is not None else "",
                    "1" if got["retired"] else "",
                ])
                f.flush()
                mark = "" if got["score"] is not None else "  ← 得点なし"
                print(f"[{i}/{len(todo)}] {r['reg_no']} {r['name']} {got['score']}{mark}")
            except Exception as e:
                print(f"[{i}/{len(todo)}] {r['reg_no']} {r['name']} 失敗: {e}")
            time.sleep(WAIT)

    print(f"\n完了 -> {outfile}")


def mode_judge() -> None:
    """スナップショット + 過去2期の初期値から代謝判定"""
    hist = HERE / "history.csv"     # reg_no, t1(2025後期), t2(2026前期)
    if not hist.exists():
        print(f"{hist} がありません。")
        print("reg_no,t1,t2 の形式で過去2期の得点を用意してください。")
        return

    snaps = sorted(SNAPDIR.glob("*.csv"))
    if not snaps:
        print("スナップショットがありません。先に python scrape.py を実行してください。")
        return
    latest = snaps[-1]
    print(f"使用データ: {latest.name} + {hist.name}\n")

    past = {}
    with open(hist, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            past[row["reg_no"].zfill(6)] = (row["t1"], row["t2"])

    cands = []
    with open(latest, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            reg = row["reg_no"]
            if row["retired"] or not row["score"] or reg not in past:
                continue
            t1, t2 = past[reg]
            if not t1 or not t2:
                continue
            a, b, c = Decimal(t1), Decimal(t2), Decimal(row["score"])
            # 直近2期が連続で70点未満、かつ3期平均も70点未満
            if b < 70 and c < 70:
                avg = ((a + b + c) / 3).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                if avg < 70:
                    cands.append((avg, reg, row["name"], row["entries"]))

    cands.sort()
    print(f"代謝対象者 {len(cands)}人\n")
    for i, (avg, reg, name, ent) in enumerate(cands, 1):
        nxt = ent.split(";")[0] if ent else "予定なし"
        print(f"{i:3d}位  {avg}  {name}({reg})  次走 {nxt}")

    if len(cands) >= 30:
        print(f"\nボーダー(30位): {cands[29][0]}")
    else:
        print(f"\n対象者が30人未満のため、ボーダー未成立")


# ---------------------------------------------------------------- 入口

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "test":
        mode_test()
    elif arg == "judge":
        mode_judge()
    elif arg == "all":
        mode_scrape(["A1", "A2", "A3"])
    elif arg in ("A1", "A2", "A3"):
        mode_scrape([arg])
    else:
        mode_scrape(["A3"])
