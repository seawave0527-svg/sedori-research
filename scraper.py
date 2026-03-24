"""
scraper.py - 各仕入れサイトのスクレイピング関数
Claude A（仕入れリサーチ担当）モジュール
"""

import requests
from bs4 import BeautifulSoup
import time
import random
import re
from typing import List, Dict, Optional

# ---------------------------------------------------------------------------
# 共通設定
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "DNT": "1",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _sleep():
    """礼儀正しいクローリングのためのランダム待機"""
    time.sleep(random.uniform(1.0, 2.5))


def _get(url: str, params: dict = None, timeout: int = 10) -> Optional[BeautifulSoup]:
    """GETリクエスト共通処理。失敗時はNoneを返す"""
    try:
        resp = SESSION.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"    [取得失敗] {url} → {e}")
        return None


def _clean_price(text: str) -> Optional[int]:
    """価格文字列から数値を抽出する"""
    if not text:
        return None
    nums = re.sub(r"[^\d]", "", text)
    return int(nums) if nums else None


# ---------------------------------------------------------------------------
# 1. メルカリ
# ---------------------------------------------------------------------------

def scrape_mercari(keyword: str, max_items: int = 5) -> List[Dict]:
    """
    メルカリ検索結果をスクレイピング。
    方式1: 公開検索APIエンドポイント
    方式2: モバイルサイトHTMLパース（フォールバック）
    """
    results = []

    # 方式1: 公開検索ページのHTMLをパース（モバイルUA）
    search_url = "https://jp.mercari.com/search"
    params = {"keyword": keyword, "status": "on_sale"}
    mobile_headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.0 Mobile/15E148 Safari/604.1"
        ),
        "Accept-Language": "ja-JP,ja;q=0.9",
    }
    try:
        resp = SESSION.get(search_url, params=params, headers=mobile_headers, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # メルカリはNext.js製のため、埋め込みJSONからデータを抽出
        import json as _json
        scripts = soup.find_all("script", {"id": "__NEXT_DATA__"})
        for script in scripts:
            try:
                data = _json.loads(script.string or "{}")
                # ページデータ内のアイテムリストを探索
                items_data = (
                    data.get("props", {})
                        .get("pageProps", {})
                        .get("initialSearchCondition", {})
                )
                # 別パス
                search_items = (
                    data.get("props", {})
                        .get("pageProps", {})
                        .get("items", [])
                )
                for item in search_items[:max_items]:
                    price = item.get("price") or item.get("sell_price")
                    name  = item.get("name") or item.get("item_name", "不明")
                    iid   = item.get("id") or item.get("item_id", "")
                    if price:
                        results.append({
                            "site": "メルカリ",
                            "name": str(name)[:60],
                            "price": int(price),
                            "url": f"https://jp.mercari.com/item/{iid}",
                            "condition": "中古",
                        })
            except Exception:
                continue

    except Exception as e:
        print(f"    [メルカリHTMLエラー] {e}")

    # 方式2: 内部APIエンドポイント（取得できなかった場合）
    if not results:
        api_url = "https://api.mercari.jp/v2/entities:search"
        payload = {
            "pageSize": max_items,
            "pageToken": "",
            "searchSessionId": "",
            "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
            "thumbnailTypes": [],
            "searchCondition": {
                "keyword": keyword,
                "excludeKeyword": "",
                "sort": "SORT_SCORE",
                "order": "ORDER_DESC",
                "status": ["STATUS_ON_SALE"],
                "sizeId": [], "categoryId": [], "brandId": [],
                "sellerId": [], "priceMin": 0, "priceMax": 0,
                "itemConditionId": [], "shippingPayerId": [],
                "shippingFromArea": [], "shippingMethod": [],
                "hasCoupon": False, "attributes": [],
                "buyerLeadTimeMax": 0,
            },
            "defaultDatasets": ["DATASET_TYPE_MERCARI", "DATASET_TYPE_BEYOND"],
        }
        api_headers = {
            **HEADERS,
            "X-Platform": "web",
            "Content-Type": "application/json; charset=utf-8",
        }
        try:
            resp = SESSION.post(api_url, json=payload, headers=api_headers, timeout=10)
            data = resp.json()
            items = data.get("items", [])
            for item in items[:max_items]:
                price = item.get("price")
                name  = item.get("name", "不明")
                if price:
                    results.append({
                        "site": "メルカリ",
                        "name": name[:60],
                        "price": int(price),
                        "url": f"https://jp.mercari.com/item/{item.get('id', '')}",
                        "condition": item.get("itemCondition", {}).get("name", "不明"),
                    })
        except Exception as e:
            print(f"    [メルカリAPIエラー] {e}")

    # 両方失敗した場合はモックデータ
    if not results:
        results = _mock_results("メルカリ", keyword, max_items)

    _sleep()
    return results


# ---------------------------------------------------------------------------
# 2. ヤフオク（終了済み落札データ）
# ---------------------------------------------------------------------------

def scrape_yahuoku(keyword: str, max_items: int = 5) -> List[Dict]:
    """ヤフオク 落札済み商品から相場を調査"""
    results = []
    url = "https://auctions.yahoo.co.jp/search/search"
    params = {
        "p": keyword,
        "va": keyword,
        "b": 1,
        "n": max_items,
        "s1": "end",
        "o1": "d",
        "abatch": 1,  # 出品終了分を含む
    }
    soup = _get(url, params=params)
    if soup is None:
        return _mock_results("ヤフオク", keyword, max_items)

    try:
        items = soup.select("li.Product")
        for item in items[:max_items]:
            name_el = item.select_one(".Product__title a")
            price_el = item.select_one(".Product__priceValue")
            if not name_el or not price_el:
                continue
            price = _clean_price(price_el.get_text())
            if price:
                results.append({
                    "site": "ヤフオク",
                    "name": name_el.get_text(strip=True)[:60],
                    "price": price,
                    "url": name_el.get("href", ""),
                    "condition": "中古",
                })
    except Exception as e:
        print(f"    [ヤフオクパースエラー] {e}")
        results = _mock_results("ヤフオク", keyword, max_items)

    _sleep()
    return results


# ---------------------------------------------------------------------------
# 3. Yahoo!フリマ（旧PayPayフリマ）
# ---------------------------------------------------------------------------

def scrape_yahoo_fleamarket(keyword: str, max_items: int = 5) -> List[Dict]:
    """Yahoo!フリマ スクレイピング"""
    results = []
    # URLは末尾スラッシュなし（旧PayPayフリマURL）
    url = "https://paypayfleamarket.yahoo.co.jp/search"
    params = {"q": keyword}
    soup = _get(url, params=params)
    if soup is None:
        return _mock_results("Yahoo!フリマ", keyword, max_items)

    try:
        # Yahoo!フリマはReact SPAのためJSONデータをHTMLに埋め込む形式
        scripts = soup.find_all("script", {"type": "application/ld+json"})
        count = 0
        for script in scripts:
            if count >= max_items:
                break
            try:
                import json
                data = json.loads(script.string or "{}")
                if data.get("@type") == "Product":
                    price = data.get("offers", {}).get("price")
                    name = data.get("name", "不明")
                    if price:
                        results.append({
                            "site": "Yahoo!フリマ",
                            "name": str(name)[:60],
                            "price": int(float(price)),
                            "url": data.get("url", ""),
                            "condition": "中古",
                        })
                        count += 1
            except Exception:
                continue

        if not results:
            # JavaScriptレンダリング必要のため代替としてモック
            results = _mock_results("Yahoo!フリマ", keyword, max_items)
    except Exception as e:
        print(f"    [Yahoo!フリマパースエラー] {e}")
        results = _mock_results("Yahoo!フリマ", keyword, max_items)

    _sleep()
    return results


# ---------------------------------------------------------------------------
# 4. オフモール（ハードオフグループ）
# ---------------------------------------------------------------------------

def scrape_offmall(keyword: str, max_items: int = 5) -> List[Dict]:
    """オフモール スクレイピング"""
    results = []
    # オフモール: ハードオフグループのオンラインストア
    url = "https://www.hardoff.co.jp/search/"
    params = {"q": keyword, "limit": max_items}
    soup = _get(url, params=params)
    if soup is None:
        return _mock_results("オフモール", keyword, max_items)

    try:
        items = soup.select(".product-list-item, .p-item-box, li.item")
        for item in items[:max_items]:
            name_el = item.select_one(".product-name, .p-item-name, .item-name")
            price_el = item.select_one(".product-price, .p-item-price, .item-price")
            link_el = item.select_one("a")
            if not name_el or not price_el:
                continue
            price = _clean_price(price_el.get_text())
            if price:
                results.append({
                    "site": "オフモール",
                    "name": name_el.get_text(strip=True)[:60],
                    "price": price,
                    "url": "https://www.offmall.jp" + (link_el.get("href", "") if link_el else ""),
                    "condition": "中古",
                })
    except Exception as e:
        print(f"    [オフモールパースエラー] {e}")
        results = _mock_results("オフモール", keyword, max_items)

    if not results:
        results = _mock_results("オフモール", keyword, max_items)

    _sleep()
    return results


# ---------------------------------------------------------------------------
# 5. セカンドストリートオンライン
# ---------------------------------------------------------------------------

def scrape_2ndstreet(keyword: str, max_items: int = 5) -> List[Dict]:
    """セカンドストリートオンライン スクレイピング"""
    results = []
    url = "https://www.2ndstreet.jp/goods/list"
    params = {"keyword": keyword, "page": 1}
    # 2ndstreetは403になる場合があるのでRefererを付与
    headers_extra = {**HEADERS, "Referer": "https://www.2ndstreet.jp/"}
    try:
        resp = SESSION.get(url, params=params, headers=headers_extra, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"    [取得失敗] {url} → {e}")
        soup = None
    if soup is None:
        return _mock_results("セカンドストリート", keyword, max_items)

    try:
        # セレクターは実際のHTML構造に合わせて調整
        items = soup.select(".item-card, .goods-list-item, .c-item-card")
        for item in items[:max_items]:
            name_el = item.select_one(".item-name, .goods-name, .c-item-card__title")
            price_el = item.select_one(".item-price, .goods-price, .c-item-card__price")
            link_el = item.select_one("a")
            if not name_el or not price_el:
                continue
            price = _clean_price(price_el.get_text())
            if price:
                href = link_el.get("href", "") if link_el else ""
                results.append({
                    "site": "セカンドストリート",
                    "name": name_el.get_text(strip=True)[:60],
                    "price": price,
                    "url": href if href.startswith("http") else "https://www.2ndstreet.jp" + href,
                    "condition": "中古",
                })
    except Exception as e:
        print(f"    [セカンドストリートパースエラー] {e}")
        results = _mock_results("セカンドストリート", keyword, max_items)

    if not results:
        results = _mock_results("セカンドストリート", keyword, max_items)

    _sleep()
    return results


# ---------------------------------------------------------------------------
# 6. トレファクオンライン
# ---------------------------------------------------------------------------

def scrape_torefac(keyword: str, max_items: int = 5) -> List[Dict]:
    """トレファクオンライン スクレイピング"""
    results = []
    # トレファクオンライン（トレジャーファクトリー）
    url = "https://www.torefac.com/products/search"
    params = {"keyword": keyword, "page": 1}
    soup = _get(url, params=params)
    if soup is None:
        return _mock_results("トレファク", keyword, max_items)

    try:
        items = soup.select(".product-item, .item-box, .p-item")
        for item in items[:max_items]:
            name_el = item.select_one(".product-name, .item-name, .p-name")
            price_el = item.select_one(".product-price, .item-price, .p-price")
            link_el = item.select_one("a")
            if not name_el or not price_el:
                continue
            price = _clean_price(price_el.get_text())
            if price:
                href = link_el.get("href", "") if link_el else ""
                results.append({
                    "site": "トレファク",
                    "name": name_el.get_text(strip=True)[:60],
                    "price": price,
                    "url": href if href.startswith("http") else "https://torefac.com" + href,
                    "condition": "中古",
                })
    except Exception as e:
        print(f"    [トレファクパースエラー] {e}")
        results = _mock_results("トレファク", keyword, max_items)

    if not results:
        results = _mock_results("トレファク", keyword, max_items)

    _sleep()
    return results


# ---------------------------------------------------------------------------
# モックデータ生成（スクレイピング失敗時のフォールバック）
# ---------------------------------------------------------------------------

def _mock_results(site: str, keyword: str, count: int = 3) -> List[Dict]:
    """
    スクレイピングが困難なサイト向けのデモデータ。
    実際の運用では削除またはSelenium等に置き換える。
    ※ 価格はキーワードのhash値から疑似的に生成（再現性あり）
    """
    import hashlib
    base = int(hashlib.md5(f"{site}{keyword}".encode()).hexdigest()[:6], 16) % 3000 + 500
    mock_items = []
    for i in range(min(count, 3)):
        variation = int(hashlib.md5(f"{site}{keyword}{i}".encode()).hexdigest()[:4], 16) % 500
        price = base + variation * (1 if i % 2 == 0 else -1)
        price = max(price, 100)
        mock_items.append({
            "site": site,
            "name": f"[モック] {keyword} 関連商品 {i+1}",
            "price": price,
            "url": "",
            "condition": "中古",
            "is_mock": True,
        })
    return mock_items


# ---------------------------------------------------------------------------
# 全サイト一括検索
# ---------------------------------------------------------------------------

def search_all_sites(keyword: str, max_per_site: int = 3) -> List[Dict]:
    """全仕入れサイトを検索して結果を統合する"""
    all_results = []

    scrapers = [
        ("メルカリ",           scrape_mercari),
        ("ヤフオク",           scrape_yahuoku),
        ("Yahoo!フリマ",       scrape_yahoo_fleamarket),
        ("オフモール",         scrape_offmall),
        ("セカンドストリート", scrape_2ndstreet),
        ("トレファク",         scrape_torefac),
    ]

    for site_name, func in scrapers:
        print(f"  🔍 {site_name} を検索中...", end="", flush=True)
        try:
            items = func(keyword, max_items=max_per_site)
            all_results.extend(items)
            print(f" {len(items)}件取得")
        except Exception as e:
            print(f" エラー: {e}")

    return all_results
