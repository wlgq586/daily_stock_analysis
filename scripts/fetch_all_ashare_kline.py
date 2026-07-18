#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量抓取所有A股历史K线数据（2016年1月至今）

使用 DataFetcherManager 多数据源自动 fallback：
  Efinance → Tencent → Akshare → Pytdx → Baostock → Yfinance
一个被封自动切换下一个，无需手动干预。

支持断点续传：已存在于数据库中的股票会被跳过。

使用方法：
    python scripts/fetch_all_ashare_kline.py
    python scripts/fetch_all_ashare_kline.py --start-index 0       # 从指定索引开始
    python scripts/fetch_all_ashare_kline.py --codes 600519,000001  # 只抓取指定代码
    python scripts/fetch_all_ashare_kline.py --sleep-min 2.0 --sleep-max 5.0  # 自定义休眠
    python scripts/fetch_all_ashare_kline.py --skip-existing-check  # 强制重新抓取所有

环境要求：
    - 需要安装 efinance: pip install efinance
    - 需要安装 akshare: pip install akshare
    - 需要安装 baostock: pip install baostock
    - 可选安装 tqdm: pip install tqdm (进度条)

数据量估算：
    - ~5500 只 A 股 × ~2500 个交易日（2016-至今）≈ 最大 ~13.7M 条
    - 每只股票约 2-8 秒（含休眠），全量约需 5-12 小时
"""

import argparse
import logging
import os
import random
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

# 初始化项目配置（必须，DataFetcherManager 依赖）
from src.config import setup_env, get_config
setup_env()
_config = get_config()

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
LOG_FILE = Path(__file__).parent.parent / "logs" / "fetch_all_ashare_kline.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("fetch_kline")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DEFAULT_START_DATE = "2016-01-01"
DEFAULT_SLEEP_MIN = 0.5
DEFAULT_SLEEP_MAX = 1.5
PROGRESS_FILE = Path(__file__).parent.parent / "data" / ".fetch_kline_progress.txt"

# ETF 代码前缀（上交所 / 深交所）
ETF_SH_PREFIXES = ("51", "52", "56", "58")
ETF_SZ_PREFIXES = ("15", "16", "18")

# BSE（北交所）代码前缀
BSE_PREFIXES = ("8", "9")  # 8xxxxx / 9xxxxx


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _is_bse_code(code: str) -> bool:
    """判断是否为北交所代码（8xxxxx / 9xxxxx，六位纯数字）"""
    code = code.strip()
    return len(code) == 6 and code.isdigit() and code.startswith(BSE_PREFIXES)


def _is_etf_code(code: str) -> bool:
    """判断是否为 ETF 基金代码"""
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        return False
    return code.startswith(ETF_SH_PREFIXES) or code.startswith(ETF_SZ_PREFIXES)


def normalize_stock_code(code: str) -> str:
    """标准化股票代码（去除 .SH/.SZ 后缀）"""
    code = str(code).strip()
    if "." in code:
        code = code.rsplit(".", 1)[0]
    return code


# ---------------------------------------------------------------------------
# 股票列表获取
# ---------------------------------------------------------------------------


def get_all_a_share_codes() -> List[Dict[str, str]]:
    """
    获取所有 A 股代码列表

    使用 akshare 的 stock_info_a_code_name() 接口。

    Returns:
        [{"code": "600519", "name": "贵州茅台"}, ...]
    """
    import akshare as ak

    logger.info("正在从 akshare 获取 A 股列表...")
    df = ak.stock_info_a_code_name()

    if df is None or df.empty:
        logger.error("akshare 返回空的股票列表")
        return []

    codes = []
    etf_count = 0
    bse_count = 0

    for _, row in df.iterrows():
        raw_code = str(row.get("code", "")).strip()
        name = str(row.get("name", "")).strip()
        if not raw_code:
            continue

        code = normalize_stock_code(raw_code)

        # 跳过 ETF
        if _is_etf_code(code):
            etf_count += 1
            continue

        # 跳过北交所（efinance 可能不支持）
        if _is_bse_code(code):
            bse_count += 1
            continue

        codes.append({"code": code, "name": name})

    logger.info(f"A 股列表获取完成: 共 {len(codes)} 只（跳过 ETF {etf_count}、北交所 {bse_count}）")
    return codes


# ---------------------------------------------------------------------------
# 进度管理
# ---------------------------------------------------------------------------


def load_progress() -> set:
    """加载已完成的股票代码集合"""
    if not PROGRESS_FILE.exists():
        return set()
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_progress(code: str):
    """追加一条完成记录"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{code}\n")


