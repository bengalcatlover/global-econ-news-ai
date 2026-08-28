"""
ベトナム経済ニュース AI パイプライン - デモUI
Streamlit で動作。ボタン一発で収集→ファクトチェック→記事生成まで実行。
"""

import streamlit as st
import json
import time
from datetime import datetime
from io import StringIO
import sys

st.set_page_config(
    page_title="ベトナム経済ニュース AI パイプライン",
    page_icon="📰",
    layout="wide",
)

st.title("📰 ベトナム経済ニュース AI パイプライン")
st.markdown("**情報収集 → ファクトチェック → 記事ドラフト生成** をワンクリックで実行")

# APIキー設定（サイドバーで入力 or 環境変数から取得）
import os
_default_key = os.getenv("OPENAI_API_KEY", "")
if not _default_key:
    try:
        _default_key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        pass

with st.sidebar:
    api_key = st.text_input("OpenAI API Key", value=_default_key, type="password")
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
        import config
        config.OPENAI_API_KEY = api_key

    st.divider()
    st.header("設定")
    hours = st.slider("収集対象（過去N時間）", 6, 72, 24)
    max_articles = st.slider("記事ドラフト生成数", 1, 5, 2)
    skip_drafts = st.checkbox("記事生成をスキップ（収集+チェックのみ）")

    st.divider()
    st.markdown("### 処理フロー")
    st.markdown("""
    1. ベトナム現地メディア9ソースからRSS収集
    2. 重複除去・InfoBank 15カテゴリに自動分類
    3. 複数ソース突合・数値矛盾検出
    4. 信頼度ラベル（A/B/C）付与
    5. 日本語記事ドラフト生成
    """)

# メイン処理
if st.button("▶ パイプラインを実行", type="primary", use_container_width=True):

    if not api_key:
        st.error("サイドバーの「OpenAI API Key」にキーを入力してください")
        st.stop()

    # ────────────────────────────────────
    # STEP 1: ニュース収集
    # ────────────────────────────────────
    st.header("STEP 1: ニュース収集")
    with st.spinner("ベトナム経済ニュースを収集中..."):
        from collector import collect_news, save_to_json
        start = time.time()
        articles = collect_news(max_age_hours=hours)
        elapsed1 = time.time() - start

    if not articles:
        st.error("記事が見つかりませんでした。時間範囲を広げてみてください。")
        st.stop()

    st.success(f"**{len(articles)}件** を収集（{elapsed1:.1f}秒）")

    # カテゴリ分布を表示
    from collections import Counter
    topic_counts = Counter(a.get("topic_ja", a.get("topic", "その他")) for a in articles)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### カテゴリ分布")
        for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1]):
            st.markdown(f"- **{topic}**: {count}件")
    with col2:
        st.markdown("#### 収集ソース")
        source_counts = Counter(a.get("source", "不明") for a in articles)
        for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            st.markdown(f"- {src}: {count}件")

    # 記事一覧（折りたたみ）
    with st.expander(f"収集記事一覧（{len(articles)}件）", expanded=False):
        for i, a in enumerate(articles, 1):
            cat = a.get("topic_ja", a.get("topic", ""))
            src = a.get("source", "")
            st.markdown(f"**{i}.** [{cat}] {a.get('title', '')}  \n<small>{src}</small>", unsafe_allow_html=True)

    st.divider()

    # ────────────────────────────────────
    # STEP 2: ファクトチェック
    # ────────────────────────────────────
    st.header("STEP 2: ファクトチェック")
    with st.spinner("複数ソース突合・数値整合性チェック中..."):
        from factchecker import run_factcheck, report_to_text
        start = time.time()
        report, clusters = run_factcheck(articles, save=False)
        elapsed2 = time.time() - start

    rs = report["meta"]["rank_summary"]
    st.success(f"ファクトチェック完了（{elapsed2:.1f}秒）")

    # スコアサマリー
    col1, col2, col3 = st.columns(3)
    col1.metric("A（複数ソース確認済み）", f"{rs['A']}件")
    col2.metric("B（高信頼・単一ソース）", f"{rs['B']}件")
    col3.metric("C（要注意・要確認）", f"{rs['C']}件")

    # 要注意箇所
    if report["attention_required"]:
        st.markdown("#### 要注意箇所")
        for item in report["attention_required"][:10]:
            rank = item.get("rank", "?")
            title = item.get("title", "")[:60]
            flags = " / ".join(item.get("caution_flags", []))
            if rank == "C":
                st.error(f"**[{rank}]** {title}  \n{flags}")
            else:
                st.warning(f"**[{rank}]** {title}  \n{flags}")

    # フルレポート（折りたたみ）
    with st.expander("ファクトチェックレポート全文", expanded=False):
        st.text(report_to_text(report))

    st.divider()

    # ────────────────────────────────────
    # STEP 3: 記事ドラフト生成
    # ────────────────────────────────────
    if not skip_drafts:
        st.header("STEP 3: 記事ドラフト生成")

        # ファクトチェック結果をドラフト用に整形
        rank_order = {"A": 0, "B": 1, "C": 2}
        sorted_clusters = sorted(clusters, key=lambda c: rank_order.get(c.get("rank", "C"), 3))
        for cluster in sorted_clusters:
            cluster["factcheck"] = {
                "confidence_label": cluster.get("rank", "C"),
                "issues": cluster.get("caution_flags", []),
                "verified_at": report["meta"]["generated_at"],
            }
            if "all_sources" in cluster and "sources" not in cluster:
                cluster["sources"] = cluster["all_sources"]
            if "all_links" in cluster and "links" not in cluster:
                cluster["links"] = cluster["all_links"]
            if "primary_topic" in cluster and "topics" not in cluster:
                cluster["topics"] = [cluster["primary_topic"]]

        from article_generator import render_article
        targets = sorted_clusters[:max_articles]

        for i, article in enumerate(targets, 1):
            title = article.get("title", "")[:50]
            with st.spinner(f"記事 {i}/{len(targets)} を生成中: {title}..."):
                start = time.time()
                rendered = render_article(article)
                elapsed = time.time() - start

            st.markdown(f"### 記事 {i}: 生成完了（{elapsed:.1f}秒）")
            st.markdown(rendered)
            st.divider()

    # ────────────────────────────────────
    # サマリー
    # ────────────────────────────────────
    st.header("実行サマリー")
    st.markdown(f"""
    | 項目 | 結果 |
    |---|---|
    | 収集記事数 | {len(articles)}件 |
    | ファクトチェック | A={rs['A']} / B={rs['B']} / C={rs['C']} |
    | 要注意箇所 | {len(report['attention_required'])}件 |
    | 生成ドラフト | {0 if skip_drafts else len(targets)}件 |
    """)

else:
    # 待機画面
    st.info("上のボタンを押すとパイプラインが実行されます")

    st.markdown("### このツールについて")
    st.markdown("""
    海外経済ニュースメディアの運営で最も時間を要する **情報収集** と **ファクトチェック** を自動化します。

    | 従来の手作業 | このツールで自動化 |
    |---|---|
    | 現地メディアを巡回して情報収集 | RSS自動収集（9ソース対応） |
    | 同じニュースが複数ソースにあるか確認 | 重複除去 + 複数ソース自動突合 |
    | 数値の正確性を原文で照合 | AI数値抽出 + ソース間矛盾検出 |
    | チェック結果をまとめる | 信頼度ラベル（A/B/C）付きレポート |
    | 記事の下書きを作成 | AI記事ドラフト（編集者確認ポイント付き） |
    """)
