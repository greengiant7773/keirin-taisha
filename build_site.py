"""
静的サイト生成: docs/index.html を書き出す

  python build_site.py

内容:
  1. S級昇級ボーダー現況 + ライン±1.00点のランキング
  2. 代謝(登録消除)危機ランキング + 下位30位ライン
  3. 両ボーダーの推移(スナップショット全日分)

X投稿(280字)に載り切らない全体像を常設するのが役割。
scrape後・taisha後にActionsから呼ばれる。
"""

import csv
import html as H
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from border import rating, class_borders, classify, floor2
from taisha import load_master, judge, QUOTA

HERE = Path(__file__).parent
SNAPDIR = HERE / "snapshots"
DOCS = HERE / "docs"

SPAN = Decimal("1.00")          # 昇級表: ラインから何点以内を載せるか
JST = timezone(timedelta(hours=9))

# 競輪の枠番9色 (背景, 文字)。代謝危機の上位9名に使う
WAKU = [
    ("#FFFFFF", "#1A1917"), ("#1A1917", "#FFFFFF"), ("#D63A2F", "#FFFFFF"),
    ("#1E5AA8", "#FFFFFF"), ("#F2C500", "#1A1917"), ("#1E8A44", "#FFFFFF"),
    ("#E87C1E", "#1A1917"), ("#E8709E", "#1A1917"), ("#7B4FA6", "#FFFFFF"),
]


