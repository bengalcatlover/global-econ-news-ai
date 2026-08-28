"""
factchecker.py — ファクトチェックモジュール
InfoBank（ベトナム経済メディア）向け。
「ファクトチェックに時間がかかる」課題を解決する中核モジュール。
複数ソース突合・数値整合性チェック・信頼度スコアリングを自動化する。
"""

import json
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict

import openai

from config import OPENAI_API_KEY, ARTICLE_CONFIG, OUTPUT_DIR

# ──────────────────────────────────────────────
# 定数定義
# ──────────────────────────────────────────────

# OpenAIクライアント初期化
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# 信頼性の高いメディアリスト（ベトナム経済特化、Bランク判定に使用）
HIGH_CREDIBILITY_SOURCES = {
    "VnExpress International",
    "VnExpress Business",
    "Vietnam News",
    "VietnamNet Business",
    "Tuoi Tre News",
    "Reuters Vietnam",
    "Nikkei Asia Vietnam",
    "BBC Vietnam",
}

# 数値系キーワード（ベトナム経済指標の抽出対象）
NUMERIC_KEYWORDS = [
    # マクロ経済
    "gdp", "growth", "gni",
    # 物価・金利
    "cpi", "inflation", "interest rate", "sbv", "state bank",
    # 対外取引
    "fdi", "foreign direct investment", "export", "import", "trade surplus", "trade deficit",
    "billion usd", "billion dollars",
    # 通貨
    "vnd", "dong", "exchange rate", "forex", "usd/vnd",
    # 労働・雇用
    "unemployment", "employment", "wage", "minimum wage",
    # 証券・株式
    "vnindex", "hnx", "stock", "bond", "securities",
    # エネルギー・資源
    "oil", "gas", "lng", "coal",
    # 数量表現
    "percent", "%", "billion", "trillion", "million",
    "thousand", "ton", "barrel",
]

# ソース鮮度チェックの閾値（時間）
FRESHNESS_THRESHOLD_HOURS = 48

# InfoBankカテゴリとキーワードの対応（config.pyのINFOBANK_CATEGORIESに準拠）
_INFOBANK_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "economy": [
        "gdp", "economic growth", "inflation", "trade", "export", "import",
        "fdi", "investment", "budget", "fiscal", "monetary", "dong", "vnd",
        "central bank", "state bank", "sbv", "interest rate", "forex",
        "stock", "market", "ipo", "bond", "securities",
    ],
    "politics": [
        "government", "party", "congress", "national assembly", "minister",
        "prime minister", "president", "policy", "regulation", "decree",
        "law", "legislation", "communist", "politburo", "diplomacy",
    ],
    "food": [
        "food", "restaurant", "cafe", "coffee", "seafood", "rice",
        "beverage", "dairy", "meat", "agriculture food", "f&b",
        "dining", "franchise food", "snack", "confectionery",
    ],
    "retail": [
        "retail", "shopping", "mall", "e-commerce", "consumer",
        "supermarket", "convenience store", "wholesale", "distribution",
        "aeon", "vinmart", "winmart", "bach hoa xanh",
    ],
    "service": [
        "service", "tourism", "hotel", "travel", "fintech", "banking",
        "insurance", "telecom", "it service", "outsourcing", "bpo",
        "education", "training", "consulting",
    ],
    "medical": [
        "health", "medical", "hospital", "pharmaceutical", "drug",
        "vaccine", "clinic", "healthcare", "biotech", "wellness",
    ],
    "power-energy": [
        "energy", "power", "electricity", "solar", "wind", "renewable",
        "oil", "gas", "lng", "coal", "nuclear", "ev charging",
        "grid", "evn", "petrovietnam", "pvn",
    ],
    "logistics": [
        "logistics", "warehouse", "shipping", "port", "freight",
        "supply chain", "transport", "cargo", "container", "delivery",
        "cold chain", "3pl",
    ],
    "automobile": [
        "automobile", "car", "vehicle", "ev", "electric vehicle",
        "vinfast", "toyota", "hyundai", "honda car", "thaco",
        "auto", "automotive",
    ],
    "real-estate": [
        "real estate", "property", "housing", "apartment", "condo",
        "construction", "infrastructure", "industrial park", "office",
        "building", "developer", "vinhomes", "novaland",
    ],
    "agri": [
        "agriculture", "farming", "crop", "rice", "coffee bean",
        "rubber", "pepper", "cashew", "aquaculture", "fishery",
        "shrimp", "pangasius", "livestock", "fertilizer",
    ],
    "motor-bike": [
        "motorcycle", "motorbike", "scooter", "honda bike", "yamaha",
        "two-wheeler", "electric bike", "e-bike",
    ],
    "taxation": [
        "tax", "taxation", "vat", "corporate tax", "accounting",
        "audit", "customs", "duty", "transfer pricing", "invoice",
    ],
    "legal": [
        "law", "legal", "court", "regulation", "compliance",
        "intellectual property", "labor law", "contract", "license",
        "dispute", "arbitration",
    ],
    "human-resources-and-labor-affairs": [
        "labor", "employment", "hiring", "salary", "wage",
        "human resource", "hr", "workforce", "worker", "recruitment",
        "layoff", "minimum wage", "social insurance",
    ],
}