# ---------------------------------------------------------------------------
# 数据库检查
# ---------------------------------------------------------------------------


def get_existing_codes_in_db() -> set:
    """查询数据库中已有数据的股票代码集合"""
    from src.storage import DatabaseManager, StockDaily
    from sqlalchemy import select, func

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        result = session.execute(
            select(func.distinct(StockDaily.code))
        ).scalars().all()
    return set(result)


# ---------------------------------------------------------------------------
# 残缺数据检测
# ---------------------------------------------------------------------------


def get_incomplete_codes(min_records: int = 500) -> list:
    """
    查询数据库中记录数不足的股票代码列表（含日期范围）

    一只 2016 年以前上市的正常 A 股应该有 ~2500 条日线数据。
    小于 min_records 的可能是抓取被截断，也可能是新股/退市股。

    Returns:
        [(code, record_count, min_date, max_date), ...] 按记录数升序排列
    """
    from src.storage import DatabaseManager, StockDaily
    from sqlalchemy import select, func

    db = DatabaseManager.get_instance()
    with db.get_session() as session:
        rows = session.execute(
            select(
                StockDaily.code,
                func.count(StockDaily.id).label("cnt"),
                func.min(StockDaily.date).label("min_date"),
                func.max(StockDaily.date).label("max_date"),
            )
            .group_by(StockDaily.code)
            .having(func.count(StockDaily.id) < min_records)
            .order_by(func.count(StockDaily.id))
        ).all()
    return [(row.code, row.cnt, row.min_date, row.max_date) for row in rows]


def _classify_incomplete(min_date, max_date, cnt: int, today=None):
    """
    根据日期范围分类残缺数据的原因

    Returns:
        'new_ipo'  — 新股/次新股（上市不足 2 年），记录少属正常
        'delisted' — 可能退市（最新数据距今超过 1 年）
        'broken'   — 疑似残缺（老股票但记录远低于预期）
    """
    from datetime import date, timedelta
    if today is None:
        today = date.today()
    two_years_ago = today - timedelta(days=730)
    one_year_ago = today - timedelta(days=365)

    if min_date and min_date >= two_years_ago:
        return 'new_ipo'
    if max_date and max_date < one_year_ago:
        return 'delisted'
    return 'broken'


def remove_from_progress(codes: list):
    """从进度文件中移除指定股票代码，使其可被重新抓取"""
    if not PROGRESS_FILE.exists():
        return
    existing = load_progress()
    to_remove = set(codes)
    kept = existing - to_remove
    if len(kept) == len(existing):
        return  # 无需修改
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        for c in sorted(kept):
            f.write(f"{c}\n")
    logger.info(f"进度文件: 移除了 {len(existing) - len(kept)} 条记录")


# ---------------------------------------------------------------------------
# K 线抓取
# ---------------------------------------------------------------------------