def load_snapshot(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def alive_rated(snap: list[dict]) -> list[dict]:
    out = []
    for r in snap:
        if r.get("retired") or not r.get("score"):
            continue
        out.append({**r, "rating": rating(Decimal(r["score"]),
                                          int(r.get("dq") or 0))})
    out.sort(key=lambda r: r["rating"], reverse=True)
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


def load_pref() -> dict[str, str]:
    out = {}
    p = HERE / "roster.csv"
    if not p.exists():
        return out
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        out[r["reg_no"].strip().zfill(6)] = r.get("pref", "")
    return out


def taisha_border_for(master: dict, snap_path: Path):
    """指定スナップショットで今期得点を上書きした代謝判定。"""
    m = {k: dict(v) for k, v in master.items()}
    for r in load_snapshot(snap_path):
        k = r["reg_no"].strip().zfill(6)
        if k in m:
            if r.get("retired"):
                m[k]["cur"] = ""
            elif r.get("score"):
                m[k]["cur"] = r["score"]
    return judge(m)


def collect() -> dict:
    snaps = sorted(SNAPDIR.glob("*.csv"))
    if not snaps:
        raise SystemExit("スナップショットがありません")
    latest = snaps[-1]
    pref = load_pref()
    master = load_master()

    riders = alive_rated(load_snapshot(latest))
    lines = class_borders([{"grade": r["grade"], "score": r["rating"]}
                           for r in riders])
    s_line = lines["S級"]

    up = []
    for r in riders:
        if r["grade"] not in ("A1", "A2"):
            continue
        g = floor2(r["rating"] - s_line)
        if abs(g) <= SPAN:
            up.append({"rank": r["rank"], "name": r["name"],
                       "grade": r["grade"],
                       "pref": pref.get(r["reg_no"].strip().zfill(6), ""),
                       "rating": r["rating"], "gap": g,
                       "state": classify(r["rating"], s_line),
                       "emoji": r.get("form_emoji") or ""})

    t_rows, t_border = taisha_border_for(master, latest)
    for r in t_rows:
        r["pref"] = pref.get(r["reg_no"], "")

    trend = []
    for p in snaps:
        rs = alive_rated(load_snapshot(p))
        ln = class_borders([{"grade": x["grade"], "score": x["rating"]}
                            for x in rs])["S級"]
        _, tb = taisha_border_for(master, p)
        d = p.stem
        trend.append({"date": f"{int(d[4:6])}/{int(d[6:8])}",
                      "s": ln, "t": tb})

    prev_s = trend[-2]["s"] if len(trend) >= 2 else None
    prev_t = trend[-2]["t"] if len(trend) >= 2 else None

    return {
        "updated": datetime.now(JST).strftime("%Y/%m/%d %H:%M"),
        "s_line": s_line,
        "s_diff": None if prev_s is None else floor2(s_line - prev_s),
        "up": up,
        "t_border": t_border,
        "t_diff": (None if (prev_t is None or t_border is None)
                   else floor2(t_border - prev_t)),
        "t_rows": t_rows,
        "trend": trend,
    }


# ---------------------------------------------------------------- 部品

def diff_tag(v) -> str:
    if v is None:
        return ""
    if v > 0:
        return f'<span class="diff upv">前回比 +{v}</span>'
    if v < 0:
        return f'<span class="diff dnv">前回比 {v}</span>'
    return '<span class="diff">前回比 ±0</span>'


def svg_trend(trend, key, color):
    pts = [(i, t[key]) for i, t in enumerate(trend) if t[key] is not None]
    if len(pts) < 2:
        return "<p class=note>データが2日分たまると推移が表示されます</p>"
    vals = [float(v) for _, v in pts]
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.25, 0.05)
    lo, hi = lo - pad, hi + pad
    W, HT, ML = 340, 130, 44

    def x(i): return ML + i * (W - ML - 10) / max(len(trend) - 1, 1)
    def y(v): return 14 + (HT - 36) * (hi - float(v)) / (hi - lo)

    path = " ".join(f"{'M' if j == 0 else 'L'}{x(i):.1f},{y(v):.1f}"
                    for j, (i, v) in enumerate(pts))
    dots = "".join(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.5" '
                   f'fill="{color}"/>' for i, v in pts)
    li, lv = pts[-1]
    n = len(trend)
    step = max(1, (n - 1) // 3)
    lab_idx = sorted({0, n - 1, *range(n - 1, -1, -step)})
    labels = "".join(
        f'<text x="{x(i):.1f}" y="{HT - 4}" class="ax">{trend[i]["date"]}</text>'
        for i in lab_idx)
    gy = [y(min(vals)), y(max(vals))]
    grid = "".join(f'<line x1="{ML}" y1="{g:.1f}" x2="{W-10}" y2="{g:.1f}" '
                   f'class="grid"/>' for g in gy)
    gl = (f'<text x="{ML-5}" y="{y(max(vals))+4:.1f}" class="ay">{max(vals):.2f}</text>'
          f'<text x="{ML-5}" y="{y(min(vals))+4:.1f}" class="ay">{min(vals):.2f}</text>')
    return (f'<svg viewBox="0 0 {W} {HT}" role="img" '
            f'preserveAspectRatio="xMidYMid meet">{grid}{gl}'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.2" '
            f'stroke-linecap="round"/>{dots}'
            f'<text x="{x(li):.1f}" y="{y(lv)-7:.1f}" text-anchor="end" '
            f'class="last" fill="{color}">{lv}</text>{labels}</svg>')


def up_tr(r) -> str:
    cls = "in" if r["state"] == "圏内" else ("tie" if r["state"] == "同点" else "out")
    g = r["gap"]
    gs = f"+{g}" if g > 0 else ("±0" if g == 0 else f"{g}")
    return (f'<tr class="{cls}"><td class="rk">{r["rank"]}</td>'
            f'<td class="nm">{H.escape(r["name"])}'
            f'<span class="sub">{r["grade"]}・{H.escape(r["pref"])}</span></td>'
            f'<td class="num">{r["rating"]}</td>'
            f'<td class="num gapv">{gs}</td>'
            f'<td class="em">{r["emoji"]}</td></tr>')


def up_band(s_line) -> str:
    return (f'<tr class="band"><td colspan="5">━ S級昇級ライン {s_line} ━'
            f'</td></tr>')


def up_rows(up, s_line, above=None, below=None) -> str:
    """above/below を指定すると帯の上下それぞれ n 行に絞る。"""
    ins = [r for r in up if r["gap"] >= 0]
    outs = [r for r in up if r["gap"] < 0]
    if above is not None:
        ins = ins[-above:]
    if below is not None:
        outs = outs[:below]
    return ("".join(up_tr(r) for r in ins) + up_band(s_line)
            + "".join(up_tr(r) for r in outs))


def taisha_tr(r, compact=False) -> str:
    if r["rank"] <= 9:
        bg, fg = WAKU[r["rank"] - 1]
        badge = (f'<span class="waku" style="background:{bg};color:{fg}">'
                 f'{r["rank"]}</span>')
    else:
        badge = f'<span class="rk">{r["rank"]}</span>'
    cls = "dgr" if r["in_danger"] else "safe"
    hist = ("" if compact else
            f'<td class="num hist">{r["t2"]}</td>')
    return (f'<tr class="{cls}"><td>{badge}</td>'
            f'<td class="nm">{H.escape(r["name"])}'
            f'<span class="sub">{H.escape(r.get("pref", ""))}</span></td>'
            f'<td class="num strong">{r["avg"]}</td>{hist}</tr>')


def taisha_band(border, compact=False) -> str:
    col = 3 if compact else 4
    return (f'<tr class="band bandR"><td colspan="{col}">━ 下位{QUOTA}位ライン '
            f'{border}（ここまで登録消除）━</td></tr>')


def taisha_rows(t_rows, border, limit=None, compact=False) -> str:
    rows = []
    src = t_rows if limit is None else t_rows[:limit]
    for r in src:
        rows.append(taisha_tr(r, compact))
        if border is not None and r["rank"] == QUOTA:
            rows.append(taisha_band(border, compact))
    return "".join(rows)


# ---------------------------------------------------------------- HTML

STYLE = """
:root {
  --paper:#FAF7F1; --sumi:#1A1917; --banka:#B98A5C; --keisen:#DCD3C4;
  --in:#1E6B3C; --out:#B03427; --sub:#6E675C;
}
* { box-sizing:border-box; margin:0; padding:0; }
body {
  background:var(--paper); color:var(--sumi);
  font-family:"Zen Kaku Gothic New",sans-serif; font-size:15px;
  line-height:1.6; -webkit-text-size-adjust:100%;
}
.wrap { max-width:760px; margin:0 auto; padding:0 14px 56px; }
header { padding:26px 0 8px; }
.brand {
  font-family:"Shippori Mincho B1",serif; font-weight:800;
  font-size:clamp(24px,6vw,36px); letter-spacing:.04em; line-height:1.2;
}
.brand a { color:inherit; text-decoration:none; }
.brand small {
  display:block; font-family:"Zen Kaku Gothic New",sans-serif;
  font-weight:500; font-size:13px; letter-spacing:.12em; color:var(--sub);
  margin-top:4px;
}
.gura { display:block; width:100%; height:14px; margin:12px 0 4px; }
.upd { font-size:12px; color:var(--sub); }
.plates { display:grid; grid-template-columns:1fr 1fr; gap:10px;
  margin:18px 0 6px; }
.plate { border:2px solid var(--sumi); background:#fff;
  padding:12px 14px 10px; }
.plate .lbl { font-size:11.5px; font-weight:700; letter-spacing:.06em; }
.plate .val { font-family:Oswald,sans-serif; font-weight:600;
  font-size:clamp(28px,8vw,42px); line-height:1.1; }
.plate .diff { font-size:11px; color:var(--sub); }
.diff.upv { color:var(--out); } .diff.dnv { color:var(--in); }
.plate.tai { border-color:var(--out); }
.plate.tai .lbl { color:var(--out); }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:22px;
  margin-top:30px; }
@media (max-width:600px) { .cols { grid-template-columns:1fr; } }
section h2 {
  font-family:"Shippori Mincho B1",serif; font-weight:800; font-size:19px;
  letter-spacing:.05em; border-left:6px solid var(--banka); padding-left:10px;
}
section.tai h2 { border-left-color:var(--out); }
.lede { font-size:12px; color:var(--sub); margin:6px 0 10px; }
table { width:100%; border-collapse:collapse; background:#fff;
  border:1.5px solid var(--sumi); }
th { font-size:10.5px; font-weight:700; letter-spacing:.08em;
  color:var(--sub); text-align:left; padding:6px 7px;
  border-bottom:1.5px solid var(--sumi); background:#F3EEE4; }
td { padding:6px 7px; border-bottom:1px solid var(--keisen);
  vertical-align:middle; }
tr:last-child td { border-bottom:none; }
.rk { font-family:Oswald,sans-serif; font-weight:500; font-size:14px;
  color:var(--sub); }
.nm { font-weight:700; white-space:nowrap; font-size:13.5px; }
.sub { display:block; font-size:10px; font-weight:400; color:var(--sub);
  letter-spacing:.04em; }
.num { font-family:Oswald,sans-serif; font-weight:500; font-size:15px;
  text-align:right; white-space:nowrap; }
.hist { font-size:11.5px; color:var(--sub); }
.strong { font-weight:600; font-size:16px; }
.em { text-align:center; font-size:14px; }
tr.in .gapv { color:var(--in); }
tr.out .gapv { color:var(--out); }
tr.tie .gapv { color:var(--banka); }
tr.band td { background:var(--sumi); color:var(--paper); text-align:center;
  font-weight:700; font-size:11.5px; letter-spacing:.1em; padding:7px;
  border-bottom:none; }
tr.band.bandR td { background:var(--out); }
tr.safe td { color:var(--sub); }
tr.safe .nm { font-weight:500; }
.waku { display:inline-flex; align-items:center; justify-content:center;
  width:22px; height:22px; border:1.5px solid var(--sumi);
  font-family:Oswald,sans-serif; font-weight:600; font-size:13px; }
.morelink { display:block; text-align:center; margin-top:10px;
  border:2px solid var(--sumi); background:#fff; color:var(--sumi);
  font-weight:700; font-size:13.5px; letter-spacing:.08em;
  padding:9px 6px; text-decoration:none; }
.morelink:hover { background:var(--sumi); color:var(--paper); }
.legend { font-size:11px; color:var(--sub); margin-top:8px; }
svg { width:100%; height:auto; display:block; background:#fff;
  border:1.5px solid var(--sumi); margin-top:12px; }
svg .ax { font:9px "Zen Kaku Gothic New"; fill:var(--sub);
  text-anchor:middle; }
svg .ay { font:9px Oswald; fill:var(--sub); text-anchor:end; }
svg .grid { stroke:var(--keisen); stroke-width:1; stroke-dasharray:3 4; }
svg .last { font:600 12px Oswald; }
.note { font-size:12px; color:var(--sub); padding:12px; background:#fff;
  border:1.5px solid var(--sumi); margin-top:10px; }
.back { display:inline-block; margin:14px 0 0; font-size:13px;
  font-weight:700; color:var(--sumi); }
footer { margin-top:44px; font-size:12px; color:var(--sub);
  border-top:1.5px solid var(--keisen); padding-top:14px; }
footer a { color:var(--sumi); font-weight:700; }
"""

GURA = ('<svg class="gura" viewBox="0 0 720 14" preserveAspectRatio="none" '
        'aria-hidden="true"><path d="M0 7 Q 15 1, 30 7'
        + " ".join(f"T {x} 7" for x in range(60, 721, 30))
        + '" fill="none" stroke="#B98A5C" stroke-width="2"/></svg>')

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?family=Shippori+'
         'Mincho+B1:wght@700;800&family=Zen+Kaku+Gothic+New:wght@400;500;700'
         '&family=Oswald:wght@500;600&display=swap" rel="stylesheet">')


