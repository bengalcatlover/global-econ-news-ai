{# ================================================================
   article_template.md — 記事ドラフトテンプレート（Jinja2形式）
   InfoBank ベトナム経済メディア向け 編集者用下書きフォーマット
   ================================================================ #}
---
生成日時: {{ generated_at }}
記事ID: {{ article_id }}
トピック: {{ topics | join(" / ") }}
ファクトチェック信頼度: **{{ factcheck.label }}** — {{ factcheck.description }}
推奨カテゴリ: **{{ infobank_category.category_id }}**（{{ infobank_category.category_name_ja }}）
---

# 記事ドラフト

> **注意: このファイルはAIが生成した下書きです。掲載前に必ず編集者によるレビューと修正が必要です。**

---

## タイトル案（{{ title_candidates | length }}候補）

{% for title in title_candidates %}
{{ loop.index }}. {{ title }}
{% endfor %}

---

## 本文ドラフト

{{ body_draft }}

---

## InfoBankカテゴリ提案

> InfoBankの既存カテゴリ体系に基づいて最適なカテゴリを自動判定しました。
> 編集者が最終確認のうえ、CMSに登録してください。

| 項目 | 内容 |
|------|------|
| 推奨カテゴリ | **{{ infobank_category.category_id }}**（{{ infobank_category.category_name_ja }}） |
| 判定信頼度 | {{ infobank_category.confidence }} |
| 判定理由 | {{ infobank_category.reason }} |
{% if infobank_category.alternatives %}
| 次点候補 | {% for alt in infobank_category.alternatives %}{{ alt }}（{{ infobank_all_categories.get(alt, {}).get('name_ja', alt) }}）{% if not loop.last %}、{% endif %}{% endfor %} |
{% endif %}

### 全カテゴリ一覧（参照用）

| カテゴリID | 日本語名 |
|-----------|---------|
{% for cat_id, cat_info in infobank_all_categories.items() %}
| {{ cat_id }} | {{ cat_info.name_ja }} |
{% endfor %}

---

## ファクトチェック注記

| 項目 | 内容 |
|------|------|
| 信頼度ラベル | **{{ factcheck.label }}** |
| 評価 | {{ factcheck.description }} |
| 参照ソース数 | {{ factcheck.source_count }}件 |
| 確認日時 | {{ factcheck.verified_at }} |

{% if factcheck.issues %}
### 検出された問題点

{% for issue in factcheck.issues %}
- ⚠️ {{ issue }}
{% endfor %}
{% else %}
ファクトチェックで特筆すべき問題は検出されませんでした。
{% endif %}

---

## 編集者確認ポイント

> 以下の箇所は特に注意して確認・修正してください。
> ベトナム固有名詞の表記揺れ・初出時の括弧書き有無も合わせて確認してください。

{% if editor_checkpoints %}
{% for point in editor_checkpoints %}
- [ ] {{ point }}
{% endfor %}
{% else %}
- [ ] 特筆すべき確認事項はありません（通常レビューを実施してください）
{% endif %}

---

## 使用ソース一覧

{% for src in sources %}
{{ src.index }}. **{{ src.name }}**
   - URL: {{ src.url }}
   {% if src.published %}
   - 公開日: {{ src.published }}
   {% endif %}
{% endfor %}

---

## 元記事情報（参照用）

- **元タイトル（英語）:** {{ original_title }}
- **元記事リンク:** {{ original_link }}

---

*このドラフトは編集者の作業効率化を目的として自動生成されました。*
*内容の正確性・掲載可否の最終判断は必ず編集者が行ってください。*