class KLineFetcher:
    """A 股 K 线数据批量抓取器（多数据源自动 fallback）"""

    def __init__(self, sleep_min: float = DEFAULT_SLEEP_MIN, sleep_max: float = DEFAULT_SLEEP_MAX):
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._last_request_time: Optional[float] = None
        self._consecutive_errors = 0
        self._manager = None  # DataFetcherManager（延迟初始化）
        # 统计每个数据源的使用次数
        self.source_stats: Dict[str, int] = defaultdict(int)
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "empty": 0,
        }

    def _get_manager(self):
        """延迟初始化 DataFetcherManager（避免导入时依赖问题）"""
        if self._manager is None:
            from data_provider.base import DataFetcherManager
            self._manager = DataFetcherManager()
        return self._manager

    def _random_sleep(self):
        """随机休眠，防止被限流。连续失败时自动增加休眠时间。"""
        if self._last_request_time is not None:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.sleep_min:
                time.sleep(self.sleep_min - elapsed)

        # 自适应退避：连续失败越多，额外休眠越长
        extra_sleep = 0
        if self._consecutive_errors >= 10:
            extra_sleep = random.uniform(5, 15)
        elif self._consecutive_errors >= 5:
            extra_sleep = random.uniform(2, 5)
        elif self._consecutive_errors >= 3:
            extra_sleep = random.uniform(1, 2)

        time.sleep(random.uniform(0, self.sleep_max - self.sleep_min) + extra_sleep)
        self._last_request_time = time.time()

    def fetch_stock_kline(
        self, stock_code: str, start_date: str, end_date: str
    ) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        获取单只股票的日线 K 线数据（多数据源自动 fallback）

        使用 DataFetcherManager 依次尝试：
          Efinance → Tencent → Akshare → Pytdx → Baostock → Yfinance
        任一成功即返回，全部失败返回 None。

        Args:
            stock_code: 股票代码
            start_date: 开始日期，格式 YYYY-MM-DD
            end_date: 结束日期，格式 YYYY-MM-DD

        Returns:
            (DataFrame, source_name) — 已含标准化列 + 技术指标（ma5/10/20/volume_ratio）
            失败返回 (None, None)
        """
        manager = self._get_manager()
        self._random_sleep()

        api_start = time.time()
        try:
            df, source_name = manager.get_daily_data(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                days=365 * 10,  # 大值确保覆盖全部日期范围
            )

            api_elapsed = time.time() - api_start

            if df is None or df.empty:
                self._consecutive_errors += 1
                logger.debug(
                    f"[空数据] {stock_code} 所有数据源均无返回, "
                    f"elapsed={api_elapsed:.2f}s"
                )
                return None, None

            # 成功，重置连续失败计数
            self._consecutive_errors = 0
            self.source_stats[source_name] += 1

            logger.debug(
                f"[OK] {stock_code}: rows={len(df)}, "
                f"source={source_name}, elapsed={api_elapsed:.2f}s"
            )
            return df, source_name

        except Exception as e:
            api_elapsed = time.time() - api_start
            error_msg = str(e).strip().lower()
            # DataFetcherManager 在所有数据源失败时抛出 DataFetchError
            # 这些是可预期的（退市股票、空响应、接口异常）
            if any(kw in error_msg for kw in (
                "nodata", "no data", "empty", "none",
                "expecting value", "jsondecodeerror",
                "extra data", "invalid", "timeout",
                "获取失败",
            )):
                self._consecutive_errors += 1
                logger.debug(f"[无数据] {stock_code}: {error_msg[:120]}")
                return None, None
            self._consecutive_errors += 1
            logger.warning(
                f"[失败] {stock_code}: {error_msg[:120]}, "
                f"elapsed={api_elapsed:.2f}s"
            )
            return None, None

    def save_to_db(self, df: pd.DataFrame, stock_code: str, source_name: str = "Unknown") -> int:
        """保存标准化数据到数据库，返回新增条数"""
        from src.storage import DatabaseManager

        db = DatabaseManager.get_instance()
        return db.save_daily_data(df, stock_code, data_source=source_name)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def parse_args():
    parser = argparse.ArgumentParser(
        description="批量抓取所有 A 股 K 线数据（2016 年 1 月至今）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="从股票列表的第几个索引开始（用于断点续传）",
    )
    parser.add_argument(
        "--end-index",
        type=int,
        default=None,
        help="股票列表的结束索引（不含）",
    )
    parser.add_argument(
        "--codes",
        type=str,
        default=None,
        help="逗号分隔的股票代码列表，如 '600519,000001,300750'",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=DEFAULT_START_DATE,
        help=f"开始日期，格式 YYYY-MM-DD（默认 {DEFAULT_START_DATE}）",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="结束日期，格式 YYYY-MM-DD（默认今天）",
    )
    parser.add_argument(
        "--sleep-min",
        type=float,
        default=DEFAULT_SLEEP_MIN,
        help=f"最小休眠时间（秒，默认 {DEFAULT_SLEEP_MIN}）",
    )
    parser.add_argument(
        "--sleep-max",
        type=float,
        default=DEFAULT_SLEEP_MAX,
        help=f"最大休眠时间（秒，默认 {DEFAULT_SLEEP_MAX}）",
    )
    parser.add_argument(
        "--skip-existing-check",
        action="store_true",
        help="跳过数据库已有数据检查，强制重新抓取所有股票",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列出将要抓取的股票，不实际抓取",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检测并列出数据库中记录数不足的股票（不抓取）",
    )
    parser.add_argument(
        "--incomplete-threshold",
        type=int,
        default=500,
        help="判定数据不完整的记录数阈值（默认 500 条，正常应有 ~2500 条）",
    )
    parser.add_argument(
        "--recheck-incomplete",
        action="store_true",
        help="自动检测残缺数据并从进度文件中移除，然后重抓",
    )
    parser.add_argument(
        "--update-recent",
        type=int,
        default=None,
        const=5,
        nargs="?",
        metavar="DAYS",
        help="增量更新：仅拉取 DB 中已有股票最近 N 天的数据（默认 5 天）。适合每日定时任务",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 确定结束日期
    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("A 股 K 线批量抓取工具（多数据源自动 fallback）")
    logger.info(f"  Fallback 链: Efinance → Tencent → Akshare → Pytdx → Baostock → Yfinance")
    logger.info(f"  日期范围: {args.start_date} ~ {end_date}")
    logger.info(f"  休眠范围: {args.sleep_min:.1f}s ~ {args.sleep_max:.1f}s")
    logger.info(f"  进度文件: {PROGRESS_FILE}")
    logger.info(f"  日志文件: {LOG_FILE}")
    logger.info("=" * 60)

    # ---- check-only 模式：仅检测残缺数据 ----
    if args.check_only:
        incomplete = get_incomplete_codes(min_records=args.incomplete_threshold)
        if not incomplete:
            logger.info(f"没有记录数 < {args.incomplete_threshold} 的股票，数据完好！")
        else:
            # 分类
            new_ipos = []
            broken = []
            delisted = []
            for code, cnt, min_d, max_d in incomplete:
                cat = _classify_incomplete(min_d, max_d, cnt)
                entry = (code, cnt, str(min_d) if min_d else "?", str(max_d) if max_d else "?")
                if cat == 'new_ipo':
                    new_ipos.append(entry)
                elif cat == 'delisted':
                    delisted.append(entry)
                else:
                    broken.append(entry)

            total = len(incomplete)
            logger.info(
                f"记录数 < {args.incomplete_threshold} 的股票共 {total} 只："
                f"新股 {len(new_ipos)}、疑似残缺 {len(broken)}、可能退市 {len(delisted)}"
            )

            if broken:
                logger.info(f"\n--- 疑似残缺（{len(broken)} 只，建议 --recheck-incomplete）---")
                for code, cnt, min_d, max_d in broken:
                    logger.info(f"  {code}: {cnt} 条, {min_d} ~ {max_d}")

            if new_ipos:
                logger.info(f"\n--- 新股/次新股（{len(new_ipos)} 只，上市不足 2 年，正常）---")
                for code, cnt, min_d, max_d in new_ipos:
                    logger.info(f"  {code}: {cnt} 条, {min_d} ~ {max_d}")

            if delisted:
                logger.info(f"\n--- 可能退市（{len(delisted)} 只，最新数据超过 1 年）---")
                for code, cnt, min_d, max_d in delisted:
                    logger.info(f"  {code}: {cnt} 条, {min_d} ~ {max_d}")
        return

    # ---- recheck-incomplete 模式：自动检测残缺并重抓 ----
    if args.recheck_incomplete:
        incomplete = get_incomplete_codes(min_records=args.incomplete_threshold)
        if not incomplete:
            logger.info(f"没有记录数 < {args.incomplete_threshold} 的股票，无需重抓！")
            return
        # 只重抓「疑似残缺」的（跳过新股和可能退市的）
        broken_codes = []
        skipped_new = 0
        skipped_delisted = 0
        for code, cnt, min_d, max_d in incomplete:
            cat = _classify_incomplete(min_d, max_d, cnt)
            if cat == 'new_ipo':
                skipped_new += 1
            elif cat == 'delisted':
                skipped_delisted += 1
            else:
                broken_codes.append(code)

        logger.info(
            f"检测到 {len(incomplete)} 只记录数 < {args.incomplete_threshold} 的股票："
            f"疑似残缺 {len(broken_codes)}（将重抓）、"
            f"新股跳过 {skipped_new}、退市跳过 {skipped_delisted}"
        )
        if not broken_codes:
            logger.info("没有需要重抓的股票（剩余的都是新股或退市股），退出")
            return
        # 从进度文件中移除，避免被跳过
        remove_from_progress(broken_codes)
        # 强制跳过 DB 存量检查（因为 DB 里有残缺数据）
        args.skip_existing_check = True

    # ---- update-recent 模式：增量更新已有股票的最近数据 ----
    if args.update_recent is not None:
        update_days = args.update_recent
        # 计算起始日期：日历日 * 2 确保覆盖足够的交易日
        from datetime import timedelta
        update_start = (
            datetime.now() - timedelta(days=update_days * 2)
        ).strftime("%Y-%m-%d")
        logger.info("=" * 60)
        logger.info(f"增量更新模式: 最近 {update_days} 个交易日")
        logger.info(f"  日期范围: {update_start} ~ {end_date}")
        logger.info("=" * 60)

        # 仅获取 DB 中已有数据的股票
        db_codes = get_existing_codes_in_db()
        if not db_codes:
            logger.info("数据库中没有股票数据，请先运行完整抓取")
            return
        logger.info(f"数据库中已有 {len(db_codes)} 只股票，将逐一增量更新")

        # 覆盖日期参数
        args.start_date = update_start
        # 仅抓取 DB 已有的股票
        codes = [{"code": c, "name": c} for c in sorted(db_codes)]
        # 跳过进度文件和 DB 检查
        args.skip_existing_check = True
        # 不清除进度文件（增量更新不应影响完整抓取的断点续传）
        completed_codes = set()
        existing_db_codes = set()

    # 获取股票列表（update-recent 模式已在上面设置好 codes）
    if args.update_recent is not None:
        pass  # codes 已在上方 update-recent 块中设置
    elif args.codes:
        codes = [
            {"code": normalize_stock_code(c.strip()), "name": c.strip()}
            for c in args.codes.split(",")
            if c.strip()
        ]
        logger.info(f"使用指定的 {len(codes)} 只股票")
    else:
        codes = get_all_a_share_codes()
        if not codes:
            logger.error("未能获取股票列表，退出")
            sys.exit(1)

    # 应用索引范围
    total_codes = len(codes)
    end_idx = args.end_index or total_codes
    codes = codes[args.start_index : end_idx]
    logger.info(f"有效抓取范围: 索引 {args.start_index} ~ {args.start_index + len(codes) - 1}")

    # 加载已完成进度（update-recent 模式不依赖进度文件）
    if args.update_recent is not None:
        pass  # completed_codes 已在上方设为 set()
    else:
        completed_codes = load_progress()
    logger.info(f"进度文件中已完成: {len(completed_codes)} 只")

    # 查询数据库中已有数据的代码
    if args.update_recent is not None:
        pass  # existing_db_codes 已在上方设为 set()
    elif not args.skip_existing_check:
        try:
            existing_db_codes = get_existing_codes_in_db()
            logger.info(f"数据库中已有数据: {len(existing_db_codes)} 只")
        except Exception as e:
            logger.warning(f"查询数据库已有代码失败: {e}，将尝试抓取所有股票")
            existing_db_codes = set()
    else:
        logger.info("跳过数据库已有数据检查")
        existing_db_codes = set()

    # 过滤需要抓取的股票
    to_fetch = []
    skipped_progress = 0
    skipped_db = 0
    for item in codes:
        code = item["code"]
        if code in completed_codes:
            skipped_progress += 1
            continue
        if not args.skip_existing_check and code in existing_db_codes:
            skipped_db += 1
            # 也记录到进度文件，避免下次重复检查 DB
            save_progress(code)
            continue
        to_fetch.append(item)

    logger.info(
        f"需要抓取: {len(to_fetch)} 只 "
        f"(进度跳过 {skipped_progress}、DB跳过 {skipped_db}、总计 {total_codes})"
    )

    if args.dry_run:
        logger.info("DRY RUN 模式，仅列出前 20 只:")
        for item in to_fetch[:20]:
            logger.info(f"  {item['code']} {item['name']}")
        if len(to_fetch) > 20:
            logger.info(f"  ... 还有 {len(to_fetch) - 20} 只")
        return

    if not to_fetch:
        logger.info("没有需要抓取的股票，退出")
        return

    # 开始抓取
    fetcher = KLineFetcher(sleep_min=args.sleep_min, sleep_max=args.sleep_max)
    fetcher.stats["total"] = len(to_fetch)

    # 尝试导入 tqdm
    try:
        from tqdm import tqdm
        iterator = tqdm(enumerate(to_fetch, 1), total=len(to_fetch), desc="抓取进度", unit="只")
    except ImportError:
        logger.info("提示: pip install tqdm 可获得进度条显示")
        iterator = enumerate(to_fetch, 1)

    start_time = time.time()

    for idx, item in iterator:
        code = item["code"]
        name = item["name"]

        try:
            df, source_name = fetcher.fetch_stock_kline(code, args.start_date, end_date)

            if df is None or df.empty:
                fetcher.stats["empty"] += 1
                # 空数据也记录进度，避免重复尝试
                save_progress(code)
                continue

            # 保存到数据库
            saved = fetcher.save_to_db(df, code, source_name=source_name or "Unknown")
            fetcher.stats["success"] += 1

            # 记录进度
            save_progress(code)

            if isinstance(iterator, enumerate):
                if idx % 50 == 0 or idx == 1:
                    elapsed = time.time() - start_time
                    rate = idx / elapsed if elapsed > 0 else 0
                    eta = (len(to_fetch) - idx) / rate if rate > 0 else 0
                    logger.info(
                        f"[进度] {idx}/{len(to_fetch)} "
                        f"成功={fetcher.stats['success']} 失败={fetcher.stats['failed']} "
                        f"空={fetcher.stats['empty']} "
                        f"速率={rate:.2f}只/s ETA={eta/3600:.1f}h "
                        f"当前: {code} {name} src={source_name} saved={saved}"
                    )

        except KeyboardInterrupt:
            logger.info("\n用户中断，进度已保存")
            break
        except Exception as e:
            fetcher.stats["failed"] += 1
            logger.error(f"[异常] {code} {name}: {e}")
            logger.debug(traceback.format_exc())
            # 失败后额外等待，避免连续失败触发限流
            time.sleep(5)

    # 汇总
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("抓取完成!")
    logger.info(f"  总耗时: {elapsed / 3600:.1f}h ({elapsed:.0f}s)")
    logger.info(f"  总数: {fetcher.stats['total']}")
    logger.info(f"  成功: {fetcher.stats['success']}")
    logger.info(f"  失败: {fetcher.stats['failed']}")
    logger.info(f"  空数据: {fetcher.stats['empty']}")
    if fetcher.source_stats:
        logger.info("  数据源贡献:")
        for src, cnt in sorted(fetcher.source_stats.items(), key=lambda x: -x[1]):
            logger.info(f"    {src}: {cnt} 只")
    logger.info(f"  进度文件: {PROGRESS_FILE}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
