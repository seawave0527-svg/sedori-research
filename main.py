"""
main.py - せどりリサーチツール メインスクリプト

設計思想:
  Claude A（仕入れリサーチ担当） → scraper.py
  Claude B（利益分析担当）       → amazon.py
  本ファイルは両者を統括するオーケストレーター

使い方:
  python main.py
  python main.py --keyword "Nintendo Switch"
  python main.py --keyword "ゲームボーイ" --limit 5 --asin B08H75RTZ8
"""

import argparse
import sys
import os
import json
from datetime import datetime
from typing import List, Dict

from scraper import search_all_sites
from amazon import analyze_items, get_amazon_price_by_asin


# ---------------------------------------------------------------------------
# ターミナル出力用カラー（ANSI）
# ---------------------------------------------------------------------------

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    GRAY   = "\033[90m"
    BLUE   = "\033[94m"

def color_grade(grade: str) -> str:
    if grade == "◎":
        return f"{C.GREEN}{C.BOLD}{grade}{C.RESET}"
    elif grade == "○":
        return f"{C.YELLOW}{grade}{C.RESET}"
    elif grade == "△":
        return f"{C.GRAY}{grade}{C.RESET}"
    else:
        return f"{C.RED}{grade}{C.RESET}"


# ---------------------------------------------------------------------------
# 表示関数
# ---------------------------------------------------------------------------

SEPARATOR = "─" * 80

def print_header(keyword: str):
    print()
    print(f"{C.BOLD}{C.CYAN}{'═' * 80}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  せどりリサーチツール  ／  キーワード: 「{keyword}」{C.RESET}")
    print(f"{C.CYAN}  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 80}{C.RESET}")


def print_phase(title: str):
    print(f"\n{C.BOLD}{C.BLUE}▶ {title}{C.RESET}")
    print(SEPARATOR)


def print_results_table(items: List[Dict]):
    """利益計算済みアイテムを表形式で表示"""
    if not items:
        print(f"  {C.GRAY}該当商品が見つかりませんでした。{C.RESET}")
        return

    # ヘッダー行
    print(
        f"  {'評価':<4} "
        f"{'仕入れサイト':<18} "
        f"{'商品名':<38} "
        f"{'仕入値':>8} "
        f"{'Amazon':>8} "
        f"{'手数料':>7} "
        f"{'利益':>8} "
        f"{'利益率':>7}"
    )
    print("  " + SEPARATOR)

    for i, item in enumerate(items, 1):
        grade        = item.get("grade", "?")
        site         = item.get("site", "不明")
        name         = item.get("name", "不明商品")
        purchase     = item.get("purchase_price", 0)
        amazon_price = item.get("amazon_price", 0)
        fee          = item.get("fee", 0)
        profit       = item.get("profit", 0)
        profit_rate  = item.get("profit_rate", 0)
        is_mock      = item.get("is_mock", False)

        # 名前を35文字に省略
        name_disp = (name[:34] + "…") if len(name) > 35 else name

        # 利益の色付け
        profit_str = f"{'+'if profit>=0 else ''}¥{profit:,}"
        if profit >= 0:
            profit_col = C.GREEN if profit_rate >= 15 else C.YELLOW
        else:
            profit_col = C.RED

        # モックデータには印をつける
        mock_mark = f"{C.GRAY}*{C.RESET}" if is_mock else " "

        print(
            f"  {color_grade(grade):<4} "
            f"{site:<18} "
            f"{name_disp:<38} "
            f"¥{purchase:>7,} "
            f"¥{amazon_price:>7,} "
            f"¥{fee:>6,} "
            f"{profit_col}{profit_str:>9}{C.RESET} "
            f"{profit_col}{profit_rate:>6.1f}%{C.RESET}"
            f"{mock_mark}"
        )

    print("  " + SEPARATOR)
    print(
        f"{C.GRAY}  * モックデータ（スクレイピング代替）を含む場合があります。{C.RESET}"
    )


def print_summary(items: List[Dict]):
    """集計サマリーを表示"""
    if not items:
        return

    total    = len(items)
    circle2  = sum(1 for i in items if i.get("grade") == "◎")
    circle1  = sum(1 for i in items if i.get("grade") == "○")
    triangle = sum(1 for i in items if i.get("grade") == "△")
    cross    = sum(1 for i in items if i.get("grade") == "✗")

    best = max(items, key=lambda x: x.get("profit_rate", -999))

    print(f"\n{C.BOLD}【集計サマリー】{C.RESET}")
    print(f"  総件数: {total}件  |  "
          f"{C.GREEN}◎ {circle2}件{C.RESET}  "
          f"{C.YELLOW}○ {circle1}件{C.RESET}  "
          f"{C.GRAY}△ {triangle}件{C.RESET}  "
          f"{C.RED}✗ {cross}件{C.RESET}")

    if best:
        print(f"\n  {C.BOLD}最高利益候補:{C.RESET}")
        print(f"    {color_grade(best['grade'])} "
              f"[{best['site']}] {best['name'][:40]}")
        print(f"    仕入: ¥{best['purchase_price']:,}  →  "
              f"Amazon: ¥{best['amazon_price']:,}  "
              f"利益: {C.GREEN}+¥{best['profit']:,} ({best['profit_rate']}%){C.RESET}")


def print_grade_legend():
    print(f"\n{C.GRAY}【評価基準】 "
          f"{C.GREEN}◎{C.RESET}{C.GRAY} 利益率15%以上  "
          f"{C.YELLOW}○{C.RESET}{C.GRAY} 5%以上  "
          f"△ 0%以上  "
          f"{C.RED}✗{C.RESET}{C.GRAY} 赤字{C.RESET}")
    print(f"{C.GRAY}【手数料計算】 Amazon販売手数料15% + FBA配送料概算¥300{C.RESET}\n")