# ──────────────────────────────────────────────
# 1. トピックグルーピング
# ──────────────────────────────────────────────

def group_articles_by_topic(articles: list[dict]) -> dict[str, list[dict]]:
    """
    収集済み記事群をInfoBankカテゴリ別にグルーピングする。
    collector.pyのtopicsフィールドがあればそれを優先、なければ独自判定。

    Returns:
        {"カテゴリ名": [記事, ...], ...}
    """
    groups: dict[str, list[dict]] = defaultdict(list)

    for article in articles:
        # collector.pyで付与済みのtopicsがある場合はそれを使う
        topics = article.get("topics")
        if topics:
            primary = topics[0]  # 最初のトピックを主カテゴリとして使用
        else:
            primary = _infer_topic(article)
        groups[primary].append(article)

    print(f"トピックグルーピング完了: {len(groups)}カテゴリ、{len(articles)}件")
    for topic, arts in groups.items():
        print(f"  [{topic}]: {len(arts)}件")

    return dict(groups)


def _infer_topic(article: dict) -> str:
    """
    タイトル＋本文からInfoBankカテゴリを簡易推定する。
    config.pyのINFOBANK_CATEGORIESと同一キーワード体系を使用。
    """
    text = (article.get("title", "") + " " + article.get("summary", "")).lower()

    # キーワードマッチ数が多いカテゴリを優先選択
    best_topic = "その他"
    best_count = 0

    for topic, keywords in _INFOBANK_TOPIC_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_topic = topic

    return best_topic


# ──────────────────────────────────────────────
# 2. 複数ソース突合（同一イベントのクラスタリング）
# ──────────────────────────────────────────────

def match_same_event(articles: list[dict], similarity_threshold: float = 0.35) -> list[dict]:
    """
    同一イベントを報じている記事をJaccard類似度で自動マッチングし、
    ソースリストを統合したクラスターを生成する。
    APIコスト最小化のため、GPTを使わずタイトルキーワードで判定する。

    Args:
        articles: 同一トピック内の記事リスト
        similarity_threshold: マッチ判定のJaccard係数閾値（デフォルト0.35）

    Returns:
        マッチング結果をまとめたクラスター記事リスト
    """
    if not articles:
        return []

    clusters: list[dict] = []
    used_ids: set[str] = set()

    for i, base in enumerate(articles):
        base_id = base.get("id", str(i))
        if base_id in used_ids:
            continue

        cluster = {
            **base,
            "matched_articles": [base],
            "all_sources": [base.get("source", "")],
            "all_links": [base.get("link", "")],
        }
        used_ids.add(base_id)

        base_tokens = _tokenize_title(base.get("title", ""))

        for j, candidate in enumerate(articles):
            cand_id = candidate.get("id", str(j))
            if cand_id in used_ids or cand_id == base_id:
                continue
            # 同一ソースはスキップ（重複排除済みの場合も考慮）
            if candidate.get("source") == base.get("source"):
                continue

            cand_tokens = _tokenize_title(candidate.get("title", ""))
            sim = _jaccard_similarity(base_tokens, cand_tokens)

            if sim >= similarity_threshold:
                cluster["matched_articles"].append(candidate)
                cluster["all_sources"].append(candidate.get("source", ""))
                cluster["all_links"].append(candidate.get("link", ""))
                used_ids.add(cand_id)

        # collector.pyで既に複数ソースが統合されている場合も考慮
        existing_sources = base.get("sources", [base.get("source", "")])
        cluster["all_sources"] = list(set(existing_sources + cluster["all_sources"]))
        cluster["source_count"] = len(cluster["all_sources"])

        clusters.append(cluster)

    print(f"  イベントマッチング: {len(articles)}件 → {len(clusters)}クラスター")
    return clusters


