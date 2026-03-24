"""
api.py - せどりリサーチ Web API
Flask バックエンド

Claude A（仕入れリサーチ担当: scraper.py）と
Claude B（利益分析担当: amazon.py）を連携させてリサーチ結果を返す。
"""

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from scraper import search_all_sites
from amazon import analyze_items

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    """フロントエンドHTMLを返す"""
    return render_template("index.html")


@app.route("/api/search", methods=["POST"])
def search():
    """
    仕入れリサーチAPIエンドポイント。

    Request body (JSON):
        {"keyword": "検索キーワード"}

    Response (JSON):
        {
            "keyword": "...",
            "results": [
                {
                    "site": "ヤフオク",
                    "name": "商品名",
                    "buy_price": 1000,
                    "amazon_price": 5000,
                    "fee": 1050,
                    "profit": 3950,
                    "profit_rate": 79.0,
                    "grade": "◎",
                    "is_mock": false
                },
                ...
            ]
        }
    """
    data = request.get_json(silent=True) or {}
    keyword = (data.get("keyword") or "").strip()

    if not keyword:
        return jsonify({"error": "keyword は必須です"}), 400

    try:
        # Phase 1: Claude A が仕入れサイトを全検索
        raw_items = search_all_sites(keyword, max_per_site=3)

        # Phase 2: Claude B が Amazon価格・利益を計算
        analyzed = analyze_items(raw_items, keyword)

        # レスポンス用に整形
        results = []
        for item in analyzed:
            results.append({
                "site":         item.get("site", "不明"),
                "name":         item.get("name", "不明商品"),
                "buy_price":    item.get("purchase_price", 0),
                "amazon_price": item.get("amazon_price", 0),
                "fee":          item.get("fee", 0),
                "profit":       item.get("profit", 0),
                "profit_rate":  item.get("profit_rate", 0.0),
                "grade":        item.get("grade", "?"),
                "url":          item.get("url", ""),
                "is_mock":      item.get("is_mock", False),
            })

        return jsonify({
            "keyword": keyword,
            "results": results,
        })

    except Exception as e:
        return jsonify({"error": f"リサーチ中にエラーが発生しました: {str(e)}"}), 500


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)
