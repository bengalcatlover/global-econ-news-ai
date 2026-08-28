"""
記事ドラフト生成モジュール — InfoBank ベトナム経済メディア向け

設計思想：
  「完全自動生成」ではなく「編集者の作業を効率化する下書き生成」ツール。
  AIは素材を整理・構造化するが、最終判断は必ず人間の編集者が行う。
  ファクトチェック注記と編集確認ポイントを明示することで、
  編集者がどこに注力すべきかを一目で把握できる設計にする。

InfoBank固有の要件：
  - タイトルは「ベトナム」を含むスタイルに統一
  - ベトナム固有名詞は初出時にベトナム語/英語を併記
  - INFOBANK_CATEGORIESから最適なカテゴリを自動提案
  - 記事本文は800〜1500字の日本語
"""

import json
import os
from datetime import datetime
from pathlib import Path

import openai
from jinja2 import Environment, FileSystemLoader

from config import OPENAI_API_KEY, ARTICLE_CONFIG, INFOBANK_CATEGORIES, OUTPUT_DIR

# OpenAI クライアントを初期化
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Jinja2 テンプレートエンジンを初期化（templates/ ディレクトリを参照）
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_jinja_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ─────────────────────────────────────────────
# 1. タイトル案生成（InfoBankスタイル準拠）
# ─────────────────────────────────────────────