def page(title, desc, body, updated, home=False) -> str:
    brand = ("KEIRIN BORDER" if home
             else '<a href="./">KEIRIN BORDER</a>')
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
{FONTS}
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1 class="brand">{brand}
    <small>S級昇級ライン・代謝ボーダー 自動集計</small></h1>
  {GURA}
  <p class="upd">最終更新 {updated} JST ／ 毎朝の公式データ取得後に自動更新 ／ ※非公式・個人集計</p>
</header>
{body}
<footer>
  <p>KEIRIN BORDER ─ JKA公式サイトの公開データを個人が自動集計した非公式ページです。級班の確定は公式発表をご確認ください。</p>
  <p style="margin-top:6px">毎日の勝負駆けアラートはXで → <a href="https://x.com/greengiant7773">@greengiant7773</a></p>
</footer>
</div>
</body>
</html>"""


def render_index(d) -> str:
    n_up = len(d["up"])
    n_t = len(d["t_rows"])
    n_danger = sum(1 for r in d["t_rows"] if r["in_danger"])
    t_border = d["t_border"] if d["t_border"] is not None else "未成立"
    body = f"""
<div class="plates">
  <div class="plate">
    <p class="lbl">S級昇級ライン（A級上位200位）</p>
    <p class="val">{d["s_line"]}</p>
    {diff_tag(d["s_diff"])}
  </div>
  <div class="plate tai">
    <p class="lbl">A3代謝ボーダー（3期平均・下位{QUOTA}位）</p>
    <p class="val">{t_border}</p>
    {diff_tag(d["t_diff"])}
  </div>