def _tokenize_title(title: str) -> set[str]:
    """タイトルを正規化してトークンセットに変換する"""
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    # 一般的なストップワードを除去
    stopwords = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of",
        "and", "or", "is", "are", "was", "were", "by", "with",
        "as", "its", "be", "has", "have",
    }
    tokens = {w for w in title.split() if w not in stopwords and len(w) > 2}
    return tokens


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard係数でセット間の類似度を計算する（0〜1）"""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


# ──────────────────────────────────────────────
# 3. 数値抽出（GPT-4o-mini）
# ──────────────────────────────────────────────

def extract_numeric_claims(article: dict) -> list[dict]:
    """
    記事テキストからベトナム経済指標（GDP、FDI、VND為替、CPI、輸出入額等）を
    GPT-4o-miniで抽出する。数値キーワードが含まれない記事はAPIコスト節約のためスキップ。

    Returns:
        [{"metric": "GDP成長率", "value": "6.8%", "context": "2024年通年見通し", "source": "..."}, ...]
    """
    text = f"Title: {article.get('title', '')}\n{article.get('summary', '')}"
    source = article.get("source", "不明")

    # 数値系キーワードが含まれない記事はスキップ（API節約）
    if not any(kw in text.lower() for kw in NUMERIC_KEYWORDS):
        return []

    prompt = """以下はベトナム経済に関するニュース記事です。記事から経済指標の具体的な数値をすべて抽出してください。

抽出対象（優先順位が高い指標）：
- GDP成長率（年率・四半期）
- FDI（外国直接投資額・件数）
- VND為替レート（USD/VND等）
- CPI（消費者物価指数・インフレ率）
- 輸出額・輸入額・貿易収支
- SBV（ベトナム国家銀行）政策金利
- VN-Index（ホーチミン証券取引所）
- 失業率・最低賃金
- その他ベトナム経済の具体的数値

出力はJSON配列のみ（説明文不要）。各要素の形式：
{"metric": "指標名（英語可）", "value": "数値と単位", "context": "数値の説明（30字以内）"}

数値が含まれない場合は空配列 [] を返すこと。

記事:
""" + text

    try:
        response = client.chat.completions.create(
            model=ARTICLE_CONFIG["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
        # JSONブロックを抽出（```json ... ``` 形式にも対応）
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return []
        claims = json.loads(json_match.group())
        # sourceを付与
        for claim in claims:
            claim["source"] = source
        return claims

    except (json.JSONDecodeError, openai.OpenAIError, KeyError) as e:
        print(f"  [警告] 数値抽出エラー ({source}): {e}")
        return []


# ──────────────────────────────────────────────
# 4. 数値整合性チェック（ソース間の矛盾検出）
# ──────────────────────────────────────────────

def check_numeric_consistency(clusters: list[dict]) -> list[dict]:
    """
    クラスター内の複数記事から抽出した数値を突合し、ソース間の矛盾を検出する。
    矛盾がある場合はinconsistenciesフィールドに詳細を格納する。

    Returns:
        inconsistenciesフィールドが追加されたクラスターリスト
    """
    for cluster in clusters:
        matched = cluster.get("matched_articles", [cluster])
        if len(matched) < 2:
            # 単一ソースの場合はそのまま数値抽出のみ実施
            cluster["numeric_claims"] = extract_numeric_claims(cluster)
            cluster["inconsistencies"] = []
            continue

        title_preview = cluster.get("title", "")[:40]
        print(f"  数値チェック: 「{title_preview}...」（{len(matched)}ソース）")

        # 全記事から数値を収集
        all_claims: list[dict] = []
        for art in matched:
            claims = extract_numeric_claims(art)
            all_claims.extend(claims)

        cluster["numeric_claims"] = all_claims

        if len(all_claims) < 2:
            cluster["inconsistencies"] = []
            continue

        # GPT-4o-miniで矛盾チェック
        cluster["inconsistencies"] = _detect_inconsistencies(all_claims, cluster.get("title", ""))

    return clusters


def _detect_inconsistencies(claims: list[dict], topic_title: str) -> list[dict]:
    """
    複数ソースの数値クレームをGPT-4o-miniに渡し、矛盾箇所を検出する。
    ±5%以内の丸め誤差は許容範囲としてOK判定する。

    Returns:
        [{"metric": "...", "conflict": "ソースAは6.8%、ソースBは7.2%", "severity": "high/medium/low"}, ...]
    """
    claims_text = json.dumps(claims, ensure_ascii=False, indent=2)

    prompt = f"""以下は「{topic_title}」に関する複数のベトナム経済ニュースソースから抽出した数値データです。

