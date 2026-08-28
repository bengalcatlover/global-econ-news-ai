"""
InfoBank ベトナム経済ニュース収集モジュール
RSS フィードから複数ソースを取得し、重複除去・カテゴリ分類・JSON保存を行う
"""

import json
import os
import re
import hashlib
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

from config import RSS_FEEDS, INFOBANK_CATEGORIES, OUTPUT_DIR

# ──────────────────────────────────────────────
# 定数
# ──────────────────────────────────────────────

# デフォルトの記事有効期限（時間）
DEFAULT_MAX_AGE_HOURS = 24

# HTTP リクエスト用 User-Agent（ブロック対策）
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; InfoBankNewsBot/1.0; "
        "+https://github.com/example/global-econ-news-ai)"
    )
}

# ──────────────────────────────────────────────
# 内部ユーティリティ（プレフィックス _ で区別）
# ──────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    """
    タイトルを正規化して重複検出キーを生成する
    - 小文字化
    - 句読点・記号除去
    - 余分なスペース圧縮
    """
    title = title.lower()
    title = re.sub(r"[^\w\s]", "", title)   # 記号除去
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _title_fingerprint(normalized: str) -> str:
    """
    正規化済みタイトルの先頭60文字を MD5 ハッシュ化する
    高速な重複チェックキーとして利用
    """
    prefix = normalized[:60]
    return hashlib.md5(prefix.encode()).hexdigest()


def _parse_published_time(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    """
    feedparser エントリから公開日時を UTC datetime に変換する
    複数フォールバックを試み、全て失敗した場合は None を返す
    """
    # feedparser がパース済み time_struct を持つケース
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        ts = getattr(entry, attr, None)
        if ts:
            try:
                return datetime(*ts[:6], tzinfo=timezone.utc)
            except Exception:
                pass

    # 文字列フォールバック（RFC 2822 / ISO 8601 形式）
    for attr in ("published", "updated", "created"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(raw).astimezone(timezone.utc)
            except Exception:
                pass

    return None


def _extract_summary(entry: feedparser.FeedParserDict) -> str:
    """
    feedparser エントリからサマリーテキストを抽出し HTML タグを除去する
    先頭 500 文字に制限して返す
    """
    raw = ""
    if hasattr(entry, "summary") and entry.summary:
        raw = entry.summary
    elif hasattr(entry, "description") and entry.description:
        raw = entry.description
    elif hasattr(entry, "content") and entry.content:
        raw = entry.content[0].get("value", "")

    # BeautifulSoup で HTML タグを除去してプレーンテキスト化
    text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


def _classify_category(title: str, summary: str) -> tuple[str, str]:
    """
    タイトルとサマリーのテキストから InfoBank カテゴリを分類する

    INFOBANK_CATEGORIES を上から評価し、最初にキーワードがマッチした
    カテゴリスラッグと日本語名のタプルを返す。
    どのキーワードにも該当しない場合は ("other", "その他") を返す。

    Args:
        title:   記事タイトル
        summary: 記事サマリー

    Returns:
        (カテゴリスラッグ, カテゴリ日本語名) のタプル
    """
    text = (title + " " + summary).lower()
    for slug, meta in INFOBANK_CATEGORIES.items():
        for kw in meta["keywords"]:
            if kw in text:
                return slug, meta["name_ja"]
    return "other", "その他"


# ──────────────────────────────────────────────
# コア関数（単体でも呼び出し可能）
# ──────────────────────────────────────────────

def fetch_feed(source_name: str, feed_url: str, timeout: int = 15) -> list[dict]:
    """
    単一の RSS フィードを取得してエントリリストを返す

    requests で先取得することで User-Agent 付与とタイムアウト制御を実現し、
    取得済みコンテンツを feedparser でパースする。

    Args:
        source_name: ソース名（例: "VnExpress Business"）
        feed_url:    RSS フィードの URL
        timeout:     HTTP タイムアウト秒数（デフォルト 15 秒）

    Returns:
        エントリの辞書リスト。各エントリは以下のキーを持つ:
        - title        : 記事タイトル
        - url          : 記事 URL
        - source       : ソース名
        - summary      : HTML タグ除去済みサマリー（最大500文字）
        - published_at : ISO 8601 形式の公開日時（UTC）または None
        - _published_dt: datetime オブジェクト（内部処理用、JSON 保存時に除外）
    """
    print(f"  [取得中] {source_name} ← {feed_url}")
    entries = []

    try:
        # requests で取得して feedparser に渡す（User-Agent / タイムアウト制御）
        resp = requests.get(feed_url, headers=REQUEST_HEADERS, timeout=timeout)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except requests.exceptions.Timeout:
        print(f"    [警告] タイムアウト: {source_name}")
        return []
    except requests.exceptions.RequestException as e:
        print(f"    [警告] 取得失敗 ({source_name}): {e}")
        return []
    except Exception as e:
        print(f"    [警告] パース失敗 ({source_name}): {e}")
        return []

    if not feed.entries:
        print(f"    [情報] エントリなし: {source_name}")
        return []

    for entry in feed.entries:
        title = getattr(entry, "title", "").strip()
        url   = getattr(entry, "link",  "").strip()
        if not title or not url:
            continue  # タイトルまたは URL が空のエントリはスキップ

        published_at = _parse_published_time(entry)
        summary      = _extract_summary(entry)

        entries.append({
            "title":         title,
            "url":           url,
            "source":        source_name,
            "summary":       summary,
            "published_at":  published_at.isoformat() if published_at else None,
            "_published_dt": published_at,  # フィルタリング用（JSON 保存時は除外）
        })

    print(f"    [完了] {len(entries)} 件取得: {source_name}")
    return entries


def filter_by_age(
    entries: list[dict],
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> list[dict]:
    """
    発信日時が max_age_hours 時間より古い記事を除外する

    公開日時が取得できなかった記事（published_at = None）は
    保守的に残す（除外しない）。

    Args:
        entries:      fetch_feed の結果リスト
        max_age_hours: 有効期限（時間）、デフォルト 24 時間

    Returns:
        フィルタリング後のエントリリスト
    """
    now     = datetime.now(timezone.utc)
    cutoff  = now - timedelta(hours=max_age_hours)
    filtered = []
    skipped  = 0

    for entry in entries:
        dt: Optional[datetime] = entry.get("_published_dt")
        if dt is None:
            # 日時不明の記事は除外しない（情報欠落のためスキップ回避）
            filtered.append(entry)
            continue
        if dt >= cutoff:
            filtered.append(entry)
        else:
            skipped += 1

    if skipped:
        print(f"  [フィルタ] {skipped} 件を除外（{max_age_hours} 時間超過）")
    return filtered


def deduplicate(entries: list[dict]) -> list[dict]:
    """
    タイトル正規化による重複除去を行い、複数ソースの同一記事を統合する

    同一記事と判定された場合の統合ルール:
    - sources フィールドに全ソース名をリストで保持
    - より長いサマリーを採用
    - より古い published_at を保持（最初の報道を正とする）

    Args:
        entries: フィルタリング済みエントリリスト

    Returns:
        重複除去後のエントリリスト
    """
    # fingerprint → 代表エントリ のマッピング
    seen: dict[str, dict] = {}

    for entry in entries:
        norm = _normalize_title(entry["title"])
        fp   = _title_fingerprint(norm)

        if fp not in seen:
            # 初出：コピーして sources リストを付与
            entry = dict(entry)
            entry["sources"] = [entry["source"]]
            seen[fp] = entry
        else:
            # 重複発見：既存エントリに情報をマージ
            existing = seen[fp]

            # ソース名を重複なく追加
            if entry["source"] not in existing["sources"]:
                existing["sources"].append(entry["source"])

            # より長いサマリーを採用
            if len(entry.get("summary", "")) > len(existing.get("summary", "")):
                existing["summary"] = entry["summary"]

            # より古い published_at を保持（最初の報道優先）
            new_dt = entry.get("_published_dt")
            old_dt = existing.get("_published_dt")
            if new_dt and old_dt and new_dt < old_dt:
                existing["_published_dt"] = new_dt
                existing["published_at"]  = new_dt.isoformat()

    result = list(seen.values())
    removed = len(entries) - len(result)
    print(f"  [重複除去] {len(entries)} 件 → {len(result)} 件（{removed} 件を統合）")
    return result


def classify_topics(entries: list[dict]) -> list[dict]:
    """
    各エントリに topic / topic_ja フィールドを付与して InfoBank カテゴリ分類を行う

    INFOBANK_CATEGORIES のキーワードに基づいてタイトル＋サマリーを評価し、
    最初にマッチしたカテゴリを採用する。分類結果の件数サマリーを表示する。

    付与フィールド:
    - topic    : カテゴリスラッグ（例: "economy", "real-estate"）
    - topic_ja : カテゴリ日本語名（例: "経済", "不動産・建設"）

    Args:
        entries: 重複除去済みエントリリスト

    Returns:
        topic / topic_ja フィールドを追加したエントリリスト
    """
    for entry in entries:
        slug, name_ja = _classify_category(
            entry.get("title",   ""),
            entry.get("summary", ""),
        )
        entry["topic"]    = slug
        entry["topic_ja"] = name_ja

    # カテゴリ別件数をコンソールに表示
    counts = Counter(
        f"{e['topic_ja']}（{e['topic']}）" for e in entries
    )
    print("  [分類結果]")
    for label, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {label}: {count} 件")
    return entries


def collect_news(
    feeds: Optional[dict[str, str]] = None,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
) -> list[dict]:
    """
    全 RSS フィードを収集し、フィルタ・重複除去・カテゴリ分類を一括実行する

    各ステップを順番に実行：
    1. 全フィードからエントリを取得
    2. 鮮度フィルタ（max_age_hours 超過を除外）
    3. 重複除去（類似タイトルを統合）
    4. InfoBank カテゴリ分類（キーワードベース）

    Args:
        feeds:         ソース名 → URL の辞書（省略時は config.RSS_FEEDS を使用）
        max_age_hours: 記事の有効期限（時間）

    Returns:
        処理済みエントリのリスト
    """
    if feeds is None:
        feeds = RSS_FEEDS

    print(f"\n{'='*52}")
    print(f"  ニュース収集開始 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"  対象ソース数  : {len(feeds)}")
    print(f"  有効期限      : {max_age_hours} 時間以内")
    print(f"{'='*52}\n")

    # ステップ0: 全フィードを順番に取得
    all_entries: list[dict] = []
    for source_name, feed_url in feeds.items():
        fetched = fetch_feed(source_name, feed_url)
        all_entries.extend(fetched)
        time.sleep(0.5)  # サーバー負荷軽減のための小休止

    print(f"\n取得合計: {len(all_entries)} 件\n")

    # ステップ1: 鮮度フィルタ
    print("[ステップ1] 鮮度フィルタ適用中...")
    fresh_entries = filter_by_age(all_entries, max_age_hours)
    print(f"  フィルタ後: {len(fresh_entries)} 件\n")

    # ステップ2: 重複除去
    print("[ステップ2] 重複除去中...")
    unique_entries = deduplicate(fresh_entries)
    print()

    # ステップ3: InfoBank カテゴリ分類
    print("[ステップ3] InfoBank カテゴリ分類中...")
    classified_entries = classify_topics(unique_entries)
    print()

    print(f"{'='*52}")
    print(f"  収集完了: 最終 {len(classified_entries)} 件")
    print(f"{'='*52}\n")

    return classified_entries


def save_to_json(
    entries: list[dict],
    filename: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    """
    収集結果を JSON ファイルとして保存する

    内部処理用フィールド（_ プレフィックス）は保存時に除外する。
    出力 JSON の構造:
    {
        "generated_at": "<ISO 8601>",
        "total_articles": <int>,
        "articles": [...]
    }

    Args:
        entries:    保存するエントリリスト
        filename:   出力ファイル名（省略時はタイムスタンプ付き自動生成）
        output_dir: 出力ディレクトリ（省略時は config.OUTPUT_DIR を使用）

    Returns:
        保存した JSON ファイルの絶対パス
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR

    if filename is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"news_{ts}.json"

    filepath = os.path.join(output_dir, filename)

    # 内部用フィールド（_ プレフィックス）を除外してエクスポート用リストを作成
    export_entries = [
        {k: v for k, v in entry.items() if not k.startswith("_")}
        for entry in entries
    ]

    payload = {
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "total_articles": len(export_entries),
        "articles":       export_entries,
    }

    os.makedirs(output_dir, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[保存完了] {filepath}  ({len(export_entries)} 件)")
    return filepath


def load_from_json(filepath: str) -> list[dict]:
    """
    JSON ファイルからエントリを読み込む

    save_to_json で保存したファイルの articles リストを返す。
    後続の要約・分析モジュールからの再利用を想定している。

    Args:
        filepath: 読み込む JSON ファイルのパス

    Returns:
        articles リストの内容
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("articles", [])
    print(f"[読み込み完了] {filepath}  ({len(entries)} 件)")
    return entries


# ──────────────────────────────────────────────
# メインエントリポイント
# ──────────────────────────────────────────────

def run(
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    save: bool = True,
) -> tuple[list[dict], Optional[str]]:
    """
    ニュース収集のメインエントリポイント

    collect_news を実行し、オプションで JSON 保存まで一括処理する。
    他モジュールから import して呼び出すことも、スクリプトとして直接実行することも可能。

    Args:
        max_age_hours: 有効期限（時間）。デフォルト 24 時間
        save:          True の場合 JSON 保存を行う

    Returns:
        (エントリリスト, 保存ファイルパス または None) のタプル
    """
    entries  = collect_news(max_age_hours=max_age_hours)
    filepath = None
    if save and entries:
        filepath = save_to_json(entries)
    return entries, filepath


if __name__ == "__main__":
    articles, saved_path = run()
    if saved_path:
        print(f"\n出力先: {saved_path}")
    else:
        print("\n保存をスキップしました（記事なし、または save=False）")
