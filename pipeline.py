"""
パイプライン統合モジュール
収集 → ファクトチェック → 記事ドラフト生成 を一括実行する。
各モジュールは単体でも使えるが、このスクリプトで全工程を一気通貫で回せる。
"""

import argparse
import json
import time
from datetime import datetime

from config import ARTICLE_CONFIG, OUTPUT_DIR
from collector import collect_news, save_to_json, load_from_json
from factchecker import run_factcheck, report_to_text
from article_generator import generate_drafts


def run_pipeline(
    max_age_hours: int = 24,
    max_articles: int = None,
    skip_factcheck: bool = False,
    skip_drafts: bool = False,
    input_json: str = None,
):
    """
    全工程を一括実行するメインパイプライン。

    Args:
        max_age_hours: 収集対象の記事有効期限（時間）
        max_articles: 記事ドラフト生成の上限数
        skip_factcheck: ファクトチェックをスキップ（収集のみ）
        skip_drafts: 記事ドラフト生成をスキップ（収集+チェックのみ）
        input_json: 既存の収集済みJSONから再開する場合のファイルパス
    """
    start_time = time.time()
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    print("=" * 60)
    print("  Global Econ News AI Pipeline")
    print(f"  実行開始: {timestamp}")
    print("=" * 60)

    # ────────────────────────────────────
    # STEP 1: ニュース収集
    # ────────────────────────────────────
    if input_json:
        print(f"\n[STEP 1] 既存データから読み込み: {input_json}")
        articles = load_from_json(input_json)
    else:
        print(f"\n[STEP 1] ニュース収集（過去{max_age_hours}時間）")
        articles = collect_news(max_age_hours=max_age_hours)
        if articles:
            json_path = save_to_json(articles)
            print(f"  → 収集データ保存: {json_path}")

    if not articles:
        print("\n記事が見つかりませんでした。終了します。")
        return

    step1_time = time.time()
    print(f"  所要時間: {step1_time - start_time:.1f}秒")

    # ────────────────────────────────────
    # STEP 2: ファクトチェック
    # ────────────────────────────────────
    if skip_factcheck:
        print("\n[STEP 2] ファクトチェック: スキップ")
        report = None
        checked_clusters = articles
    else:
        print(f"\n[STEP 2] ファクトチェック（{len(articles)}件）")
        report, checked_clusters = run_factcheck(articles, save=True)

        # テキストレポートをコンソールにも表示
        print("\n" + report_to_text(report))

    step2_time = time.time()
    print(f"  所要時間: {step2_time - step1_time:.1f}秒")

    # ────────────────────────────────────
    # STEP 3: 記事ドラフト生成
    # ────────────────────────────────────
    if skip_drafts:
        print("\n[STEP 3] 記事ドラフト生成: スキップ")
        draft_paths = []
    else:
        # ファクトチェック結果をドラフト生成用に整形
        draft_input = _prepare_for_drafts(checked_clusters, report)
        limit = max_articles or ARTICLE_CONFIG["max_articles_per_run"]

        print(f"\n[STEP 3] 記事ドラフト生成（上限{limit}件）")
        draft_paths = generate_drafts(draft_input, max_count=limit)

    step3_time = time.time()
    print(f"  所要時間: {step3_time - step2_time:.1f}秒")

    # ────────────────────────────────────
    # サマリー
    # ────────────────────────────────────
    total_time = time.time() - start_time
    print("\n" + "=" * 60)
    print("  パイプライン完了")
    print("=" * 60)
    print(f"  総所要時間: {total_time:.1f}秒")
    print(f"  収集記事数: {len(articles)}件")
    if report:
        rs = report["meta"]["rank_summary"]
        print(f"  ファクトチェック: A={rs['A']} / B={rs['B']} / C={rs['C']}")
        print(f"  要注意箇所: {len(report['attention_required'])}件")
    print(f"  生成ドラフト: {len(draft_paths)}件")
    print(f"  出力先: {OUTPUT_DIR}/")
    print("=" * 60)


def _prepare_for_drafts(clusters, report):
    """
    ファクトチェック結果を記事ドラフト生成に渡す形式に変換する。
    Aランク優先、次にBランクの順で並び替える。
    """
    if not report:
        return clusters

    # ランク順にソート（A→B→C）
    rank_order = {"A": 0, "B": 1, "C": 2}
    sorted_clusters = sorted(
        clusters,
        key=lambda c: rank_order.get(c.get("rank", "C"), 3)
    )

    # ファクトチェック結果をarticle_generator用にマッピング
    for cluster in sorted_clusters:
        cluster["factcheck"] = {
            "confidence_label": cluster.get("rank", "C"),
            "issues": [
                inc.get("conflict", "")
                for inc in cluster.get("inconsistencies", [])
            ] + cluster.get("caution_flags", []),
            "verified_at": report["meta"]["generated_at"],
        }
        # sourcesフィールドの正規化
        if "all_sources" in cluster and "sources" not in cluster:
            cluster["sources"] = cluster["all_sources"]
        if "all_links" in cluster and "links" not in cluster:
            cluster["links"] = cluster["all_links"]
        if "primary_topic" in cluster and "topics" not in cluster:
            cluster["topics"] = [cluster["primary_topic"]]

    return sorted_clusters


# ────────────────────────────────────
# CLI エントリポイント
# ────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="海外経済ニュース AI パイプライン — 収集・ファクトチェック・記事生成"
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="収集対象の記事有効期限（時間）。デフォルト: 24"
    )
    parser.add_argument(
        "--max-articles", type=int, default=None,
        help="記事ドラフト生成の上限数"
    )
    parser.add_argument(
        "--collect-only", action="store_true",
        help="収集のみ実行（ファクトチェック・ドラフト生成をスキップ）"
    )
    parser.add_argument(
        "--no-drafts", action="store_true",
        help="記事ドラフト生成をスキップ（収集+ファクトチェックのみ）"
    )
    parser.add_argument(
        "--input", type=str, default=None,
        help="既存の収集済みJSONファイルから再開"
    )

    args = parser.parse_args()

    run_pipeline(
        max_age_hours=args.hours,
        max_articles=args.max_articles,
        skip_factcheck=args.collect_only,
        skip_drafts=args.collect_only or args.no_drafts,
        input_json=args.input,
    )
