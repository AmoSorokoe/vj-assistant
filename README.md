# VJ Assistant Simple Web v0.3

PCブラウザ向け。前のNext.js版を簡略化して、基本は `index.html` 1枚にまとめた版です。

## 機能

### ① セトリ画像解析
- 画像ドラッグ&ドロップ
- 日本語 + 英語OCR
- OCR前に自動拡大 / グレースケール / コントラスト補正
- 2パターンでOCRして、より多く文字が取れた結果を採用
- 曲名 / アーティストを直接修正
- 認識漏れは「＋空白曲を追加」
- 各曲の間にも空白曲を差し込み可能
- YouTube検索
- 準備済チェック
- ブラウザに結果を保存

### ② フロア曲リアルタイム認識
- PCの音声入力を選択
- 9秒周期で録音
- AudDへ送信
- NOW PLAYING表示
- YouTube検索
- 履歴

## 一番簡単な使い方

### セトリOCRだけ試す
`index.html` をChromeで開けば画面自体は表示できます。

ただし、ブラウザの音声入力は `file://` では正常に動かない場合があります。
LIVE認識まで使うならVercelへ公開してください。

## Vercelへ公開

1. このフォルダをGitHubリポジトリへアップロード
2. VercelでそのGitHubリポジトリをImport
3. Vercelの Project Settings → Environment Variables
4. 次を追加

```
AUDD_API_TOKEN=あなたのAudD APIキー
```

5. Deploy

以後はVercelが発行したURLをChromeで開くだけです。

## フォルダ構成

```
vj-assistant-simple/
├─ index.html
├─ api/
│  └─ recognize.js
├─ vercel.json
└─ README.md
```

## 推奨音声接続

```
DJミキサー REC OUT / BOOTH OUT
        ↓
USBオーディオインターフェース
        ↓
PC
        ↓
Chrome
```
