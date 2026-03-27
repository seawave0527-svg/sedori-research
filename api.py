"""
api.py - せどりリサーチ Web API（Flask）

Keepa APIで定価超え商品を取得し、楽天・Yahooで仕入れ価格を調べ、
利益計算した結果をJSONで返す。
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from keepa_client import find_premium_products, CATEGORY_MAP
from rakuten_client import search_product as rakuten_search
from yahoo_client import search_product as yahoo_search
from profit_calculator import find_best_deals

app = Flask(__name__)
CORS(app)

# カテゴリ表示名
CATEGORY_LABELS = {
    "game":        "テレビゲーム",
    "electronics": "家電・カメラ",
    "toys":        "おもちゃ",
    "books":       "本・コミック",
    "other":       "その他",
}


@app.route("/")
def index():
    """フロントエンドHTMLを返す"""
    return render_template("index.html")


@app.route("/api/categories", methods=["GET"])
def get_categories():
    """検索できるカテゴリ一覧を返す"""
    categories = [
        {"id": key, "name": label}
        for key, label in CATEGORY_LABELS.items()
    ]
    return jsonify({"categories": categories})


@app.route("/api/research", methods=["POST"])
def research():
    """
    プレミアム商品リサーチAPIエンドポイント。

    Request body (JSON):
        {
            "category": "game",   // カテゴリID（省略可）
            "limit":    20        // 取得件数（省略可、デフォルト20）
        }

    Response (JSON):
        {
            "status":   "ok",
            "category": "game",
            "count":    10,
            "results":  [
                {
                    "asin":            "B0XXXXXX",
                    "title":           "商品名",
                    "amazon_price":    8000,
                    "list_price":      5000,
                    "price_diff":      3000,
                    "price_diff_rate": 60.0,
                    "buy_price":       3500,
                    "buy_source":      "楽天市場",
                    "buy_url":         "https://...",
                    "buy_shop":        "ショップ名",
                    "profit":          3700,
                    "profit_rate":     46.3,
                    "fee":             800,
                    "grade":           "◎"
                },
                ...
            ]
        }
    """
    data     = request.get_json(silent=True) or {}
    category = (data.get("category") or "other").strip()
    limit    = min(int(data.get("limit", 20)), 50)

    # カテゴリ検証
    if category not in CATEGORY_LABELS:
        category = "other"

    try:
        # Step 1: Keepaで定価超え商品を取得
        print(f"[API] Keepaで {category} カテゴリのプレミアム商品を検索中... (limit={limit})")
        premium_products = find_premium_products(category=category, limit=limit)
        print(f"[API] Keepa結果: {len(premium_products)} 件")

        if not premium_products:
            return jsonify({
                "status":   "ok",
                "category": category,
                "count":    0,
                "results":  [],
                "message":  "Keepaで定価超え商品が見つかりませんでした。",
            })

        # Step 2: 各商品を楽天・Yahooで並列検索
        rakuten_results_map = {}
        yahoo_results_map   = {}

        def fetch_rakuten(product):
            asin    = product["asin"]
            keyword = _make_search_keyword(product["title"])
            try:
                results = rakuten_search(keyword, limit=5)
                print(f"  [楽天] {keyword[:20]}... → {len(results)}件")
                return asin, results
            except Exception as e:
                print(f"  [楽天エラー] {e}")
                return asin, []

        def fetch_yahoo(product):
            asin    = product["asin"]
            keyword = _make_search_keyword(product["title"])
            try:
                results = yahoo_search(keyword, limit=5)
                print(f"  [Yahoo] {keyword[:20]}... → {len(results)}件")
                return asin, results
            except Exception as e:
                print(f"  [Yahooエラー] {e}")
                return asin, []

        print(f"[API] {len(premium_products)}件を並列検索中...")
        with ThreadPoolExecutor(max_workers=6) as executor:
            r_futures = {executor.submit(fetch_rakuten, p): p for p in premium_products}
            y_futures = {executor.submit(fetch_yahoo,   p): p for p in premium_products}
            for f in as_completed(r_futures):
                asin, results = f.result()
                rakuten_results_map[asin] = results
            for f in as_completed(y_futures):
                asin, results = f.result()
                yahoo_results_map[asin] = results

        # Step 3: 利益計算
        print("[API] 利益計算中...")
        deals = find_best_deals(
            premium_products=premium_products,
            rakuten_results_map=rakuten_results_map,
            yahoo_results_map=yahoo_results_map,
            category=category,
        )

        print(f"[API] 完了: {len(deals)} 件の結果")

        return jsonify({
            "status":   "ok",
            "category": category,
            "count":    len(deals),
            "results":  deals,
        })

    except Exception as e:
        print(f"[API] リサーチエラー: {e}")
        return jsonify({
            "status":  "error",
            "message": f"リサーチ中にエラーが発生しました: {str(e)}",
        }), 500


def _make_search_keyword(title):
    """
    商品タイトルから検索キーワードを生成する。
    タイトルが長すぎる場合は最初の30文字程度に絞る。
    """
    if not title:
        return ""
    # 括弧内の補足情報を除去
    import re
    cleaned = re.sub(r"[（(].*?[）)]", "", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # 先頭40文字まで
    return cleaned[:40]


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)
