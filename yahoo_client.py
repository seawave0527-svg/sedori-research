"""
yahoo_client.py - Yahoo!ショッピング スクレイピングクライアント

Yahoo!ショッピングをBeautifulSoupでスクレイピングして商品を取得する。
安い順（PRI_A）でソートして返す。
"""

import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

YAHOO_SEARCH_BASE = "https://shopping.yahoo.co.jp/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def search_product(keyword, limit=5):
    """
    Yahoo!ショッピングで商品をスクレイピングして検索する。

    Parameters
    ----------
    keyword : str
        検索キーワード
    limit : int
        取得件数

    Returns
    -------
    list of dict
        [{name, price, url, shop}, ...]
        取得失敗時は空リスト
    """
    results = []

    if not keyword or not keyword.strip():
        return results

    try:
        encoded_keyword = quote(keyword.strip())
        url = f"{YAHOO_SEARCH_BASE}?p={encoded_keyword}&sort=PRI_A&in_stock=1"

        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        results = _parse_search_results(soup, limit)

    except requests.exceptions.HTTPError as e:
        print(f"[Yahoo] HTTPエラー: {e}")
    except requests.exceptions.RequestException as e:
        print(f"[Yahoo] リクエストエラー: {e}")
    except Exception as e:
        print(f"[Yahoo] 予期しないエラー: {e}")

    return results


def _parse_search_results(soup, limit):
    """BeautifulSoupオブジェクトから商品情報を抽出する。"""
    results = []

    # Yahoo!ショッピングの商品リストセレクター（複数パターン試行）
    item_selectors = [
        "li.SearchResultItemUnit",
        "li[class*='SearchResult']",
        "div.SearchResult",
        "li.Item",
        "div[data-item]",
        "li[class*='item']",
        ".elGridItem",
        ".LoopItemInner",
    ]

    items = []
    for selector in item_selectors:
        items = soup.select(selector)
        if items:
            break

    # セレクターで見つからない場合はscriptタグからJSONを探す
    if not items:
        results = _parse_from_json_ld(soup, limit)
        if results:
            return results

    for item in items:
        if len(results) >= limit:
            break
        try:
            parsed = _parse_item(item)
            if parsed and parsed.get("price", 0) > 0:
                results.append(parsed)
        except Exception as e:
            print(f"[Yahoo] アイテムパースエラー: {e}")
            continue

    return results


def _parse_item(item):
    """個別の商品要素から情報を抽出する。"""
    # 商品名
    name = None
    name_selectors = [
        "a.SearchResultItem__title",
        ".itemName",
        "h3 a",
        "h2 a",
        ".title a",
        "a[class*='title']",
        "a[class*='name']",
        ".elTitle a",
    ]
    for sel in name_selectors:
        el = item.select_one(sel)
        if el:
            name = el.get_text(strip=True)
            break

    if not name:
        a_tags = item.find_all("a")
        for a in a_tags:
            text = a.get_text(strip=True)
            if len(text) > 5:
                name = text
                break

    if not name:
        return None

    # 価格
    price = None
    price_selectors = [
        ".SearchResultItem__price",
        ".itemPrice",
        "span.price",
        "[class*='price']",
        ".elPrice",
    ]
    for sel in price_selectors:
        el = item.select_one(sel)
        if el:
            price = _extract_price(el.get_text())
            if price:
                break

    if not price:
        # テキスト全体から価格パターンを探す
        text = item.get_text()
        price = _extract_price(text)

    if not price:
        return None

    # URL
    url = ""
    url_selectors = ["a[href*='/store/']", "a[href*='store.shopping']", "a[href]"]
    for sel in url_selectors:
        el = item.select_one(sel)
        if el:
            href = el.get("href", "")
            if href:
                if href.startswith("http"):
                    url = href
                elif href.startswith("/"):
                    url = "https://shopping.yahoo.co.jp" + href
                break

    # ショップ名
    shop = "Yahoo!ショッピング"
    shop_selectors = [
        ".SearchResultItem__store",
        ".storeName",
        "[class*='store']",
        "[class*='shop']",
    ]
    for sel in shop_selectors:
        el = item.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text:
                shop = text
                break

    return {
        "name":  name[:100],  # 長すぎる場合は切る
        "price": int(price),
        "url":   url,
        "shop":  shop,
    }


def _parse_from_json_ld(soup, limit):
    """JSON-LDスクリプトから商品情報を取得する（フォールバック）。"""
    import json
    results = []

    try:
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    for item in data:
                        if len(results) >= limit:
                            break
                        parsed = _parse_json_ld_item(item)
                        if parsed:
                            results.append(parsed)
                elif isinstance(data, dict):
                    parsed = _parse_json_ld_item(data)
                    if parsed:
                        results.append(parsed)
            except json.JSONDecodeError:
                continue
    except Exception as e:
        print(f"[Yahoo] JSON-LDパースエラー: {e}")

    return results


def _parse_json_ld_item(item):
    """JSON-LDアイテムから商品情報を抽出する。"""
    try:
        item_type = item.get("@type", "")
        if item_type not in ("Product", "Offer"):
            return None

        name = item.get("name", "")
        if not name:
            return None

        price = None
        offers = item.get("offers", item.get("Offers", {}))
        if isinstance(offers, dict):
            price = _extract_price(str(offers.get("price", "")))
        elif isinstance(offers, list) and offers:
            price = _extract_price(str(offers[0].get("price", "")))

        if not price:
            return None

        url = item.get("url", "")

        return {
            "name":  name,
            "price": int(price),
            "url":   url,
            "shop":  "Yahoo!ショッピング",
        }
    except Exception:
        return None


def _extract_price(text):
    """テキストから価格（数値）を抽出する。"""
    if not text:
        return None
    # カンマ・円記号・スペースを除去して数値を抽出
    cleaned = re.sub(r"[^\d,]", "", text.replace(",", ""))
    digits = re.search(r"\d+", cleaned)
    if digits:
        val = int(digits.group())
        # 妥当な価格範囲チェック（1円〜100万円）
        if 1 <= val <= 1_000_000:
            return val
    return None