# ---------------------------------------------------------------------------
# JSON出力
# ---------------------------------------------------------------------------

def save_results_json(items: List[Dict], keyword: str):
    """結果をJSONファイルに保存（オプション）"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"result_{timestamp}.json"
    filepath  = os.path.join(os.path.dirname(__file__), filename)
    data = {
        "keyword":    keyword,
        "timestamp":  timestamp,
        "total":      len(items),
        "items":      items,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  💾 結果を保存しました: {filepath}")


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def run_research(keyword: str, max_per_site: int = 3, asin: str = None, save_json: bool = False):
    """
    メインリサーチ処理。
    1. 全仕入れサイトを検索（Claude A担当）
    2. Amazon価格取得・利益計算（Claude B担当）
    3. 結果表示
    """
    print_header(keyword)

    # ── Phase 1: 仕入れサイト検索（Claude A）──────────────────────────
    print_phase("Phase 1 / 仕入れサイト検索（Claude A: リサーチ担当）")
    raw_items = search_all_sites(keyword, max_per_site=max_per_site)
    print(f"\n  合計 {len(raw_items)} 件の仕入れ候補を取得しました。")

    if not raw_items:
        print(f"{C.RED}  仕入れ候補が見つかりませんでした。キーワードを変えて試してください。{C.RESET}")
        return

    # ── Phase 2: Amazon価格取得・利益計算（Claude B）────────────────────
    print_phase("Phase 2 / Amazon価格取得・利益計算（Claude B: 分析担当）")

    # ASINが指定された場合はASINで直接取得
    amazon_override = None
    if asin:
        from amazon import get_amazon_price_by_asin
        print(f"  ASIN指定: {asin} で価格を取得中...")
        amazon_override = get_amazon_price_by_asin(asin)
        if amazon_override:
            print(f"  ✅ ASIN価格: ¥{amazon_override:,}")
            # 全アイテムにAmazon価格を上書き
            for item in raw_items:
                item["_amazon_override"] = amazon_override

    analyzed_items = analyze_items(raw_items, keyword)

    # ASIN上書きが指定されていた場合は再計算
    if amazon_override:
        from amazon import calculate_profit
        for item in analyzed_items:
            result = calculate_profit(item["purchase_price"], amazon_override)
            item.update(result)
        analyzed_items.sort(key=lambda x: x["profit_rate"], reverse=True)

    # ── Phase 3: 結果表示 ──────────────────────────────────────────────
    print_phase("Phase 3 / リサーチ結果")
    print_results_table(analyzed_items)
    print_summary(analyzed_items)
    print_grade_legend()

    # JSON保存（オプション）
    if save_json:
        save_results_json(analyzed_items, keyword)

    return analyzed_items


def interactive_mode():
    """対話モード（引数なし起動時）"""
    print(f"\n{C.BOLD}{C.CYAN}{'═' * 60}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  せどりリサーチツール  v1.0{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 60}{C.RESET}")
    print(f"  Claude A（仕入れリサーチ）× Claude B（利益分析）連携ツール\n")

    while True:
        print(f"{C.BOLD}検索キーワードを入力してください（終了: q）{C.RESET}")
        keyword = input("  > ").strip()

        if keyword.lower() in ("q", "quit", "exit", "終了"):
            print("\nツールを終了します。\n")
            break
        if not keyword:
            print(f"  {C.GRAY}キーワードを入力してください。{C.RESET}")
            continue

        print(f"\n{C.GRAY}オプション設定（Enterでスキップ）{C.RESET}")

        asin_input = input(f"  ASINコード（例: B08H75RTZ8）: ").strip() or None

        limit_input = input(f"  1サイトあたりの取得件数（デフォルト: 3）: ").strip()
        try:
            limit = int(limit_input) if limit_input else 3
            limit = max(1, min(limit, 10))
        except ValueError:
            limit = 3

        save_input = input(f"  JSONファイルに保存しますか？ [y/N]: ").strip().lower()
        save_json  = save_input in ("y", "yes")

        try:
            run_research(keyword, max_per_site=limit, asin=asin_input, save_json=save_json)
        except KeyboardInterrupt:
            print(f"\n  {C.YELLOW}処理を中断しました。{C.RESET}")
        except Exception as e:
            print(f"\n  {C.RED}予期しないエラー: {e}{C.RESET}")

        print()
        cont = input("続けて検索しますか？ [Y/n]: ").strip().lower()
        if cont in ("n", "no"):
            print("\nツールを終了します。\n")
            break
        print()


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="せどりリサーチツール - 仕入れ候補を自動検索して利益計算します"
    )
    parser.add_argument(
        "--keyword", "-k",
        type=str,
        default=None,
        help="検索キーワード（省略すると対話モード）",
    )
    parser.add_argument(
        "--asin", "-a",
        type=str,
        default=None,
        help="Amazon ASIN コード（指定するとASINで価格取得）",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=3,
        help="1サイトあたりの取得件数（デフォルト: 3）",
    )
    parser.add_argument(
        "--save", "-s",
        action="store_true",
        help="結果をJSONファイルに保存する",
    )

    args = parser.parse_args()

    if args.keyword:
        # コマンドライン引数モード
        try:
            run_research(
                keyword=args.keyword,
                max_per_site=args.limit,
                asin=args.asin,
                save_json=args.save,
            )
        except KeyboardInterrupt:
            print(f"\n{C.YELLOW}処理を中断しました。{C.RESET}\n")
            sys.exit(0)
    else:
        # 対話モード
        try:
            interactive_mode()
        except KeyboardInterrupt:
            print(f"\n\n{C.YELLOW}終了します。{C.RESET}\n")
            sys.exit(0)


if __name__ == "__main__":
    main()
