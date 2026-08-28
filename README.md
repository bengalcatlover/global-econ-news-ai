# InfoBank ベトナム経済ニュース AI パイプライン

ベトナム経済ニュースの **情報収集** と **ファクトチェック** を自動化するツール。

メディア運営で最も時間を要する「ソース収集」「裏取り」「数値確認」をAIで高速化し、
編集者が本来注力すべき記事の質向上・取材・分析に時間を使えるようにする。

## このツールが解決する課題

| 従来の手作業 | このツールで自動化 |
|---|---|
| ベトナム現地メディアを巡回して情報収集 | RSS自動収集（VnExpress, Vietnam News, VietnamNet等 8ソース） |
| 同じニュースが複数ソースにあるか確認 | 重複除去 + 複数ソース自動マッチング |
| 数値（GDP、FDI、VND為替等）の正確性を原文で照合 | AI数値抽出 + ソース間矛盾自動検出 |
| ファクトチェック結果をまとめる | 信頼度ラベル（A/B/C）付きレポート自動生成 |
| 英語記事から日本語の記事下書きを作成 | AI記事ドラフト生成（InfoBankカテゴリ提案+編集者確認ポイント付き） |

## 処理フロー

```
① 収集（collector.py）
   ベトナム現地RSS → 重複除去 → InfoBank 15カテゴリに自動分類 → JSON保存

② ファクトチェック（factchecker.py）
   複数ソース突合 → ベトナム経済指標の数値矛盾検出 → 信頼度スコアリング → レポート生成

③ 記事ドラフト生成（article_generator.py）
   チェック済みデータ → 日本語ドラフト → InfoBankカテゴリ提案 → テンプレート出力

④ 一括実行（pipeline.py）
   ①→②→③ をコマンド一発で実行、処理時間を記録
```

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .env に OPENAI_API_KEY を設定
```

## 使い方

### 全工程を一括実行
```bash
python pipeline.py
```

### オプション
```bash
# 収集のみ（ファクトチェック・ドラフト生成なし）
python pipeline.py --collect-only

# ファクトチェックまで（ドラフト生成なし）
python pipeline.py --no-drafts

# 過去48時間のニュースを対象に
python pipeline.py --hours 48

# 記事ドラフトの生成数を制限
python pipeline.py --max-articles 3

# 既に収集済みのJSONから再開
python pipeline.py --input output/news_20260828_120000.json
```

### モジュール単体での利用
```python
# 収集だけ
from collector import collect_news, save_to_json
articles = collect_news(max_age_hours=24)
save_to_json(articles)

# ファクトチェックだけ
from factchecker import run_factcheck
report, clusters = run_factcheck(articles)

# ドラフト生成だけ
from article_generator import generate_drafts
paths = generate_drafts(articles, max_count=3)
```

## InfoBank カテゴリ自動分類

収集した記事をInfoBankの既存15カテゴリに自動分類：

| カテゴリ | スラッグ |
|---|---|
| 経済 | economy |
| 政治 | politics |
| 食品・外食 | food |
| 卸・小売 | retail |
| サービス | service |
| 医療・ヘルスケア | medical |
| 電力・エネルギー | power-energy |
| 物流・倉庫 | logistics |
| 自動車 | automobile |
| 不動産・建設 | real-estate |
| 農業 | agri |
| 二輪車 | motor-bike |
| 税務・会計 | taxation |
| 法律・法務 | legal |
| 人事労務 | human-resources-and-labor-affairs |

## ファクトチェック信頼度ラベル

| ラベル | 意味 | 編集者の対応 |
|---|---|---|
| **A** | 複数ソース確認済み・数値矛盾なし | そのまま使用可（通常レビューのみ） |
| **B** | 単一ソースだが信頼メディア（VnExpress等） | 該当箇所を要確認 |
| **C** | 未確認・矛盾あり・古い情報 | 一次ソース確認必須 |

## 出力ファイル

```
output/
├── news_YYYYMMDD_HHMMSS.json         # 収集した生データ
├── factcheck_YYYYMMDD_HHMMSS.json    # ファクトチェック結果（JSON）
├── factcheck_YYYYMMDD_HHMMSS.txt     # ファクトチェック結果（テキスト）
└── drafts/
    └── draft_XXXXX_YYYYMMDD_HHMMSS.md  # 記事ドラフト（Markdown）
```

## カスタマイズ

- **収集ソースの追加**: `config.py` の `RSS_FEEDS` にフィードURLを追加
- **カテゴリ変更**: `config.py` の `INFOBANK_CATEGORIES` を編集
- **出力フォーマット変更**: `templates/article_template.md` を編集
- **AIモデル変更**: `config.py` の `ARTICLE_CONFIG["model"]` を変更

## 拡張例（継続開発で対応可能）

- 定期自動実行（cron / スケジューラ連携）
- WordPress API連携（記事ドラフトの直接投稿）
- ベトナム政府統計局（GSO）公式データとの自動照合
- Slack / メール通知連携
- ベトナム語ソースの直接翻訳対応

## 技術スタック

- Python 3.12
- feedparser / BeautifulSoup（ニュース収集）
- OpenAI GPT-4o-mini（ファクトチェック・翻訳・記事生成）
- Jinja2（テンプレートエンジン）