同じ指標について、ソース間で数値が矛盾・不一致していないか確認してください。
誤差が許容範囲（±5%以内の丸め誤差）の場合はOKとみなしてください。

矛盾があればJSON配列で返してください（なければ空配列 []）。
各要素の形式：
{{"metric": "指標名", "conflict": "矛盾の説明", "values": ["ソースA: X%", "ソースB: Y%"], "severity": "high/medium/low"}}

数値データ:
{claims_text}
"""

    try:
        response = client.chat.completions.create(
            model=ARTICLE_CONFIG["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return []
        return json.loads(json_match.group())

    except (json.JSONDecodeError, openai.OpenAIError) as e:
        print(f"  [警告] 矛盾チェックエラー: {e}")
        return []


# ──────────────────────────────────────────────
# 5. ソース鮮度チェック（48時間超の古いソース検出）
# ──────────────────────────────────────────────

def check_source_freshness(clusters: list[dict]) -> list[dict]:
    """
    クラスター内の各記事の公開日時をチェックする。
    閾値（48時間）を超えた古い記事をソースとして使っている場合に警告を付与する。

    Returns:
        freshness_warningsフィールドが追加されたクラスターリスト
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=FRESHNESS_THRESHOLD_HOURS)

    for cluster in clusters:
        warnings: list[dict] = []
        articles_to_check = cluster.get("matched_articles", [cluster])

        for art in articles_to_check:
            pub_str = art.get("published")
            source_name = art.get("source", "不明")

            if not pub_str:
                warnings.append({
                    "source": source_name,
                    "issue": "公開日時が不明（日時未取得）",
                    "published": None,
                })
                continue

            try:
                # ISO形式・タイムゾーン付き両方に対応
                pub_dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                pub_dt_naive = pub_dt.replace(tzinfo=None)

                age_hours = (now - pub_dt_naive).total_seconds() / 3600
                if pub_dt_naive < cutoff:
                    warnings.append({
                        "source": source_name,
                        "issue": f"記事が古い（{int(age_hours)}時間前）",
                        "published": pub_str,
                        "age_hours": round(age_hours, 1),
                    })
            except (ValueError, TypeError):
                warnings.append({
                    "source": source_name,
                    "issue": f"日時パース失敗: {pub_str}",
                    "published": pub_str,
                })

        cluster["freshness_warnings"] = warnings

    stale_count = sum(1 for c in clusters if c.get("freshness_warnings"))
    if stale_count:
        print(f"  鮮度チェック: {stale_count}件に古いソースあり（閾値: {FRESHNESS_THRESHOLD_HOURS}時間）")

    return clusters


# ──────────────────────────────────────────────
# 6. 信頼度スコアリング（A/B/Cランク付与）
# ──────────────────────────────────────────────

