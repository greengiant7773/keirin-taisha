# keirin-taisha 引き継ぎメモ（2026-09-03）

## この文書の目的
競輪ボーダー自動配信システムの現状と、直近の未完了作業を引き継ぐ。
読む側は前提知識ゼロで良い。**推測で直さず、必ず実際の通信やログを見てから直す**こと。

---

## いま何が動いているか

GitHub Actions（リポジトリ `greengiant7773/keirin-taisha`）を cron-job.org から叩いて毎日自動実行。

| 時刻(JST) | job | 内容 |
|---|---|---|
| 6:00 | scrape | keirin.jp から全A級1516人のプロフィール取得 → `snapshots/YYYYMMDD.csv` |
| 7:30 | notepost | note に有料記事を自動投稿（keirin_note.py） |
| 8:00/10:00/15:30/19:30 | post | X に勝負駆け投稿（時間帯別） |
| 8:05/10:05/15:35/19:35 | alert | X に代謝危機の出走通知 |
| 日・水 20:00 | taisha | 代謝ボーダー投稿（GitHub schedule） |

失敗するとワークフローが赤になりGitHubからメールが届く。

## note投稿の仕組み（重要・全部実通信から確認済み）

`note_client.py` が非公式APIを叩く。手順:
1. `POST /api/v1/text_notes` → 数値ID と note_key を得る
2. `POST /api/v1/text_notes/draft_save?id=<数値ID>&is_temp_saved=true` → 本文保存
3. `PUT /api/v1/text_notes/<数値ID>` → 公開（有料設定・キャンペーンもここ）
4. `POST /api/v3/discount_campaigns/twitter/post_status {"note_key":...}` → noteがXへ投稿しリポスト割引が有効化

ハマりどころ（全部過去に踏んだ）:
- ヘッダー `X-Requested-With: XMLHttpRequest` 必須。無いと422
- 有料記事は `free_body`（無料部分）と `pay_body`（有料部分）**両方**に中身。`separator` は free_body の最終段落の id
- キャンペーンは `{"kind":"twitter_retweet","discounted_price":0,"twitter_status_body":"文面"}`
- `slug` は `slug-<note_key>`、`separator` を "" にすると500
- 記事タイトルは255字以内
- 連続投稿すると422「しばらく時間をあけて」→ 90秒×3回リトライ実装済み
- **記事のハッシュタグ（`hashtags`）は形式未解明**。`[{"hashtag":{"name":...}}]` は400。現在は空配列で送っている

## 今回の修正（2026-09-03、未アップロード）

問題: 7:30の自動投稿でXに告知は出たが、**記事URLとハッシュタグが付いていなかった**。
原因: noteの定型文はURL・タグを自動付与するが、`twitter_status_body` で文面を渡すとそのまま使われる。

修正内容:
- `keirin_note.py`: `NOTE_USER = "keirin_border2"` を追加。告知文に `{url}` と `#競輪 #勝負駆け #代謝ボーダー #note` を入れた
- `note_client.py`: `create_and_publish()` に `note_user` 引数追加。note_key 取得後に `{url}` を `https://note.com/<user>/n/<key>` に置換

**やること（ユーザーに依頼）:**
1. `note_client_2338.py` を keirin-taisha にアップロード → GitHub上で `note_client.py` にリネーム（先に既存 `note_client.py` を削除しないと同名衝突でリネーム不可）
2. `keirin_note_2338.py` も同様に `keirin_note.py` へ
3. 動作確認は翌朝7:30の自動実行で見る。当日中に試すなら `posts/_note_posted.log` から今日の日付行を消して Actions → keirin → Run workflow → `notepost`

## ファイルの扱いで過去に起きた事故
- 同名ファイルを何度も出力したら、ユーザーの端末で古い版がアップロードされた。**出力ファイル名には時刻を入れる**（`note_client_HHMM.py`）
- raw.githubusercontent.com はCDNキャッシュで数分〜十数分古い内容を返す。反映確認は GitHub の blob ページで行数を見る
- `scrape.py` の `today_jst()` が一度 `date.today()`（UTC）に戻されて日付ズレが起きた。日付関連は必ず `today_jst()` を使う。UTC 21:00 = JST 翌6:00 なので UTC基準だと朝のscrapeが前日ファイルに追記される

## 残タスク
- [ ] `note_client_1314.py` → `note_client.py`、`keirin_note_1314.py` → `keirin_note.py` にリネームしてアップロード（最優先）
      Xの告知文にURL・タグを入れる修正 + 記事タグの修正が入っている
- [x] note記事の `hashtags` の形式 → 解決（下記参照）
- [ ] リポジトリの不要ファイル削除: `note_client_0902.py`, `note_client_keirin.py`, `probe_race.py`（調査用、keirin.yml の probe ジョブも）
- [x] note上のテスト記事の削除 → 完了（2026-09-03）
- [ ] X投稿文をnoteが自動投稿するため、`keirin_note.py` 内の独自X投稿は不要（実装していない、そのままでよい）

## 触ってはいけないこと
- keirin.jp の出走表ページ。robots.txt で禁止。プロフィールページ（`/pc/racerprofile`）だけが許可されている。出走メンバーはプロフィールの「開催中のレース」欄から再構成している（`race.py`）
- 秘密情報（Cookie, APIキー）はユーザーが GitHub Secrets に入れる。AIは値を扱わない

---

## 記事ハッシュタグ（解決済み・2026-09-03）

正しい形式は**先頭に # を付けた文字列の配列**だった。実通信で確認済み。

```json
"hashtags": ["#テスト", "#形式"]
```

過去に送っていた `[{"hashtag":{"name":"競輪"}}]` は400になる。
`note_client.py` 側で `#` を自動付与するので、`keirin_note.py` の
`TAGS` には `["競輪", "勝負駆け", "代謝ボーダー"]` のように # なしで書いてよい。

判明させた手順（他のAPI仕様を調べるときも同じやり方が使える）:
1. `https://note.com/notes/new` を開く
2. 同じタブで `window.fetch` をフックし、PUT `/v1/text_notes/` のボディを溜める
3. そのタブのままタイトル・本文・タグを入れて公開
4. 溜めたボディを見る

**推測で直さないこと。** 過去にこの一件で4回外している。
