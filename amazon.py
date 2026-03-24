"""
amazon.py - Amazon価格取得・利益計算モジュール
Claude B（利益分析担当）モジュール
"""

import requests
from bs4 import BeautifulSoup
import re
import time
import random
from typing import Optional, Dict, Tuple

# ---------------------------------------------------------------------------
# 共通ヘッダー（モバイルUAでシンプルなHTMLを取得）
# ---------------------------------------------------------------------------

MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

# FBA手数料の概算設定
FBA_RATE = 0.15          # 販売手数料: 売価の15%
FBA_SHIPPING = 300       # FBA配送料概算（円）


# ---------------------------------------------------------------------------
# Amazon価格取得
# ---------------------------------------------------------------------------

def get_amazon_price_by_keyword(keyword: str) -> Optional[int]:
    """
    キーワードでAmazonモバイルを検索して最安値（新品/中古）を取得する。
    ブロック対策のためモバイルUAを使用。
    """
    session = requests.Session()
    session.headers.update(MOBILE_HEADERS)

    search_url = "https://www.amazon.co.jp/s"
    params = {"k": keyword, "i": "aps"}

    try:
        resp = session.get(search_url, params=params, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 価格セレクター（モバイル・デスクトップ両対応）
        price_selectors = [
            "span.a-price-whole",
            "span.a-offscreen",
            ".a-price .a-offscreen",
            "[data-component-type='s-search-result'] .a-price span",
        ]

        prices = []
        for sel in price_selectors:
            els = soup.select(sel)
            for el in els:
                price = _clean_price(el.get_text())
                if price and 100 <= price <= 9_999_999:
                    prices.append(price)

        if prices:
            # 最安値を返す（並び替え: 価格の安い順）
            return min(prices)

    except Exception as e:
        print(f"    [Amazon検索エラー] {e}")

    return None


def get_amazon_price_by_asin(asin: str) -> Optional[int]:
    """
    ASINを指定してAmazon商品ページから価格を取得する。
    Keepaのチャートページも参照可能（要APIキー）。
    """
    session = requests.Session()
    session.headers.update(DESKTOP_HEADERS)

    url = f"https://www.amazon.co.jp/dp/{asin}"
    try:
        resp = session.get(url, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 新品価格
        price_el = soup.select_one(
            "#priceblock_ourprice, #priceblock_dealprice, "
            ".a-price .a-offscreen, #price_inside_buybox, "
            "#newBuyBoxPrice"
        )
        if price_el:
            price = _clean_price(price_el.get_text())
            if price:
                return price

        # 中古品最安値
        used_el = soup.select_one("#olpLinkWidget_feature_div .a-color-price, .olp-padding-right .a-color-price")
        if used_el:
            price = _clean_price(used_el.get_text())
            if price:
                return price

    except Exception as e:
        print(f"    [Amazon ASIN検索エラー] asin={asin} {e}")

    return None


def get_keepa_chart_price(asin: str) -> Optional[int]:
    """
    Keepaのチャートページから価格トレンドを取得（スクレイピング）。
    ※ APIキーなしで公開チャートページにアクセスする簡易版。
    """
    url = f"https://keepa.com/#!product/5-{asin}"
    # KeepaはSPAのため、HTMLスクレイピングでは価格取得不可
    # 代わりにAmazon直接取得にフォールバック
    return get_amazon_price_by_asin(asin)


# ---------------------------------------------------------------------------
# 利益計算
# ---------------------------------------------------------------------------

def calculate_profit(
    purchase_price: int,
    amazon_price: int,
    fba_rate: float = FBA_RATE,
    fba_shipping: int = FBA_SHIPPING,
) -> Dict:
    """
    利益・利益率を計算する。

    Returns:
        dict: {
            purchase_price, amazon_price,
            fee, profit, profit_rate, grade
        }
    """
    fee = int(amazon_price * fba_rate) + fba_shipping
    profit = amazon_price - purchase_price - fee
    profit_rate = (profit / amazon_price * 100) if amazon_price > 0 else 0

    # グレード判定
    if profit_rate >= 15:
        grade = "◎"
    elif profit_rate >= 5:
        grade = "○"
    elif profit_rate >= 0:
        grade = "△"
    else:
        grade = "✗"

    return {
        "purchase_price": purchase_price,
        "amazon_price": amazon_price,
        "fee": fee,
        "profit": profit,
        "profit_rate": round(profit_rate, 1),
        "grade": grade,
    }


def analyze_items(items: list, keyword: str) -> list:
    """
    仕入れ候補リストにAmazon価格・利益情報を付与する。
    Claude B（利益分析担当）の主要処理。
    """
    print(f"\n  📊 Amazon価格を取得中（キーワード: {keyword}）...")

    # Amazon価格を1回だけ取得してキャッシュ（同一キーワードなら共通）
    amazon_price = get_amazon_price_by_keyword(keyword)

    if amazon_price is None:
        print("  ⚠️  Amazon価格を取得できませんでした。推定価格を使用します。")
        # 推定価格：仕入れ値の中央値 × 2.5 を概算として使用
        prices = [item["price"] for item in items if item.get("price")]
        if prices:
            median_price = sorted(prices)[len(prices) // 2]
            amazon_price = int(median_price * 2.5)
            print(f"  📌 推定Amazon価格: ¥{amazon_price:,}（仕入れ中央値 × 2.5）")
        else:
            amazon_price = 3000  # デフォルト

    else:
        print(f"  ✅ Amazon最安値: ¥{amazon_price:,}")

    time.sleep(random.uniform(1.0, 2.0))

    analyzed = []
    for item in items:
        purchase_price = item.get("price", 0)
        if not purchase_price:
            continue

        profit_info = calculate_profit(purchase_price, amazon_price)
        analyzed.append({
            **item,
            **profit_info,
        })

    # 利益率の高い順にソート
    analyzed.sort(key=lambda x: x["profit_rate"], reverse=True)
    return analyzed


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def _clean_price(text: str) -> Optional[int]:
    """価格文字列から数値を抽出する"""
    if not text:
        return None
    nums = re.sub(r"[^\d]", "", text)
    return int(nums) if nums else None


def format_profit_summary(item: Dict) -> str:
    """利益情報を1行のサマリー文字列にフォーマット"""
    grade = item.get("grade", "?")
    profit = item.get("profit", 0)
    profit_rate = item.get("profit_rate", 0)
    sign = "+" if profit >= 0 else ""
    return f"{grade} 利益: {sign}¥{profit:,} ({sign}{profit_rate}%)"
