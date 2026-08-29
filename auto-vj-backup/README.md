# AUTO VJ BACKUP MVP

YouTube-VJをメインで使いながら、裏で常に現在曲を認識・検索・同期しておくバックアップVJです。

## MVPでできること

- DJミキサー / オーディオIFの入力を常時監視
- AudDで曲名・アーティスト・timecodeを認識
- 同じ曲なら定期的に再生位置を補正
- 新曲候補はすぐYouTube検索を開始
- 曲変更は連続認識で確定して誤切替を減らす
- YouTube候補を自動選択してミュート再生
- HOT STANDBY: 裏で常時READYまで準備
- FULL AUTO: 曲変更時にNEXT表示を挟んで次のMVへ切替
- TAKE / FULLSCREEN、RESYNC、NEXT TEST

## 重要

このMVPは同期コアの検証版です。SynapseRackへのSpout出力はまだ未実装です。
現段階では `AUTO VJ OUTPUT` ウィンドウを別ソースとして扱い、同期精度と動画選択精度を確認します。

## Windowsで起動

1. Python 3.11以降を入れる
2. `auto-vj-backup` フォルダを開く
3. `run_windows.bat` をダブルクリック
4. 初回だけ必要パッケージが自動インストールされる
5. Audio inputでDJミキサー / オーディオIFの入力を選択
6. AudD API tokenを入力
7. `START HOT STANDBY`

設定は `config.json` にローカル保存され、GitHubにはコミットされません。
環境変数 `AUDD_API_TOKEN` がある場合はそちらを優先します。

## 推奨配線

DJ Mixer REC OUT / MASTER 2 / USB Audio
→ PC Audio Input
→ AUTO VJ BACKUP
→ AUTO VJ OUTPUT
→ 将来 Spout
→ SynapseRack

普段の映像経路はこれまで通り:

YouTube-VJ
→ SynapseRack
→ Screen

AUTO VJ側は裏で常時同期させ、YouTube-VJが間に合わない時だけSynapseRack側でAUTO VJソースへ切り替える想定です。

## モード

### HOT STANDBY

- 曲を常時認識
- MVを自動検索
- 裏で同期再生
- 曲変更時も自動で次の映像へ更新
- NEXT演出は出さない

### FULL AUTO

- HOT STANDBYの動作に加えて、曲変更時にNEXTを表示
- NEXT → 次曲MV → 同期再生
- 単体VJとして使う想定

## 初期値

- 認識に使う音声: 7秒
- 通常認識間隔: 7秒
- 新曲候補の再確認: 3秒
- 曲変更確定: 2回連続認識
- 自動同期: 0.75秒以上ズレた場合にseek

認識間隔を短くすると切替は速くなりますが、AudD APIの利用回数も増えます。

## 次に実装するもの

1. Spout出力
2. MIDI TAKE / YouTube-VJへ戻す操作
3. NEXT.mp4 / 汎用VJ素材の登録
4. MV候補5件からの手動修正と曲→MV対応DB
5. ローカルMV最優先検索
6. BPM / pitch変化に対する継続同期
7. YouTube埋め込み不可動画の自動除外
