"""
昇級 / 残留 のボーダー算出

規程の要点(A級3班):
  昇級  … その期の評価点(平均競走得点 - 失格点)の上位150名がA級2班へ
  残留  … 2期連続70点未満かつ3期平均70点未満の対象者のうち、下位30名が登録消除
  発表  … 次期の級班は例年4月・10月に公表される

代謝(3期平均)と違い、昇級は「その期の得点だけ」で決まる。
よって今期得点のスナップショットがあれば追加データなしで算出できる。
"""

from decimal import Decimal, ROUND_DOWN

PROMOTE_QUOTA = 150      # A3 -> A2
RELEGATE_LINE = Decimal("70.00")


def floor2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def promotion_border(scores: list[Decimal], quota: int = PROMOTE_QUOTA):
    """昇級ボーダー。得点降順に並べたときのquota番目の値。
    足りなければ None(全員が昇級圏)。"""
    s = sorted(scores, reverse=True)
    return s[quota - 1] if len(s) >= quota else None


def classify(score: Decimal, border: Decimal | None) -> str:
    """ボーダーに対する位置。同点は『超えていない』ので圏外扱い(規程に合わせる)。"""
    if border is None:
        return "圏内"
    if score > border:
        return "圏内"
    if score == border:
        return "同点"
    return "圏外"


def gap(score: Decimal, border: Decimal | None) -> Decimal | None:
    return None if border is None else floor2(score - border)


def needed_average(target: Decimal, total: Decimal, starts: int, remaining: int):
    """あと remaining 走で target に届くために必要な、残り走の平均点。
       (target*(starts+remaining) - total) / remaining
    出走回数が取れるようになったら勝負駆けの精度がここで上がる。"""
    if remaining <= 0:
        return None
    return floor2((target * (starts + remaining) - total) / remaining)


def shobugake_targets(riders: list[dict], span: Decimal = Decimal("1.50")) -> dict:
    """ボーダー付近の選手を『昇級争い』『残留争い』に振り分ける。
    riders: [{'reg_no','name','score'(Decimal), ...}]
    span:   ボーダーから何点以内を『争い』とみなすか"""
    scores = [r["score"] for r in riders]
    pb = promotion_border(scores)

    up, stay = [], []
    for r in riders:
        s = r["score"]
        if pb is not None and abs(s - pb) <= span:
            up.append({**r, "border": pb, "gap": gap(s, pb),
                       "state": classify(s, pb)})
        if abs(s - RELEGATE_LINE) <= span:
            stay.append({**r, "border": RELEGATE_LINE,
                         "gap": gap(s, RELEGATE_LINE),
                         "state": classify(s, RELEGATE_LINE)})

    up.sort(key=lambda x: x["score"], reverse=True)
    stay.sort(key=lambda x: x["score"])
    return {"promotion_border": pb, "up": up, "stay": stay}


if __name__ == "__main__":
    # 同点がボーダーに来たときの挙動を確認する
    sc = [Decimal(str(80 - i * 0.05)) for i in range(200)]
    b = promotion_border(sc)
    print("150位の値:", b)
    print("  1つ上:", classify(b + Decimal("0.01"), b))
    print("  同点  :", classify(b, b))
    print("  1つ下:", classify(b - Decimal("0.01"), b))

    # 残り3走で70.00に乗せるのに必要な平均
    print("\n12走で合計816.0(平均68.00)、残り3走で70.00に乗せるには:")
    print(" 必要平均 =", needed_average(Decimal("70.00"), Decimal("816.0"), 12, 3))


# ---------------------------------------------------------------- A級全体

DQ_PENALTY = Decimal("3")   # 失格1回につき評価点から3点引かれる


def rating(score: Decimal, dq: int = 0) -> Decimal:
    """評価点 = 平均競走得点 - 失格点。級班はこの値で決まる。"""
    return floor2(score - DQ_PENALTY * dq)


# S級へ上がる人数。A級は全班(A1/A2/A3)を得点順に並べた上位から選ばれるため、
# A2の選手がS級ラインに入ることもある。
S_QUOTA = 200

# 級班の定員(名簿の実数から。期ごとに多少変わるので毎回渡すのが正確)
DEFAULT_SIZES = {"A1": 504, "A2": 515, "A3": 497}


def class_borders(riders: list[dict], sizes: dict[str, int] | None = None) -> dict:
    """A級全体を得点順に並べ、S級/A1/A2の各下限(ライン)を返す。
    riders: [{'grade','score'(Decimal), ...}]"""
    sizes = sizes or DEFAULT_SIZES
    s = sorted(riders, key=lambda r: r["score"], reverse=True)
    n = len(s)

    out, pos = {}, 0
    for label, cnt in (("S級", S_QUOTA), ("A1", sizes["A1"]), ("A2", sizes["A2"])):
        pos += cnt
        out[label] = s[pos - 1]["score"] if pos <= n else None
    return out


def near_line(riders: list[dict], line: Decimal | None,
              span: Decimal = Decimal("0.50")) -> list[dict]:
    """ラインから span 点以内の選手を、ラインに近い順で返す。"""
    if line is None:
        return []
    out = [{**r, "border": line, "gap": floor2(r["score"] - line),
            "state": classify(r["score"], line)}
           for r in riders if abs(r["score"] - line) <= span]
    out.sort(key=lambda x: abs(x["gap"]))
    return out
