"""
profit_calculator.py - 利益計算モジュール

Amazon FBA手数料を考慮した利益計算と、
複数商品の最安値仕入れ先を特定するロジック。
"""

# Amazon FBA手数料率（カテゴリ別）
FBA_FEE_RATE = {
    "game":        0.10,  # テレビゲーム: 10%
    "electronics": 0.08,  # 家電: 8%
    "toys":        0.10,  # おもちゃ: 10%
    "books":       0.15,  # 本・コミック: 15%
    "other":       0.10,  # その他: 10%
}

# FBA送料（配送・保管手数料の目安）
FBA_SHIPPING_FEE = 300  # 円

# 利益率しきい値
GRADE_EXCELLENT_THRESHOLD = 15.0  # ◎: 15%以上
GRADE_OK_THRESHOLD        =  5.0  # ○: 5%以上


def calculate_profit(amazon_price, buy_price, category="other"):
    """
    Amazon FBA販売時の利益を計算する。

    Parameters
    ----------
    amazon_price : int or float
        Amazonでの販売価格（円）
    buy_price : int or float
        仕入れ価格（円）
    category : str
        カテゴリ（"game", "electronics", "toys", "books", "other"）

    Returns
    -------
    dict
        {profit, profit_rate, fee}
        - profit      : 利益額（円）
        - profit_rate : 利益率（%）
        - fee         : 手数料合計（円）
    """
    try:
        amazon_price = float(amazon_price)
        buy_price    = float(buy_price)

        if amazon_price <= 0 or buy_price <= 0:
            return {"profit": 0, "profit_rate": 0.0, "fee": 0}

        # FBA手数料（販売手数料 + 配送手数料）
        fee_rate = FBA_FEE_RATE.get(category, FBA_FEE_RATE["other"])
        sales_fee = amazon_price * fee_rate
        fee = int(sales_fee + FBA_SHIPPING_FEE)

        # 利益 = 販売価格 - 仕入れ価格 - 手数料
        profit = int(amazon_price - buy_price - fee)

        # 利益率 = 利益 / 販売価格 × 100
        profit_rate = round((profit / amazon_price) * 100, 1) if amazon_price > 0 else 0.0

        return {
            "profit":      profit,
            "profit_rate": profit_rate,
            "fee":         fee,
        }

    except Exception as e:
        print(f"[利益計算] エラー: {e}")
        return {"profit": 0, "profit_rate": 0.0, "fee": 0}


def get_grade(profit_rate):
    """
    利益率からグレードを判定する。

    Returns
    -------
    str
        "◎" (15%以上), "○" (5%以上), "✗" (マイナスまたは5%未満)
    """
    if profit_rate >= GRADE_EXCELLENT_THRESHOLD:
        return "◎"
    elif profit_rate >= GRADE_OK_THRESHOLD:
        return "○"
    else:
        return "✗"


def find_best_deals(premium_products, rakuten_results_map, yahoo_results_map, category="other"):
    """
    プレミアム商品リストに対して最安値仕入れ先を特定し、利益計算を行う。

    Parameters
    ----------
    premium_products : list of dict
        keepa_client.find_premium_products() の返り値
    rakuten_results_map : dict
        {asin: [{name, price, url, shop}, ...]} 楽天の検索結果
    yahoo_results_map : dict
        {asin: [{name, price, url, shop}, ...]} Yahoo!の検索結果
    category : str
        カテゴリ

    Returns
    -------
    list of dict
        利益計算済みの商品リスト（利益率降順）
    """
    deals = []

    for product in premium_products:
        try:
            asin          = product.get("asin", "")
            title         = product.get("title", "不明商品")
            amazon_price  = product.get("current_price", 0)
            list_price    = product.get("list_price", 0)
            price_diff    = product.get("price_diff", 0)
            price_diff_rate = product.get("price_diff_rate", 0)

            if not amazon_price:
                continue

            # 楽天・Yahooの結果を統合して最安値を探す
            rakuten_items = rakuten_results_map.get(asin, [])
            yahoo_items   = yahoo_results_map.get(asin, [])

            best_source = None
            best_price  = None

            # 楽天の最安値（すでに安い順ソート済み）
            if rakuten_items:
                r_item = rakuten_items[0]
                r_price = r_item.get("price", 0)
                if r_price > 0:
                    if best_price is None or r_price < best_price:
                        best_price  = r_price
                        best_source = {**r_item, "source": "楽天市場"}

            # Yahooの最安値
            if yahoo_items:
                y_item = yahoo_items[0]
                y_price = y_item.get("price", 0)
                if y_price > 0:
                    if best_price is None or y_price < best_price:
                        best_price  = y_price
                        best_source = {**y_item, "source": "Yahoo!ショッピング"}

            if not best_source or not best_price:
                # 仕入れ先が見つからなかった商品も含める（仕入れ先なしで記録）
                deals.append({
                    "asin":           asin,
                    "title":          title,
                    "amazon_price":   amazon_price,
                    "list_price":     list_price,
                    "price_diff":     price_diff,
                    "price_diff_rate": price_diff_rate,
                    "buy_price":      None,
                    "buy_source":     None,
                    "buy_url":        None,
                    "buy_shop":       None,
                    "profit":         None,
                    "profit_rate":    None,
                    "fee":            None,
                    "grade":          "?",
                })
                continue

            # 利益計算
            calc = calculate_profit(amazon_price, best_price, category)

            deals.append({
                "asin":            asin,
                "title":           title,
                "amazon_price":    amazon_price,
                "list_price":      list_price,
                "price_diff":      price_diff,
                "price_diff_rate": price_diff_rate,
                "buy_price":       best_price,
                "buy_source":      best_source.get("source", ""),
                "buy_url":         best_source.get("url", ""),
                "buy_shop":        best_source.get("shop", ""),
                "profit":          calc["profit"],
                "profit_rate":     calc["profit_rate"],
                "fee":             calc["fee"],
                "grade":           get_grade(calc["profit_rate"]),
            })

        except Exception as e:
            print(f"[利益計算] 商品処理エラー (ASIN={product.get('asin')}): {e}")
            continue

    # 利益率降順でソート（Noneは末尾）
    deals.sort(
        key=lambda x: x.get("profit_rate") if x.get("profit_rate") is not None else -9999,
        reverse=True,
    )

    return deals
