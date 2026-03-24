"""
keepa_client.py - Keepa API クライアント（日本Amazon）

「現在価格 > 過去最安値 × 1.2」の商品を
プレミアム商品として返す。
"""

import requests
import json

KEEPA_API_KEY = "7mitc0lbc1kdg8ntb2dqsb68j1t4badbs05aegktml4aagv39fijai836ijcgvpc"
KEEPA_BASE_URL = "https://api.keepa.com"

CATEGORY_MAP = {
    "game":        None,
    "electronics": None,
    "toys":        None,
    "books":       None,
    "other":       None,
}

KEYWORD_MAP = {
    "game":        "Nintendo Switch ゲームソフト",
    "electronics": "家電 カメラ",
    "toys":        "おもちゃ フィギュア",
    "books":       "コミック 漫画",
    "other":       "",
}


def find_premium_products(category=None, limit=20):
    """
    現在価格が過去最安値より高い商品（プレミアム商品）を取得する。
    """
    results = []

    try:
        # ASINリスト取得
        selection = {
            "page": 0,
            "perPage": 100,
            "sort": [6, 1],
            "current_AMAZON": [500, 200000],
        }

        resp = requests.get(
            f"{KEEPA_BASE_URL}/query",
            params={
                "key": KEEPA_API_KEY,
                "domain": 5,
                "selection": json.dumps(selection),
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        asin_list = data.get("asinList", [])

        if not asin_list:
            return results

        # 商品詳細を取得（最大50件）
        asins = asin_list[:50]
        resp2 = requests.get(
            f"{KEEPA_BASE_URL}/product",
            params={
                "key": KEEPA_API_KEY,
                "domain": 5,
                "asin": ",".join(asins),
                "history": 1,
            },
            timeout=30,
        )
        resp2.raise_for_status()
        products = resp2.json().get("products", [])

        for product in products:
            if len(results) >= limit:
                break
            try:
                item = _parse_product(product)
                if item:
                    results.append(item)
            except Exception as e:
                print(f"[Keepa] パースエラー: {e}")
                continue

    except Exception as e:
        print(f"[Keepa] エラー: {e}")

    return results


def _parse_product(product):
    """商品データを解析してプレミアム判定する"""
    asin = product.get("asin", "")
    title = product.get("title") or ""

    if not title or not asin:
        return None

    csv = product.get("csv") or []

    # Amazon価格履歴 (csv[0])
    # ※ Keepa日本ドメインはJPY整数（100倍不要）
    price_history = csv[0] if csv and len(csv) > 0 else None
    if not price_history or len(price_history) < 4:
        return None

    # 現在価格（最新の値）
    current_price = None
    for i in range(len(price_history) - 1, 0, -2):
        val = price_history[i]
        if val and val > 0:
            current_price = val
            break

    if not current_price:
        return None

    # 過去最安値
    prices = [price_history[i] for i in range(1, len(price_history), 2)
              if price_history[i] and price_history[i] > 0]

    if not prices:
        return None

    min_price = min(prices)
    avg_price = sum(prices) / len(prices)

    # RRP（定価）があれば使う、なければ平均価格を参考定価とする
    rrp = product.get("rrp", -1)
    if rrp and rrp > 0:
        list_price = rrp
    else:
        list_price = avg_price

    # プレミアム判定: 現在価格が過去最安値の1.15倍以上
    if current_price < min_price * 1.15:
        return None

    price_diff = current_price - min_price
    price_diff_rate = (price_diff / min_price) * 100 if min_price > 0 else 0

    # 安すぎ・高すぎ除外
    if current_price < 500 or current_price > 300000:
        return None

    return {
        "asin": asin,
        "title": title,
        "current_price": int(current_price),
        "list_price": int(list_price),
        "min_price": int(min_price),
        "price_diff": int(price_diff),
        "price_diff_rate": round(price_diff_rate, 1),
        "amazon_url": f"https://www.amazon.co.jp/dp/{asin}",
    }