</div>

<div class="cols">
<section>
  <h2>S級昇級ボーダー</h2>
  <p class="lede">評価点＝平均競走得点−失格点。ライン前後の当落線上。</p>
  <table>
    <thead><tr><th>順位</th><th>選手</th><th>評価点</th><th>差</th><th>調子</th></tr></thead>
    <tbody>{up_rows(d["up"], d["s_line"], above=6, below=6)}</tbody>
  </table>
  <a class="morelink" href="up.html">ライン±1.00点 全{n_up}名を見る →</a>
  {svg_trend(d["trend"], "s", "#B98A5C")}
</section>

<section class="tai">
  <h2>代謝危機ランキング</h2>
  <p class="lede">3期平均の下位{QUOTA}名が登録消除。対象{n_t}名・圏内{n_danger}名。</p>
  <table>
    <thead><tr><th>順位</th><th>選手</th><th>3期平均</th></tr></thead>
    <tbody>{taisha_rows(d["t_rows"], d["t_border"], limit=12, compact=True)}</tbody>
  </table>
  <a class="morelink" href="taisha.html">対象{n_t}名すべて見る →</a>
  {svg_trend(d["trend"], "t", "#B03427")}
</section>
</div>
"""
    return page("KEIRIN BORDER｜S級昇級ライン・代謝ボーダー",
                "競輪のS級昇級ラインと代謝ボーダーをJKA公式データから毎日自動集計。非公式・個人集計。",
                body, d["updated"], home=True)


def render_up(d) -> str:
    body = f"""