def score_credibility(cluster: dict) -> dict:
    """
    クラスター単体の信頼度ランクを判定する。

    ランク基準:
        A: 複数ソース確認済み（2件以上）かつ数値矛盾なし
        B: 単一ソースだがHIGH_CREDIBILITY_SOURCESに含まれる高信頼メディア
        C: 単一ソース・信頼性未確認、または数値矛盾あり

    Returns:
        rank / rank_reason / caution_flagsフィールドが追加されたクラスター
    """
    source_count = cluster.get("source_count", 1)
    inconsistencies = cluster.get("inconsistencies", [])
    freshness_warnings = cluster.get("freshness_warnings", [])
    all_sources = cluster.get("all_sources", [cluster.get("source", "")])

    caution_flags: list[str] = []

    # 数値矛盾があれば即Cランクに落とす
    if inconsistencies:
        caution_flags.append("数値矛盾あり")
        rank = "C"
        rank_reason = "ソース間で数値の不一致が検出されました"

    elif source_count >= ARTICLE_CONFIG.get("min_sources_for_factcheck", 2):
        # 複数ソース確認済み → Aランク
        source_preview = ", ".join(all_sources[:3])
        rank = "A"
        rank_reason = f"{source_count}ソースで確認済み（{source_preview}）"

    else:
        # 単一ソース → 高信頼メディアかどうかで判定
        source_name = all_sources[0] if all_sources else ""
        if source_name in HIGH_CREDIBILITY_SOURCES:
            rank = "B"
            rank_reason = f"単一ソースだが高信頼メディア（{source_name}）"
        else:
            rank = "C"
            rank_reason = f"単一ソース・信頼性未確認（{source_name}）"
            caution_flags.append("単一ソース・要確認")

    # 鮮度警告があればフラグ追加（ランクは変えないが注意喚起）
    if freshness_warnings:
        caution_flags.append(f"古いソースあり（{len(freshness_warnings)}件）")

    cluster["rank"] = rank
    cluster["rank_reason"] = rank_reason
    cluster["caution_flags"] = caution_flags

    return cluster


def score_all(clusters: list[dict]) -> list[dict]:
    """全クラスターに信頼度スコア（A/B/Cランク）を付与する"""
    for cluster in clusters:
        score_credibility(cluster)

    rank_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    for c in clusters:
        rank_counts[c.get("rank", "C")] += 1

    print(
        f"  信頼度スコア完了: "
        f"A={rank_counts['A']}件、B={rank_counts['B']}件、C={rank_counts['C']}件"
    )
    return clusters


# ──────────────────────────────────────────────
# 7. ファクトチェックレポート生成
# ──────────────────────────────────────────────

def generate_report(clusters: list[dict], topic: str = "全体") -> dict:
    """
    ファクトチェック結果をJSON形式のレポートとして生成する。
    「要注意箇所」を明示し、InfoBank編集者が重点確認すべき箇所をハイライトする。

    Args:
        clusters: スコアリング済みのクラスターリスト
        topic: レポートタイトルに使うトピック名

    Returns:
        report辞書（JSON保存可能な形式）
    """
    now = datetime.utcnow().isoformat()
    a_items = [c for c in clusters if c.get("rank") == "A"]
    b_items = [c for c in clusters if c.get("rank") == "B"]
    c_items = [c for c in clusters if c.get("rank") == "C"]

    # 要注意リスト（Cランク＋矛盾あり＋鮮度警告あり）
    attention_required: list[dict] = []
    for c in clusters:
        flags = c.get("caution_flags", [])
        inconsistencies = c.get("inconsistencies", [])
        if flags or inconsistencies:
            attention_required.append({
                "title": c.get("title", "")[:80],
                "rank": c.get("rank"),
                "caution_flags": flags,
                "inconsistencies": inconsistencies,
                "sources": c.get("all_sources", []),
                "freshness_warnings": c.get("freshness_warnings", []),
            })

    report = {
        "meta": {
            "generated_at": now,
            "topic": topic,
            "total_clusters": len(clusters),
            "rank_summary": {
                "A": len(a_items),
                "B": len(b_items),
                "C": len(c_items),
            },
        },
        # 要注意箇所（InfoBank編集者が重点確認すべき箇所）
        "attention_required": attention_required,
        # ランク別詳細
        "rank_A": _format_cluster_list(a_items),
        "rank_B": _format_cluster_list(b_items),
        "rank_C": _format_cluster_list(c_items),
    }

    return report


def _format_cluster_list(clusters: list[dict]) -> list[dict]:
    """クラスターを出力用に整形する（内部ヘルパー）"""
    result = []
    for c in clusters:
        result.append({
            "title": c.get("title", ""),
            "rank": c.get("rank"),
            "rank_reason": c.get("rank_reason", ""),
            "source_count": c.get("source_count", 1),
            "all_sources": c.get("all_sources", []),
            "published": c.get("published"),
            "numeric_claims": c.get("numeric_claims", []),
            "inconsistencies": c.get("inconsistencies", []),
            "caution_flags": c.get("caution_flags", []),
            "freshness_warnings": c.get("freshness_warnings", []),
            "links": c.get("all_links", [c.get("link", "")]),
        })
    return result


