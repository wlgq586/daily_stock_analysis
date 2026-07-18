#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新股票自动补全索引文件

从 akshare 获取全量 A 股代码+名称，生成 stocks.index.json（含拼音、市场分类）。
无需 Tushare token，仅需 akshare。

输出路径：
  apps/dsa-web/public/stocks.index.json   （前端构建用）
  static/stocks.index.json                （后端运行时用）

用法：
  python scripts/update_stock_index.py              # 生成并写入
  python scripts/update_stock_index.py --test       # 仅测试，不写入
  python scripts/update_stock_index.py --test -v    # 测试 + 详细预览
"""

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

# 项目根目录
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from pypinyin import lazy_pinyin
    PYPINYIN_AVAILABLE = True
except ImportError:
    PYPINYIN_AVAILABLE = False
    print("[Warning] pypinyin not available, pinyin fields will be empty")
    print("[Info] Install with: pip install pypinyin")


# -------- 复用 generate_stock_index 的工具函数 --------

def determine_market_and_type(code: str) -> tuple:
    if code.isdigit():
        if len(code) == 5:
            if code.startswith('0') or code.startswith('2'):
                return 'HK', 'stock'
            return 'CN', 'stock'
        elif len(code) == 6:
            if code.startswith('6'):
                return 'CN', 'stock'
            elif code.startswith(('0', '2', '3')):
                return 'CN', 'stock'
            elif code.startswith('8'):
                return 'BSE', 'stock'
            return 'CN', 'stock'
        elif len(code) == 4:
            return 'US', 'stock'
    return 'US', 'stock'


def build_canonical_code(code: str, market: str) -> str:
    if market == 'CN' and code.isdigit() and len(code) == 6:
        if code.startswith(('6', '900')):
            return f"{code}.SH"
        if code.startswith(('0', '2', '3')):
            return f"{code}.SZ"
        if code.startswith(('920', '43', '83', '87', '88', '81', '82')):
            return f"{code}.BJ"
    if market == 'BSE' and code.isdigit() and len(code) == 6:
        return f"{code}.BJ"
    suffix_map = {'CN': 'SH', 'HK': 'HK', 'US': 'US', 'BSE': 'BJ'}
    return f"{code}.{suffix_map.get(market, 'SH')}"


def normalize_name_for_pinyin(name: str) -> str:
    normalized = unicodedata.normalize('NFKC', name).strip()
    normalized = re.sub(r'^(?:\*?ST|N)+', '', normalized, flags=re.IGNORECASE)
    return normalized.strip() or unicodedata.normalize('NFKC', name).strip()


def generate_pinyin(name: str):
    if not PYPINYIN_AVAILABLE:
        return None, None
    try:
        normalized = normalize_name_for_pinyin(name)
        py = lazy_pinyin(normalized)
        return ''.join(py), ''.join(p[0] for p in py)
    except Exception:
        return None, None


# -------- 数据获取 --------

def get_akshare_stocks() -> List[Dict[str, str]]:
    """从 akshare 获取全量 A 股代码+名称"""
    import akshare as ak
    print("正在从 akshare 获取 A 股列表...")
    df = ak.stock_info_a_code_name()
    if df is None or df.empty:
        print("[Error] akshare 返回空列表")
        return []

    stocks = []
    skipped_etf = 0
    for _, row in df.iterrows():
        raw_code = str(row.get("code", "")).strip()
        name = str(row.get("name", "")).strip()
        if not raw_code or not name:
            continue
        # 标准化代码
        code = raw_code
        if "." in code:
            code = code.rsplit(".", 1)[0]

        # 跳过 ETF（51/52/56/58/15/16/18 开头）
        if len(code) == 6 and code.isdigit():
            if code[:2] in ("51", "52", "56", "58", "15", "16", "18"):
                skipped_etf += 1
                continue

        stocks.append({"code": code, "name": name})

    print(f"A 股列表: {len(stocks)} 只（跳过 ETF {skipped_etf}）")
    return stocks


def get_manual_stocks() -> List[Dict[str, str]]:
    """手动维护的港股/美股等，来自 STOCK_NAME_MAP"""
    from src.data.stock_mapping import STOCK_NAME_MAP
    a_stocks = get_akshare_stocks()
    a_codes = {s["code"] for s in a_stocks}

    manual = []
    for code, name in STOCK_NAME_MAP.items():
        if code in a_codes:
            continue  # 已在 akshare 列表中
        manual.append({"code": code, "name": name})
    return manual


# -------- 索引生成 --------

def build_index(stocks: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    index = []
    for s in stocks:
        code = s["code"]
        name = s["name"]
        market, asset_type = determine_market_and_type(code)
        pinyin_full, pinyin_abbr = generate_pinyin(name)

        index.append({
            "canonicalCode": build_canonical_code(code, market),
            "displayCode": code,
            "nameZh": name,
            "pinyinFull": pinyin_full,
            "pinyinAbbr": pinyin_abbr,
            "aliases": [],
            "market": market,
            "assetType": asset_type,
            "active": True,
            "popularity": 100,
        })
    return index


def compress_index(index: List[Dict[str, Any]]) -> List[List]:
    compressed = []
    for item in index:
        compressed.append([
            item["canonicalCode"],
            item["displayCode"],
            item["nameZh"],
            item.get("pinyinFull"),
            item.get("pinyinAbbr"),
            item.get("aliases", []),
            item["market"],
            item["assetType"],
            item["active"],
            item.get("popularity", 0),
        ])
    return compressed


def write_index(compressed: List[List], output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('[\n')
        for i, item in enumerate(compressed):
            json.dump(item, f, ensure_ascii=False, separators=(',', ':'))
            if i < len(compressed) - 1:
                f.write(',\n')
            else:
                f.write('\n')
        f.write(']\n')
    return output_path.stat().st_size


# -------- 主流程 --------

def main():
    parser = argparse.ArgumentParser(description="更新股票自动补全索引（基于 akshare）")
    parser.add_argument('--test', '-t', action='store_true', help='测试模式，不写入文件')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示前 10 条预览')
    args = parser.parse_args()

    print("=" * 60)
    print("股票索引更新工具（akshare）")
    print("=" * 60)

    # 1. 获取 A 股完整列表
    a_stocks = get_akshare_stocks()
    if not a_stocks:
        print("[Error] 无法获取 A 股列表，退出")
        return 1

    # 2. 获取手动维护的港股/美股
    manual = get_manual_stocks()
    print(f"手动补充（港股/美股等）: {len(manual)} 只")

    # 3. 合并并去重（按 code）
    all_stocks = a_stocks + manual
    seen = set()
    unique = []
    for s in all_stocks:
        if s["code"] not in seen:
            seen.add(s["code"])
            unique.append(s)

    print(f"合并去重后: {len(unique)} 只")

    # 4. 生成索引
    index = build_index(unique)

    # 5. 统计
    market_stats = {}
    for item in index:
        m = item['market']
        market_stats[m] = market_stats.get(m, 0) + 1
    print(f"市场分布: {market_stats}")

    # 6. 压缩
    compressed = compress_index(index)
    size_kb = len(json.dumps(compressed, ensure_ascii=False, separators=(',', ':'))) / 1024
    print(f"预计大小: {size_kb:.1f} KB")

    if args.test:
        print("\n[测试模式] 不会写入文件")
        if args.verbose:
            print("\n前 10 条预览:")
            for i, item in enumerate(index[:10]):
                print(f"  {i+1}. {item['canonicalCode']} - {item['nameZh']} ({item['market']})")
        print("\n✓ 测试通过")
        return 0

    # 7. 写入文件
    web_path = REPO_ROOT / "apps" / "dsa-web" / "public" / "stocks.index.json"
    static_path = REPO_ROOT / "static" / "stocks.index.json"

    file_size = write_index(compressed, web_path)
    print(f"已写入: {web_path} ({file_size / 1024:.1f} KB)")

    # 同步到 static/
    static_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(web_path, static_path)
    print(f"已同步: {static_path}")

    # 8. 验证
    with open(web_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(f"验证通过: {len(data)} 条记录")

    print("\n✓ 索引更新完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