<section style="margin-top:26px">
  <h2>S級昇級ボーダーランキング</h2>
  <p class="lede">評価点（平均競走得点−失格点）でA級全班を並べた上位200名がS級へ。ライン±{SPAN}点の{len(d["up"])}名を全体順位つきで掲載。🚀は直近好調、🥺は不調。</p>
  <table>
    <thead><tr><th>順位</th><th>選手</th><th>評価点</th><th>ライン差</th><th>調子</th></tr></thead>
    <tbody>{up_rows(d["up"], d["s_line"])}</tbody>
  </table>
  <a class="back" href="./">← トップへ戻る</a>
</section>
"""
    return page("S級昇級ボーダーランキング｜KEIRIN BORDER",
                "競輪S級昇級ライン付近の全選手ランキング。毎日自動更新・非公式。",
                body, d["updated"])


def render_taisha(d) -> str:
    n_danger = sum(1 for r in d["t_rows"] if r["in_danger"])
    body = f"""
<section class="tai" style="margin-top:26px">
  <h2>代謝危機ランキング</h2>
          <p class="lede">男子A3で直近2期連続70点未満かつ3期平均70点未満が対象。3期平均の下位{QUOTA}名が登録消除。対象{len(d["t_rows"])}名。「前期」は2026前期の得点。</p>
  <table>
    <thead><tr><th>順位</th><th>選手</th><th>3期平均</th><th>前期</th></tr></thead>
    <tbody>{taisha_rows(d["t_rows"], d["t_border"])}</tbody>
  </table>
  <p class="legend">□ 枠番色の1〜9位はもっとも消除に近い9名。ライン帯より下は現時点で消除を免れている選手。</p>
  <a class="back" href="./">← トップへ戻る</a>
</section>
"""
    return page("代謝危機ランキング｜KEIRIN BORDER",
                "競輪A3代謝ボーダー（登録消除ライン）対象選手の全ランキング。毎日自動更新・非公式。",
                body, d["updated"])


def main() -> None:
    d = collect()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(render_index(d), encoding="utf-8")
    (DOCS / "up.html").write_text(render_up(d), encoding="utf-8")
    (DOCS / "taisha.html").write_text(render_taisha(d), encoding="utf-8")
    print(f"docs/ に3ページ書き出しました "
          f"(昇級 {len(d['up'])}人 / 代謝 {len(d['t_rows'])}人)")


if __name__ == "__main__":
    main()