def report_to_text(report: dict) -> str:
    """
    JSONレポートをInfoBank編集者が読みやすいテキスト形式に変換する。

    Returns:
        フォーマット済みテキスト文字列
    """
    lines: list[str] = []
    meta = report["meta"]

    lines.append("=" * 60)
    lines.append(f"ファクトチェックレポート — {meta['topic']}")
    lines.append(f"生成日時: {meta['generated_at']} (UTC)")
    lines.append("=" * 60)

    rs = meta["rank_summary"]
    lines.append(f"\n【スコアサマリー】 全{meta['total_clusters']}件")
    lines.append(f"  A（複数ソース確認済み）: {rs['A']}件")
    lines.append(f"  B（高信頼・単一ソース）: {rs['B']}件")
    lines.append(f"  C（要注意・要確認）    : {rs['C']}件")

    # 要注意箇所ハイライト
    if report["attention_required"]:
        lines.append("\n" + "!" * 60)
        lines.append("★ 要注意箇所（InfoBank編集者による重点確認が必要）")
        lines.append("!" * 60)
        for i, item in enumerate(report["attention_required"], 1):
            lines.append(f"\n[{i}] [{item['rank']}] {item['title']}")
            if item["caution_flags"]:
                lines.append(f"    フラグ: {' / '.join(item['caution_flags'])}")
            if item["inconsistencies"]:
                lines.append("    数値矛盾:")
                for inc in item["inconsistencies"]:
                    lines.append(f"      - {inc.get('metric', '')}: {inc.get('conflict', '')}")
                    if inc.get("values"):
                        lines.append(f"        ({' vs '.join(inc['values'])})")
            if item["freshness_warnings"]:
                for fw in item["freshness_warnings"]:
                    lines.append(f"      - {fw.get('source', '')}: {fw.get('issue', '')}")
    else:
        lines.append("\n★ 要注意箇所なし")

    # ランク別リスト
    for rank, key in [("A", "rank_A"), ("B", "rank_B"), ("C", "rank_C")]:
        items = report.get(key, [])
        if not items:
            continue
        lines.append(f"\n{'─' * 40}")
        lines.append(f"【ランク {rank}】 {len(items)}件")
        lines.append("─" * 40)
        for item in items:
            lines.append(f"\n  ■ {item['title'][:70]}")
            lines.append(f"    ソース: {', '.join(item['all_sources'])} （{item['source_count']}件）")
            lines.append(f"    判定: {item['rank_reason']}")
            if item["numeric_claims"]:
                claims_preview = ", ".join(
                    f"{c['metric']}={c['value']}" for c in item["numeric_claims"][:3]
                )
                lines.append(f"    数値: {claims_preview}")
            if item["caution_flags"]:
                lines.append(f"    注意: {' / '.join(item['caution_flags'])}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 8. レポート保存（JSON＋テキスト）
# ──────────────────────────────────────────────

def save_report(report: dict, prefix: str = "factcheck") -> tuple[str, str]:
    """
    ファクトチェックレポートをJSONとテキストの両形式でOUTPUT_DIRに保存する。

    Returns:
        (json_path, text_path) のタプル
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(OUTPUT_DIR, f"{prefix}_{timestamp}.json")
    text_path = os.path.join(OUTPUT_DIR, f"{prefix}_{timestamp}.txt")

    # JSON保存
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"JSONレポート保存: {json_path}")

    # テキスト保存
    text = report_to_text(report)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"テキストレポート保存: {text_path}")

    return json_path, text_path


# ──────────────────────────────────────────────
# 9. メインパイプライン（全ステップ一括実行）
# ──────────────────────────────────────────────

def run_factcheck(articles: list[dict], save: bool = True) -> tuple[dict, list[dict]]:
    """
    収集済み記事群に対してファクトチェックの全ステップを一括実行する。

    処理フロー:
        1. トピックグルーピング（InfoBankカテゴリ別）
        2. 同一イベントマッチング（Jaccard類似度）
        3. ベトナム経済指標の数値抽出 + ソース間整合性チェック
        4. ソース鮮度チェック（48時間超を検出）
        5. 信頼度スコアリング（A/B/Cランク付与）
        6. レポート生成・保存（JSON＋テキスト）

    Args:
        articles: collector.pyで収集した記事リスト
        save: Trueの場合、レポートをOUTPUT_DIRに保存する

    Returns:
        (report辞書, スコアリング済みクラスターリスト)
    """
    print("\n" + "=" * 60)
    print("ファクトチェック開始 — InfoBank ベトナム経済版")
    print(f"対象記事数: {len(articles)}件")
    print("=" * 60 + "\n")

    # ステップ1: トピックグルーピング
    print("【ステップ1】トピックグルーピング")
    topic_groups = group_articles_by_topic(articles)

    # ステップ2: トピックごとに同一イベントをマッチング
    print("\n【ステップ2】同一イベントマッチング（Jaccard類似度）")
    all_clusters: list[dict] = []
    for topic, topic_articles in topic_groups.items():
        print(f"\n  トピック: [{topic}]")
        clusters = match_same_event(topic_articles)
        for c in clusters:
            c["primary_topic"] = topic
        all_clusters.extend(clusters)

    # ステップ3: 数値抽出 + 整合性チェック
    print(f"\n【ステップ3】ベトナム経済指標の数値抽出・整合性チェック（全{len(all_clusters)}クラスター）")
    all_clusters = check_numeric_consistency(all_clusters)

    # ステップ4: ソース鮮度チェック
    print("\n【ステップ4】ソース鮮度チェック（閾値: 48時間）")
    all_clusters = check_source_freshness(all_clusters)

    # ステップ5: 信頼度スコアリング
    print("\n【ステップ5】信頼度スコアリング（A/B/Cランク付与）")
    all_clusters = score_all(all_clusters)

    # ステップ6: レポート生成
    print("\n【ステップ6】レポート生成")
    report = generate_report(all_clusters)

    if save:
        save_report(report)

    print("\n" + "=" * 60)
    print("ファクトチェック完了")
    print(f"  Aランク（複数ソース確認済み）: {report['meta']['rank_summary']['A']}件")
    print(f"  Bランク（高信頼・単一ソース）: {report['meta']['rank_summary']['B']}件")
    print(f"  Cランク（要注意・要確認）    : {report['meta']['rank_summary']['C']}件")
    print(f"  要注意箇所: {len(report['attention_required'])}件")
    print("=" * 60 + "\n")

    return report, all_clusters


# ──────────────────────────────────────────────
# 単体テスト用エントリポイント
# ──────────────────────────────────────────────

if __name__ == "__main__":
    # テスト用サンプル記事（実際はcollector.pyから渡す）
    sample_articles = [
        {
            "id": "vn001",
            "title": "Vietnam GDP growth reaches 6.8% in 2024, beats government target",
            "summary": (
                "Vietnam's GDP expanded 6.8% in 2024, surpassing the government's 6.5% target. "
                "FDI disbursement hit a record $25.3 billion. The VND/USD rate closed at 25,400."
            ),
            "source": "VnExpress Business",
            "published": datetime.utcnow().isoformat(),
            "link": "https://e.vnexpress.net/test-gdp-2024",
        },
        {
            "id": "vn002",
            "title": "Vietnam economy expands 6.8 percent in 2024, FDI at record high",
            "summary": (
                "The Vietnamese economy grew 6.8% last year. "
                "Realized FDI reached $25.35 billion, a new record. "
                "CPI averaged 3.63% for the full year."
            ),
            "source": "Vietnam News",
            "published": datetime.utcnow().isoformat(),
            "link": "https://vietnamnews.vn/test-gdp-2024",
        },
        {
            "id": "vn003",
            "title": "Vietnam CPI rises 3.63% in 2024 as food prices climb",
            "summary": (
                "Vietnam's consumer price index rose 3.63% on average in 2024, "
                "driven by food and healthcare costs. The State Bank of Vietnam kept "
                "the refinancing rate at 4.5%."
            ),
            "source": "VietnamNet Business",
            "published": datetime.utcnow().isoformat(),
            "link": "https://vietnamnet.vn/test-cpi-2024",
        },
        {
            "id": "vn004",
            "title": "Mekong Delta shrimp exports top $3 billion in 2024",
            "summary": (
                "Shrimp exports from the Mekong Delta reached $3.2 billion in 2024, "
                "a 12% increase year-on-year. Key markets include the US, EU, and Japan."
            ),
            "source": "Tuoi Tre News",
            "published": datetime.utcnow().isoformat(),
            "link": "https://tuoitrenews.vn/test-shrimp-2024",
        },
    ]

    report, clusters = run_factcheck(sample_articles, save=True)
    print(report_to_text(report))