def generate_title_candidates(article_data: dict, n: int = 3) -> list[str]:
    """
    ファクトチェック済みデータをもとにInfoBankスタイルのタイトル案を複数生成する。

    InfoBankのタイトル傾向：
      - 「ベトナム」を含む or 先頭に置く
      - 具体的な数値・固有名詞を入れる（例：「126件」「24億ドル超」）
      - テーマを明確に示す（M&A、農業、エネルギーなど）
      例：「ベトナム農業から生まれる炭素市場とカーボンクレジット」
          「ベトナムM&A、2026年上期126件で総額24億ドル超」

    Args:
        article_data: collector.py + ファクトチェッカーが出力した記事データ
        n: 生成するタイトル候補数（デフォルト3）

    Returns:
        タイトル候補のリスト
    """
    original_title = article_data.get("title", "")
    summary = article_data.get("summary", "")
    topics = ", ".join(article_data.get("topics", ["経済"]))

    prompt = f"""以下のベトナム経済ニュースをもとに、InfoBankという日本語ベトナム経済メディア向けの
記事タイトル案を{n}つ考えてください。

【元タイトル（英語）】
{original_title}

【内容要約】
{summary}

【トピック分類】
{topics}

InfoBankのタイトルルール：
- 「ベトナム」を含む、または先頭に置く（必須）
- 具体的な数値・固有名詞を盛り込む（例：「126件」「24億ドル超」「ビングループ」）
- 40字以内で収める
- センセーショナルすぎず、事実に忠実に
- 参考例：
  「ベトナム農業から生まれる炭素市場とカーボンクレジット」
  「ベトナムM&A、2026年上期126件で総額24億ドル超」
  「ベトナム、再生可能エネルギー投資が前年比30%増」

タイトルのみを1行ずつ番号付きで出力してください。"""

    response = client.chat.completions.create(
        model=ARTICLE_CONFIG["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=300,
    )

    raw = response.choices[0].message.content.strip()

    # 番号付きリストをパースしてリストに変換
    titles = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # "1. タイトル" → "タイトル" に変換
        if line[0].isdigit() and len(line) > 2 and line[1] in (".", "。", "）", ")"):
            line = line[2:].strip()
        titles.append(line)

    return titles[:n]


# ─────────────────────────────────────────────
# 2. 本文ドラフト生成（800〜1500字・固有名詞併記）
# ─────────────────────────────────────────────

def generate_body_draft(article_data: dict) -> str:
    """
    ベトナム経済記事の本文ドラフトを生成する。
    文字数は800〜1500字（InfoBankの標準的な記事量）。
    ベトナム固有名詞は初出時にベトナム語/英語を併記する。

    固有名詞の表記ルール（例）：
      ビングループ（Vingroup）、ハノイ（Hanoi）、
      ホーチミン市（Ho Chi Minh City）、ビンファスト（VinFast）

    Args:
        article_data: ファクトチェック済み記事データ

    Returns:
        Markdown形式の本文ドラフト文字列
    """
    title = article_data.get("title", "")
    summary = article_data.get("summary", "")
    sources = article_data.get("sources", [article_data.get("source", "不明")])
    links = article_data.get("links", [article_data.get("link", "")])
    topics = ", ".join(article_data.get("topics", []))

    # ソース情報を番号付きで整形してプロンプトに渡す
    source_list = "\n".join(
        f"  [{i+1}] {src}（{lnk}）"
        for i, (src, lnk) in enumerate(zip(sources, links))
    )

    prompt = f"""以下のベトナム経済ニュースを、日本語の記事本文ドラフト（800〜1500字）に変換してください。

【元タイトル】
{title}

【内容要約】
{summary}

【情報ソース（番号付き）】
{source_list}

【トピック】
{topics}

出力ルール：
- 日本語で自然な経済記事らしい文体（です・ます調）
- 文字数は800〜1500字を目安にする（短くなりすぎないよう注意）
- ベトナム固有名詞は初出時に「日本語読み（英語/ベトナム語）」の形式で併記する
  例：ビングループ（Vingroup）、ハノイ（Hà Nội）、ホーチミン市（TP.HCM）
  例：国家銀行（Ngân hàng Nhà nước）、ビンファスト（VinFast）
- 事実として確認されている情報のみを記述
- 不確かな情報は「〜との見方もある」「〜と報じられている」など断定を避ける表現を使う
- ソースを引用するときは [1] [2] のような脚注番号を文中に入れる
- 段落は3〜4に分け、各段落に小見出しは付けない
- 見出し・タイトルは含めない（本文のみ）
- 背景・文脈も含めてベトナム経済全体の中での位置づけを説明する"""

    response = client.chat.completions.create(
        model=ARTICLE_CONFIG["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,   # 低めにして事実の歪みを抑える
        max_tokens=1800,   # 1500字対応のためトークン数を増やす
    )

    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────
# 3. 編集者確認ポイント抽出
# ─────────────────────────────────────────────

def extract_editor_checkpoints(article_data: dict, body_draft: str) -> list[str]:
    """
    編集者が重点的に確認すべき箇所を列挙する。
    数値・固有名詞・不確かな記述など、見落としやすいリスクをピックアップ。
    ベトナム固有名詞の表記揺れチェックも含む。

    Args:
        article_data: ファクトチェック済み記事データ
        body_draft: 生成した本文ドラフト

    Returns:
        確認ポイントのリスト（文字列）
    """
    factcheck = article_data.get("factcheck", {})
    confidence = factcheck.get("confidence_label", "C")  # A/B/C
    issues = factcheck.get("issues", [])

    prompt = f"""以下のベトナム経済記事ドラフトを読んで、編集者が確認・修正すべき箇所を箇条書きで列挙してください。

【記事ドラフト】
{body_draft}

【ファクトチェック信頼度ラベル】: {confidence}
【既知の問題点】: {json.dumps(issues, ensure_ascii=False)}

確認ポイントとして挙げるべき内容の例：
- 数値・パーセンテージ・日付の正確性
- ベトナム固有名詞（企業名・地名・人名・機関名）の表記揺れや漢字変換ミス
- ベトナム語/英語の併記漏れ（初出の固有名詞に括弧書きがあるか）
- 断定表現になっているが一次ソースで確認が必要な箇所
- 読者が誤解しそうな表現
- 最新情報として追記が必要な可能性がある箇所
- InfoBankのトーン（中立・ビジネス寄り）に合っていない表現

出力：
- 箇条書き（- で始める）
- 1行ずつ、具体的に（「〜の数値を確認してください」など）
- 「問題なし」の場合は「特筆すべき確認事項はありません」と1行だけ出力"""

    response = client.chat.completions.create(
        model=ARTICLE_CONFIG["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=600,
    )

    raw = response.choices[0].message.content.strip()

    # 箇条書きをパースしてリストに変換
    checkpoints = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-").strip()
        if line:
            checkpoints.append(line)

    return checkpoints


# ─────────────────────────────────────────────
# 4. ファクトチェック注記の整形
# ─────────────────────────────────────────────

def format_factcheck_notes(article_data: dict) -> dict:
    """
    ファクトチェック結果を記事テンプレート向けに整形する。
    信頼度ラベル A/B/C の意味を人間が読みやすい形式に変換する。

    信頼度ラベル定義：
      A: 複数の信頼できるソースで確認済み
      B: 1ソースのみ、または確認中の情報あり
      C: 未確認情報含む、または情報が古い可能性あり

    Args:
        article_data: ファクトチェック済み記事データ

    Returns:
        テンプレートに渡す整形済み辞書
    """
    factcheck = article_data.get("factcheck", {})
    label = factcheck.get("confidence_label", "C")

    label_descriptions = {
        "A": "複数の信頼できるソースで確認済み（掲載推奨）",
        "B": "情報の一部が未確認。該当箇所を編集者が要確認",
        "C": "未確認情報または古い情報を含む可能性あり。掲載前に一次ソース確認必須",
    }

    label_colors = {
        "A": "green",
        "B": "orange",
        "C": "red",
    }

    return {
        "label": label,
        "description": label_descriptions.get(label, "不明"),
        "color_hint": label_colors.get(label, "gray"),
        "source_count": len(article_data.get("sources", [article_data.get("source")])),
        "issues": factcheck.get("issues", []),
        "verified_at": factcheck.get("verified_at", datetime.utcnow().isoformat()),
    }


# ─────────────────────────────────────────────
# 5. InfoBankカテゴリの自動提案
# ─────────────────────────────────────────────

def suggest_category(article_data: dict) -> dict:
    """
    記事の内容をもとにINFOBANK_CATEGORIESから最適なカテゴリを提案する。
    キーワードマッチングとAIによる判定を組み合わせて精度を高める。

    Args:
        article_data: 記事データ（title・summary・topicsを参照）

    Returns:
        {
            "category_id": str,      # カテゴリキー（例："economy"）
            "category_name_ja": str, # 日本語カテゴリ名（例："経済"）
            "confidence": str,       # "high" / "medium" / "low"
            "alternatives": list,    # 次点候補（category_idのリスト）
        }
    """
    title = article_data.get("title", "").lower()
    summary = article_data.get("summary", "").lower()
    text = f"{title} {summary}"

    # ── Step 1: キーワードマッチングでスコアリング ──
    scores: dict[str, int] = {}
    for cat_id, cat_info in INFOBANK_CATEGORIES.items():
        score = sum(1 for kw in cat_info["keywords"] if kw in text)
        if score > 0:
            scores[cat_id] = score

    # ── Step 2: スコア上位カテゴリをAIに最終判定させる ──
    # 上位3カテゴリをAIに渡してより正確な判定を求める
    top_candidates = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
    candidate_info = "\n".join(
        f"  - {cat_id}（{INFOBANK_CATEGORIES[cat_id]['name_ja']}）: スコア{sc}"
        for cat_id, sc in top_candidates
    ) or "  （マッチなし）"

    # 全カテゴリリストをAIに提示
    all_categories = "\n".join(
        f"  {cat_id}: {info['name_ja']}"
        for cat_id, info in INFOBANK_CATEGORIES.items()
    )

    prompt = f"""以下のベトナム経済ニュースに最も適切なInfoBankカテゴリを1つ選んでください。

【記事タイトル】
{article_data.get("title", "")}

【内容要約】
{article_data.get("summary", "")}

【利用可能なカテゴリ一覧】
{all_categories}

【キーワードマッチング上位候補】
{candidate_info}

出力フォーマット（JSONのみ、余計な説明不要）：
{{
  "category_id": "カテゴリキー",
  "confidence": "high または medium または low",
  "reason": "選定理由（1行）",
  "alternatives": ["次点のカテゴリキー1", "次点のカテゴリキー2"]
}}"""

    response = client.chat.completions.create(
        model=ARTICLE_CONFIG["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,   # カテゴリ判定は揺らぎを最小化
        max_tokens=200,
    )

    raw = response.choices[0].message.content.strip()

    # JSONをパース（失敗時はキーワードスコア1位にフォールバック）
    try:
        result = json.loads(raw)
        cat_id = result.get("category_id", "economy")
        return {
            "category_id": cat_id,
            "category_name_ja": INFOBANK_CATEGORIES.get(cat_id, {}).get("name_ja", "経済"),
            "confidence": result.get("confidence", "low"),
            "reason": result.get("reason", ""),
            "alternatives": result.get("alternatives", []),
        }
    except (json.JSONDecodeError, KeyError):
        # フォールバック: スコア最高のカテゴリを使用
        fallback_id = top_candidates[0][0] if top_candidates else "economy"
        return {
            "category_id": fallback_id,
            "category_name_ja": INFOBANK_CATEGORIES.get(fallback_id, {}).get("name_ja", "経済"),
            "confidence": "low",
            "reason": "キーワードマッチングによる自動判定",
            "alternatives": [c for c, _ in top_candidates[1:3]],
        }


# ─────────────────────────────────────────────
# 6. ソース一覧の整形
# ─────────────────────────────────────────────

def format_sources(article_data: dict) -> list[dict]:
    """
    使用ソースを番号付きリスト形式に整形する。

    Args:
        article_data: 記事データ

    Returns:
        {"index": int, "name": str, "url": str, "published": str} のリスト
    """
    sources = article_data.get("sources", [article_data.get("source", "不明")])
    links = article_data.get("links", [article_data.get("link", "")])
    published = article_data.get("published", "")

    formatted = []
    for i, (name, url) in enumerate(zip(sources, links), start=1):
        formatted.append({
            "index": i,
            "name": name,
            "url": url,
            "published": published,
        })

    return formatted


# ─────────────────────────────────────────────
# 7. テンプレートを使って記事ドラフトを出力
# ─────────────────────────────────────────────

def render_article(
    article_data: dict,
    template_name: str = "article_template.md",
) -> str:
    """
    Jinja2テンプレートを使って記事ドラフト全体を文字列にレンダリングする。
    各パーツ（タイトル・本文・カテゴリ提案・ファクトチェック注記など）を組み合わせる。

    Args:
        article_data: ファクトチェック済み記事データ
        template_name: templates/ ディレクトリ内のテンプレートファイル名

    Returns:
        レンダリング済みの記事ドラフト（Markdown文字列）
    """
    print(f"  [生成] タイトル候補を生成中...")
    titles = generate_title_candidates(article_data)

    print(f"  [生成] 本文ドラフトを生成中...")
    body = generate_body_draft(article_data)

    print(f"  [生成] 編集者確認ポイントを抽出中...")
    checkpoints = extract_editor_checkpoints(article_data, body)

    print(f"  [生成] InfoBankカテゴリを判定中...")
    category = suggest_category(article_data)

    factcheck_notes = format_factcheck_notes(article_data)
    sources = format_sources(article_data)

    # テンプレートに渡すコンテキストを構築
    context = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "original_title": article_data.get("title", ""),
        "original_link": article_data.get("link", ""),
        "topics": article_data.get("topics", []),
        "title_candidates": titles,
        "body_draft": body,
        "editor_checkpoints": checkpoints,
        "factcheck": factcheck_notes,
        "sources": sources,
        "article_id": article_data.get("id", "unknown"),
        # InfoBank固有: カテゴリ提案情報
        "infobank_category": category,
        "infobank_all_categories": INFOBANK_CATEGORIES,
    }

    template = _jinja_env.get_template(template_name)
    return template.render(**context)


# ─────────────────────────────────────────────
# 8. ファイルへの保存
# ─────────────────────────────────────────────

def save_draft(rendered: str, article_id: str, output_dir: str = OUTPUT_DIR) -> str:
    """
    レンダリング済みドラフトをMarkdownファイルとして保存する。
    OUTPUT_DIR/drafts/ に日時つきファイル名で保存する。

    Args:
        rendered: render_article() の返り値
        article_id: 記事のユニークID（ファイル名に使用）
        output_dir: 保存先ディレクトリ（デフォルト: config.py の OUTPUT_DIR）

    Returns:
        保存したファイルの絶対パス
    """
    # drafts/ サブディレクトリに保存
    drafts_dir = os.path.join(output_dir, "drafts")
    os.makedirs(drafts_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"draft_{article_id}_{timestamp}.md"
    path = os.path.join(drafts_dir, filename)

    with open(path, "w", encoding="utf-8") as f:
        f.write(rendered)

    print(f"  [保存] {path}")
    return path


# ─────────────────────────────────────────────
# 9. メイン処理：記事リストを一括処理
# ─────────────────────────────────────────────

def generate_drafts(articles: list[dict], max_count: int = None) -> list[str]:
    """
    ファクトチェック済み記事リストを受け取り、ドラフトを一括生成・保存する。
    編集者向け下書きを OUTPUT_DIR/drafts/ に保存する。

    Args:
        articles: ファクトチェック済み記事データのリスト
        max_count: 生成上限数（None の場合は config.py の max_articles_per_run を使用）

    Returns:
        保存したファイルパスのリスト
    """
    limit = max_count or ARTICLE_CONFIG["max_articles_per_run"]
    targets = articles[:limit]

    print(f"\n--- 記事ドラフト生成開始（{len(targets)}件 / 上限{limit}件）---")

    saved_paths = []
    for i, article in enumerate(targets, start=1):
        print(f"\n[{i}/{len(targets)}] {article.get('title', '（タイトル不明）')[:60]}")
        try:
            rendered = render_article(article)
            path = save_draft(rendered, article.get("id", f"article{i}"))
            saved_paths.append(path)
        except Exception as e:
            print(f"  [エラー] 生成失敗: {e}")

    print(f"\n--- 完了: {len(saved_paths)}件のドラフトを生成 ---")
    return saved_paths


# ─────────────────────────────────────────────
# 動作確認用スタブ（単体実行時）
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # ダミーデータでモジュール単体の動作を確認する（ベトナム経済ネタ）
    sample_article = {
        "id": "test001",
        "title": "Vietnam M&A Deals Reach 126 Transactions Worth Over $2.4 Billion in H1 2026",
        "link": "https://e.vnexpress.net/example-ma-article",
        "summary": (
            "Vietnam's mergers and acquisitions market recorded 126 deals "
            "with a total value exceeding $2.4 billion in the first half of 2026, "
            "driven by foreign investors targeting real estate and retail sectors. "
            "Vingroup and Masan Group were among the most active domestic participants."
        ),
        "source": "VnExpress International",
        "sources": ["VnExpress International", "Vietnam Investment Review"],
        "links": [
            "https://e.vnexpress.net/example-ma-article",
            "https://vir.com.vn/example-ma-article",
        ],
        "published": "2026-08-28T18:00:00",
        "topics": ["M&A・企業買収"],
        # ファクトチェッカーが付与する想定のフィールド
        "factcheck": {
            "confidence_label": "A",
            "issues": [],
            "verified_at": "2026-08-28T19:00:00",
        },
    }

    print("=== article_generator.py 単体テスト（InfoBank向け） ===\n")

    # 各関数を個別に確認
    print("[1] タイトル候補生成（InfoBankスタイル）")
    titles = generate_title_candidates(sample_article)
    for t in titles:
        print(f"  - {t}")

    print("\n[2] 本文ドラフト生成（800〜1500字、固有名詞併記）")
    body = generate_body_draft(sample_article)
    char_count = len(body.replace(" ", "").replace("\n", ""))
    print(f"  文字数（空白除く）: {char_count}字")
    print(body[:300] + "..." if len(body) > 300 else body)

    print("\n[3] 編集者確認ポイント抽出")
    checkpoints = extract_editor_checkpoints(sample_article, body)
    for cp in checkpoints:
        print(f"  - {cp}")

    print("\n[4] InfoBankカテゴリ提案")
    category = suggest_category(sample_article)
    print(f"  推奨カテゴリ: {category['category_id']}（{category['category_name_ja']}）")
    print(f"  信頼度: {category['confidence']} / 理由: {category['reason']}")
    print(f"  次点候補: {category['alternatives']}")

    print("\n[5] テンプレートレンダリング & 保存")
    rendered = render_article(sample_article)
    path = save_draft(rendered, sample_article["id"])
    print(f"  → {path}")
