"""
今日の勝負駆け・代謝危機まとめを note に自動投稿する

  python keirin_note.py            … プレビューのみ
  python keirin_note.py --post     … 実際にnoteへ公開

X投稿(280字)では「他N名」と省略している当落線上の選手を、
noteでは全員・得点つきで載せるのが役割。
1日1記事。posts/_note_posted.log で二重投稿を防ぐ
（postsディレクトリはワークフローのコミット対象なのでログもそこに置く）。

レース番号・車番は出走表の取得を作ってから追加する予定。
"""

import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from border import rating, class_borders, floor2
from schedule import load_month, races_on
from shobugake import load_snapshot, riding_on
from taisha import load_master, apply_latest, judge, QUOTA
from note_client import NoteClient, NoteError

HERE = Path(__file__).parent
POSTED = HERE / "posts" / "_note_posted.log"

UP_SPAN = Decimal("0.50")     # 昇級: ラインから何点以内を載せるか(X投稿と同じ)
TAI_NEAR = Decimal("1.50")    # 代謝: ボーダーから何点以内まで載せるか
SITE_URL = "https://greengiant7773.github.io/keirin-taisha/"
JST = timezone(timedelta(hours=9))


def today_jst() -> date:
    return datetime.now(JST).date()


def collect(target: date):
    """今日の開催と、走る当落線上の選手を集める。"""
    kaisai = races_on(load_month(target.year, target.month), target)
    if not kaisai:
        return None

    snap = load_snapshot()

    # --- S級昇級ライン ---
    alive = [{**r, "rating": rating(Decimal(r["score"]), int(r.get("dq") or 0))}
             for r in snap if not r.get("retired") and r.get("score")]
    s_line = class_borders([{"grade": r["grade"], "score": r["rating"]}
                            for r in alive])["S級"]
    up_all = []
    for r in alive:
        if r["grade"] not in ("A1", "A2"):
            continue
        g = floor2(r["rating"] - s_line)
        if abs(g) <= UP_SPAN:
            up_all.append({**r, "gap": g})

    # --- 代謝ボーダー ---
    master = load_master()
    apply_latest(master)
    t_rows, t_border = judge(master)
    snap_by_no = {r["reg_no"].strip().zfill(6): r for r in snap}
    tai_all = []
    for r in t_rows:
        if t_border is not None and not r["in_danger"]:
            if r["avg"] - t_border > TAI_NEAR:
                continue
        s = snap_by_no.get(r["reg_no"])
        if s:
            tai_all.append({**r, "snap": s})

    # --- 時間帯ごとに割り付け ---
    slots = {}
    for k in kaisai:
        slots.setdefault(k.slot, []).append(k)

    sections = []
    for slot, ks in slots.items():
        venues = [k.jo for k in ks]
        label = "／".join(f"{k.jo}{k.grade}" for k in ks)
        up = [r for r in up_all if riding_on(r, target, venues)]
        tai = [r for r in tai_all if riding_on(r["snap"], target, venues)]
        if up or tai:
            up.sort(key=lambda r: r["gap"], reverse=True)
            sections.append({"slot": slot, "label": label,
                             "up": up, "tai": tai})

    return {"date": target, "s_line": s_line, "t_border": t_border,
            "sections": sections}


def build_article(d) -> tuple[str, str]:
    target = d["date"]
    title = f"【{target.month}/{target.day}】競輪 勝負駆け・代謝危機の出走まとめ"

    p = []
    p.append(f"{target.month}月{target.day}日の開催から、"
             f"S級昇級の当落線上と代謝(登録消除)ボーダー付近の選手をまとめました。"
             f"X(旧Twitter)では字数の都合で載せきれない全員分です。")
    p.append(f"S級昇級ライン: {d['s_line']}（A級上位200位）\n"
             f"A3代謝ボーダー: {d['t_border'] if d['t_border'] is not None else '未成立'}"
             f"（3期平均・下位{QUOTA}位）")

    for sec in d["sections"]:
        lines = [f"■ {sec['slot']}　{sec['label']}"]
        if sec["up"]:
            lines.append("▼S級昇級争い")
            for r in sec["up"]:
                g = r["gap"]
                gs = f"圏内+{g}" if g > 0 else ("同点" if g == 0 else f"あと{-g}")
                emoji = f" {r['form_emoji']}" if r.get("form_emoji") else ""
                lines.append(f"・{r['name']}({r['grade']}) "
                             f"{r['rating']}［{gs}］{emoji}")
        if sec["tai"]:
            lines.append("▼代謝危機")
            for r in sec["tai"]:
                if d["t_border"] is None:
                    st = ""
                elif r["in_danger"]:
                    st = f"消除圏内{r['rank']}位"
                else:
                    st = f"あと{r['avg'] - d['t_border']}で圏内"
                lines.append(f"・{r['name']} 3期平均{r['avg']}［{st}］")
        p.append("\n".join(lines))

    p.append(f"順位表・ボーダー推移はこちらに常設しています。\n{SITE_URL}")
    p.append("※JKA公式サイトの公開データを個人が自動集計した非公式情報です。"
             "級班の確定は公式発表をご確認ください。")
    return title, "\n\n".join(p)


def main() -> int:
    do_post = "--post" in sys.argv
    target = today_jst()
    stamp = f"{target:%Y%m%d}"

    POSTED.parent.mkdir(exist_ok=True)
    done = POSTED.read_text(encoding="utf-8").split() if POSTED.exists() else []
    if stamp in done:
        print(f"[info] {stamp} は投稿済み。スキップします")
        return 0

    d = collect(target)
    if d is None:
        print("[info] 本日は開催なし")
        return 0
    if not d["sections"]:
        print("[info] 本日は当落線上の出走なし。投稿スキップ")
        return 0

    title, body = build_article(d)
    print(f"--- {title} ({len(body)}字) ---\n{body}\n---")

    if not do_post:
        print("\nプレビューのみ。投稿するには --post を付けてください")
        return 0

    try:
        NoteClient().create_and_publish(title, body,
                                        hashtags=["競輪", "勝負駆け"])
    except NoteError as e:
        print(f"[error] note投稿に失敗: {e}")
        return 1

    with open(POSTED, "a", encoding="utf-8") as f:
        f.write(stamp + "\n")
    print("[ok] noteに公開しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
