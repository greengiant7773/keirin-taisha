"""
note.com 非公式APIクライアント

note.comは公式の投稿APIを公開していない。
以下は 2026/08 時点で、ブラウザの実際の通信を観察して判明した仕様。
note側の変更で動かなくなる前提で使うこと（失敗はメール通知される）。

投稿の流れ（ブラウザと同じ手順を踏む必要がある）:
  1. POST /api/v1/text_notes            … 空の下書きを作り、数値IDを得る
  2. POST /api/v1/text_notes/draft_save?id=<数値ID>&is_temp_saved=true
                                        … タイトルと本文を保存
  3. PUT  /api/v1/text_notes/<数値ID>            … 公開

ハマりどころ:
  - ヘッダーに X-Requested-With: XMLHttpRequest が必須。無いと422になる。
  - 本文はHTML。段落ごとに <p name="UUID" id="UUID"> が要る。
  - body_length はタグを除いた実テキストの文字数。
  - draft_save に "status" は不要。公開時のPUTでは逆に必須。
  - /publish というエンドポイントは存在しない（404になる）。

準備:
  ブラウザでnoteにログインし、Cookie の _note_session_v5 の値を
  GitHub Secrets に NOTE_SESSION_COOKIE として保存する。
"""

import os
import re
import time
import uuid

import requests

NOTE_BASE = "https://note.com/api"
COOKIE_NAME = "_note_session_v5"


def to_note_html(text: str) -> tuple[str, int]:
    """プレーンテキストをnoteの本文HTMLに変換し、(html, 文字数) を返す。

    空行で段落を分ける。各段落にUUIDを振るのがnoteの仕様。
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    parts = []
    for b in blocks:
        u = str(uuid.uuid4())
        inner = b.replace("\n", "<br>")
        parts.append(f'<p name="{u}" id="{u}">{inner}</p>')
    html = "".join(parts)
    length = len(re.sub(r"<[^>]+>", "", html))
    return html, length


class NoteError(RuntimeError):
    """note API がエラーを返したときに投げる。メール通知の判定に使う。"""


class NoteClient:
    def __init__(self, session_cookie=None):
        session_cookie = session_cookie or os.environ.get("NOTE_SESSION_COOKIE")
        if not session_cookie:
            raise NoteError("NOTE_SESSION_COOKIE が設定されていない")

        self.session = requests.Session()
        self.session.cookies.set(COOKIE_NAME, session_cookie, domain=".note.com")
        self.session.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/128.0.0.0 Safari/537.36"),
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://editor.note.com",
            "Referer": "https://editor.note.com/",
        })

    def _post(self, path, **kw):
        resp = self.session.post(f"{NOTE_BASE}{path}", **kw)
        if not resp.ok:
            raise NoteError(f"POST {path} が {resp.status_code}: {resp.text[:300]}")
        try:
            return resp.json()
        except ValueError:
            return {}

    def create_empty_draft(self):
        """空の下書きを作り、(数値ID, noteキー) を返す。

        公開時の slug に "slug-<noteキー>" が必要なので、キーも返す。
        noteキーは n から始まる英数字（例: nacbb4756185d）で、数値IDとは別物。
        """
        data = self._post("/v1/text_notes", json={})
        d = data.get("data", data)
        note_id = d.get("id") or d.get("note_id")
        note_key = d.get("key")
        if not note_id:
            raise NoteError(f"下書きIDが取得できなかった: {str(data)[:300]}")
        return int(note_id), note_key

    def save_draft(self, note_id: int, title: str, text: str) -> None:
        """下書きにタイトルと本文を保存する。"""
        html, length = to_note_html(text)
        self._post(
            "/v1/text_notes/draft_save",
            params={"id": note_id, "is_temp_saved": "true"},
            json={"body": html, "body_length": length, "name": title,
                  "index": False, "is_lead_form": False},
        )

    def publish(self, note_id: int, title: str, text: str,
                note_key: str = "", hashtags=None, price: int = 0) -> dict:
        """下書きを公開する。

        公開は POST /publish ではなく PUT /v1/text_notes/<id>。
        （/publish は404。ブラウザの通信を見て判明した）

        price を 1以上にすると有料記事になる。その場合 free_body に
        無料で読める部分、pay_body に有料部分を入れる必要があるが、
        ここでは全文無料（price=0）を既定にしている。
        """
        html, length = to_note_html(text)
        # ブラウザが実際に送っている形に厳密に合わせる。
        # separator を "" に、slug を "" にすると 500 になるので注意。
        payload = {
            "author_ids": [],
            "body_length": length,
            "disable_comment": False,
            "exclude_from_creator_top": False,
            "exclude_ai_learning_reward": False,
            "free_body": html,
            "hashtags": [{"hashtag": {"name": h}} for h in (hashtags or [])],
            "image_keys": [],
            "index": False,
            "is_refund": False,
            "limited": False,
            "magazine_ids": [],
            "magazine_keys": [],
            "name": title,
            "pay_body": "",
            "price": price,
            "send_notifications_flag": True,
            "separator": None,
            "slug": f"slug-{note_key}" if note_key else "",
            "status": "published",
            "circle_permissions": [],
            "discount_campaigns": [],
            "lead_form": {"is_active": False, "consent_url": ""},
            "line_add_friend": {"is_active": False, "keyword": "",
                                "add_friend_url": ""},
            "pro_coupon_keys": [],
        }
        resp = self.session.put(f"{NOTE_BASE}/v1/text_notes/{note_id}",
                                json=payload)
        if not resp.ok:
            raise NoteError(
                f"PUT /v1/text_notes/{note_id} が {resp.status_code}: "
                f"{resp.text[:300]}")
        try:
            return resp.json()
        except ValueError:
            return {}

    def create_and_publish(self, title: str, text: str,
                           hashtags=None, price: int = 0,
                           retries: int = 3, wait: int = 90) -> dict:
        """下書き作成→保存→公開まで通しで行う。

        noteは連続投稿を422「しばらく時間をあけて」で弾く。
        その場合は同じ下書きに対して待ってから公開だけ再試行する
        （下書きを作り直さないので、ゴミ下書きが残らない）。
        """
        note_id, note_key = self.create_empty_draft()
        self.save_draft(note_id, title, text)
        for attempt in range(retries + 1):
            try:
                return self.publish(note_id, title, text, note_key=note_key,
                                    hashtags=hashtags, price=price)
            except NoteError as e:
                msg = str(e)
                is_rate = ("しばらく時間" in msg) or (" 422" in msg)
                if attempt < retries and is_rate:
                    print(f"[wait] 連続投稿制限。{wait}秒待って再試行 "
                          f"({attempt + 1}/{retries})")
                    time.sleep(wait)
                    continue
                raise
