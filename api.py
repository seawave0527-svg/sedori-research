"""
api.py - せどりリサーチ Web API（Flask）

Keepa APIで定価超え商品を取得し、楽天・Yahooで仕入れ価格を調べ、
利益計算した結果をJSONで返す。
"""

import os
import time
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

        # Step 2: 各商品を楽天・Yahooで検索（キーワードはタイトルの先頭部分）
        rakuten_results_map = {}
        yahoo_results_map   = {}

        for i, product in enumerate(premium_products):
            asin    = product["asin"]
            title   = product["title"]
            # タイトルが長い場合は先頭の重要部分だけを使う
            keyword = _make_search_keyword(title)

            print(f"[API] ({i+1}/{len(premium_products)}) 「{keyword}」を検索中...")

            # 楽天検索
            try:
                r_results = rakuten_search(keyword, limit=5)
                rakuten_results_map[asin] = r_results
                print(f"  楽天: {len(r_results)} 件")
            except Exception as e:
                print(f"  楽天エラー: {e}")
                rakuten_results_map[asin] = []

            # Yahoo!ショッピング検索
            try:
                y_results = yahoo_search(keyword, limit=5)
                yahoo_results_map[asin] = y_results
                print(f"  Yahoo: {len(y_results)} 件")
            except Exception as e:
                print(f"  Yahooエラー: {e}")
                yahoo_results_map[asin] = []

            # API過負荷防止のため少し待機
            if i < len(premium_products) - 1:
                time.sleep(0.5)

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
