"""
rakuten_client.py - 楽天市場スクレイピングクライアント

楽天市場の検索結果をスクレイピングして商品情報を取得する。
"""

import requests
from bs4 import BeautifulSoup
import time
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "ja-JP,ja;q=0.9",
}


def search_product(keyword, limit=5):
    """
    楽天市場で商品を検索する（スクレイピング）。

    Parameters
    ----------
    keyword : str
    limit : int

    Returns
    -------
    list of dict [{name, price, url, shop}]
    """
    results = []
    if not keyword:
        return results

    try:
        url = "https://search.rakuten.co.jp/search/mall/"
        params = {
            "qt": keyword.strip(),
            "s": "2",   # 価格安い順
            "p": 1,
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        items = soup.select("div.searchresultitem, .dui-card, [data-item]")
        if not items:
            items = soup.select(".item")

        for item in items[:limit]:
            try:
                # 商品名
                name_el = item.select_one(".title a, .itemName a, h2 a, .name a")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                item_url = name_el.get("href", "")

                # 価格
                price_el = item.select_one(".price, .important, .itemPrice")
                if not price_el:
                    continue
                price_text = price_el.get_text(strip=True)
                price = _extract_price(price_text)
                if not price:
                    continue

                # ショップ名
                shop_el = item.select_one(".shopName, .shop, .merchant")
                shop = shop_el.get_text(strip=True) if shop_el else "楽天市場"

                results.append({
                    "name": name[:60],
                    "price": price,
                    "url": item_url,
                    "shop": shop,
                })
            except Exception:
                continue

        if not results:
            # フォールバック: 別のセレクターで試す
            results = _search_fallback(keyword, limit)

    except Exception as e:
        print(f"[楽天] エラー: {e}")
        results = _search_fallback(keyword, limit)

    return results[:limit]


def _search_fallback(keyword, limit):
    """フォールバック: 楽天モバイルページをスクレイピング"""
    results = []
    try:
        url = f"https://search.rakuten.co.jp/search/mall/{requests.utils.quote(keyword)}/?s=2"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")

        for a_tag in soup.select("a[href*='item.rakuten']")[:limit * 2]:
            name = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")
            if name and len(name) > 5:
                # 近くの価格要素を探す
                parent = a_tag.find_parent()
                price = 0
                if parent:
                    price_text = parent.get_text()
                    price = _extract_price(price_text) or 0

                if price > 0:
                    results.append({
                        "name": name[:60],
                        "price": price,
                        "url": href,
                        "shop": "楽天市場",
                    })
                    if len(results) >= limit:
                        break
    except Exception as e:
        print(f"[楽天フォールバック] エラー: {e}")
    return results


def _extract_price(text):
    """テキストから価格（整数）を抽出する"""
    nums = re.findall(r"[\d,]+", text.replace("，", ","))
    for n in nums:
        val = int(n.replace(",", ""))
        if 100 <= val <= 10_000_000:
            return val
    return None
