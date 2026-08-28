"""
設定ファイル — InfoBank ベトナム経済ニュース AI パイプライン
"""
import os
from dotenv import load_dotenv

load_dotenv()

# OpenAI API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ──────────────────────────────────────────────
# 収集対象ソース（ベトナム経済ニュース）
# ──────────────────────────────────────────────
RSS_FEEDS = {
    # ベトナム国内メディア（英語版）
    "VnExpress International": "https://e.vnexpress.net/rss/news.rss",
    "VnExpress Business": "https://e.vnexpress.net/rss/business.rss",
    "Vietnam News": "https://vietnamnews.vn/rss/economy.rss",
    "VietnamNet Business": "https://vietnamnet.vn/en/rss/business.rss",
    "Tuoi Tre News": "https://tuoitrenews.vn/rss/business.rss",
    # 国際メディアのベトナム関連
    "Reuters Vietnam": "https://www.reuters.com/places/vietnam/rss",
    "Nikkei Asia Vietnam": "https://asia.nikkei.com/rss/feed/vietnam",
    "BBC Vietnam": "http://feeds.bbci.co.uk/vietnamese/rss.xml",
}

# ──────────────────────────────────────────────
# InfoBank カテゴリ定義（既存メディアに合わせる）
# ──────────────────────────────────────────────
INFOBANK_CATEGORIES = {
    "economy": {
        "name_ja": "経済",
        "keywords": [
            "gdp", "economic growth", "inflation", "trade", "export", "import",
            "fdi", "investment", "budget", "fiscal", "monetary", "dong", "vnd",
            "central bank", "state bank", "sbv", "interest rate", "forex",
            "stock", "market", "ipo", "bond", "securities",
        ],
    },
    "politics": {
        "name_ja": "政治",
        "keywords": [
            "government", "party", "congress", "national assembly", "minister",
            "prime minister", "president", "policy", "regulation", "decree",
            "law", "legislation", "communist", "politburo", "diplomacy",
        ],
    },
    "food": {
        "name_ja": "食品・外食",
        "keywords": [
            "food", "restaurant", "cafe", "coffee", "seafood", "rice",
            "beverage", "dairy", "meat", "agriculture food", "f&b",
            "dining", "franchise food", "snack", "confectionery",
        ],
    },
    "retail": {
        "name_ja": "卸・小売",
        "keywords": [
            "retail", "shopping", "mall", "e-commerce", "consumer",
            "supermarket", "convenience store", "wholesale", "distribution",
            "aeon", "vinmart", "winmart", "bach hoa xanh",
        ],
    },
    "service": {
        "name_ja": "サービス",
        "keywords": [
            "service", "tourism", "hotel", "travel", "fintech", "banking",
            "insurance", "telecom", "it service", "outsourcing", "bpo",
            "education", "training", "consulting",
        ],
    },
    "medical": {
        "name_ja": "医療・ヘルスケア",
        "keywords": [
            "health", "medical", "hospital", "pharmaceutical", "drug",
            "vaccine", "clinic", "healthcare", "biotech", "wellness",
        ],
    },
    "power-energy": {
        "name_ja": "電力・エネルギー",
        "keywords": [
            "energy", "power", "electricity", "solar", "wind", "renewable",
            "oil", "gas", "lng", "coal", "nuclear", "ev charging",
            "grid", "evn", "petrovietnam", "pvn",
        ],
    },
    "logistics": {
        "name_ja": "物流・倉庫",
        "keywords": [
            "logistics", "warehouse", "shipping", "port", "freight",
            "supply chain", "transport", "cargo", "container", "delivery",
            "cold chain", "3pl",
        ],
    },
    "automobile": {
        "name_ja": "自動車",
        "keywords": [
            "automobile", "car", "vehicle", "ev", "electric vehicle",
            "vinfast", "toyota", "hyundai", "honda car", "thaco",
            "auto", "automotive",
        ],
    },
    "real-estate": {
        "name_ja": "不動産・建設",
        "keywords": [
            "real estate", "property", "housing", "apartment", "condo",
            "construction", "infrastructure", "industrial park", "office",
            "building", "developer", "vinhomes", "novaland",
        ],
    },
    "agri": {
        "name_ja": "農業",
        "keywords": [
            "agriculture", "farming", "crop", "rice", "coffee bean",
            "rubber", "pepper", "cashew", "aquaculture", "fishery",
            "shrimp", "pangasius", "livestock", "fertilizer",
        ],
    },
    "motor-bike": {
        "name_ja": "二輪車",
        "keywords": [
            "motorcycle", "motorbike", "scooter", "honda bike", "yamaha",
            "two-wheeler", "electric bike", "e-bike",
        ],
    },
    "taxation": {
        "name_ja": "税務・会計",
        "keywords": [
            "tax", "taxation", "vat", "corporate tax", "accounting",
            "audit", "customs", "duty", "transfer pricing", "invoice",
        ],
    },
    "legal": {
        "name_ja": "法律・法務",
        "keywords": [
            "law", "legal", "court", "regulation", "compliance",
            "intellectual property", "labor law", "contract", "license",
            "dispute", "arbitration",
        ],
    },
    "human-resources-and-labor-affairs": {
        "name_ja": "人事労務",
        "keywords": [
            "labor", "employment", "hiring", "salary", "wage",
            "human resource", "hr", "workforce", "worker", "recruitment",
            "layoff", "minimum wage", "social insurance",
        ],
    },
}

# ──────────────────────────────────────────────
# AI・記事生成設定
# ──────────────────────────────────────────────
ARTICLE_CONFIG = {
    "model": "gpt-4o-mini",
    "max_articles_per_run": 5,
    "target_language": "ja",
    "source_languages": ["en", "vi"],
    "min_sources_for_factcheck": 2,
    "article_length_chars": 800,  # InfoBankの記事は800〜1500字程度
}

# 出力先
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
