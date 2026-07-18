import type React from 'react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, TrendingUp, BarChart3 } from 'lucide-react';
import { stocksApi } from '../api/stocks';
import type { StockListItem, KLineData } from '../api/stocks';
import type { ParsedApiError } from '../api/error';
import { getParsedApiError } from '../api/error';
import { Drawer, EmptyState, ApiErrorAlert, Pagination } from '../components/common';
import { StockKLineChart } from '../components/stock/StockKLineChart';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { formatUiText } from '../i18n/uiText';

const StocksPage: React.FC = () => {
  const { t } = useUiLanguage();
  const navigate = useNavigate();

  const [stocks, setStocks] = useState<StockListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);

  // K-line drawer state
  const [klineOpen, setKlineOpen] = useState(false);
  const [klineData, setKlineData] = useState<KLineData[]>([]);
  const [klineLoading, setKlineLoading] = useState(false);
  const [klineStock, setKlineStock] = useState<StockListItem | null>(null);

  useEffect(() => {
    document.title = t('stocks.pageTitle');
  }, [t]);

  const loadStocks = useCallback(async (p?: number, s?: string) => {
    setLoading(true);
    setError(null);
    try {
      const currentPage = p ?? page;
      const currentSearch = s ?? search;
      const response = await stocksApi.listStocks({
        page: currentPage,
        pageSize,
        search: currentSearch || undefined,
      });
      setStocks(response.stocks || []);
      setTotal(response.total);
      setTotalPages(response.total_pages);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoading(false);
    }
  }, [page, search, pageSize]);

  useEffect(() => {
    void loadStocks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = useCallback((value: string) => {
    setSearch(value);
    setPage(1);
    // loadStocks will be called via useEffect below
  }, []);

  useEffect(() => {
    if (stocks.length > 0 || search !== '' || page > 1) {
      void loadStocks(page, search);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search]);



  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
  }, []);

  const handlePageSizeChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setPageSize(Number(e.target.value));
    setPage(1);
  }, []);

  const handleViewKLine = useCallback(async (stock: StockListItem) => {
    setKlineStock(stock);
    setKlineOpen(true);
    setKlineLoading(true);
    setKlineData([]);
    try {
      const response = await stocksApi.getStockKLine(stock.code);
      setKlineData(response.data);
    } catch {
      setKlineData([]);
    } finally {
      setKlineLoading(false);
    }
  }, []);

  const handleAnalyze = useCallback(
    (stock: StockListItem) => {
      // Navigate to home page with the stock code as query param
      navigate(`/?stock=${encodeURIComponent(stock.code)}`);
    },
    [navigate],
  );

  const handleCloseKLine = useCallback(() => {
    setKlineOpen(false);
    setKlineStock(null);
    setKlineData([]);
  }, []);

  const klineTitle = klineStock
    ? formatUiText(t('stocks.klineTitle'), {
        name: klineStock.name || klineStock.code,
        code: klineStock.code,
      })
    : '';

  if (error) {
    return (
      <div className="min-h-screen space-y-4 p-4 md:p-6">
        <h1 className="text-xl md:text-2xl font-semibold text-foreground">{t('stocks.title')}</h1>
        <ApiErrorAlert error={error} />
        <button type="button" className="btn-primary text-sm" onClick={() => void loadStocks()}>
          {t('common.retry')}
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen space-y-4 p-4 md:p-6">
      {/* Header */}
      <section className="space-y-2">
        <h1 className="text-xl md:text-2xl font-semibold text-foreground">{t('stocks.title')}</h1>
        <p className="text-xs md:text-sm text-secondary">{t('stocks.description')}</p>
      </section>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-text" />
          <input
            type="text"
            className="h-10 w-full rounded-xl border border-white/[0.08] bg-white/[0.03] pl-10 pr-4 text-sm text-foreground placeholder:text-muted-text transition-all focus:border-primary/50 focus:bg-white/[0.05] focus:outline-none focus:ring-1 focus:ring-primary/20"
            placeholder={t('stocks.searchPlaceholder')}
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
          />
        </div>
        <span className="text-sm text-muted-text tabular-nums font-medium">
          {formatUiText(t('stocks.total'), { count: total })}
        </span>
        {/* Page size selector */}
        <select
          className="h-10 rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 pr-8 text-sm text-secondary-text transition-colors hover:border-primary/30 focus:border-primary/50 focus:outline-none focus:ring-1 focus:ring-primary/20"
          value={pageSize}
          onChange={handlePageSizeChange}
        >
          {[10, 20, 50, 100].map((n) => (
            <option key={n} value={n}>{n} 条/页</option>
          ))}
        </select>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-xl border border-white/[0.08] bg-white/[0.03] px-4 py-2 text-sm font-medium text-secondary-text transition-all hover:border-primary/30 hover:text-primary hover:bg-primary/[0.06] disabled:opacity-40"
          onClick={() => void loadStocks()}
          disabled={loading}
        >
          {loading ? t('stocks.loading') : t('common.retry')}
        </button>
      </div>

      {/* Table */}
      {loading && stocks.length === 0 ? (
        <div className="flex items-center justify-center py-20 text-muted-text text-sm">
          {t('stocks.loading')}
        </div>
      ) : stocks.length === 0 ? (
        <EmptyState
          title={search.trim() ? t('common.noData') : t('stocks.empty')}
          description={search.trim() ? undefined : undefined}
        />
      ) : (
        <>
        <div className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.01] shadow-sm">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/[0.06] bg-white/[0.03] text-left text-xs uppercase tracking-wider text-muted-text">
                <th className="px-3 py-3.5 font-semibold w-12">#</th>
                <th className="px-4 py-3.5 font-semibold">{t('stocks.code')}</th>
                <th className="px-4 py-3.5 font-semibold">{t('stocks.name')}</th>
                <th className="px-4 py-3.5 font-semibold text-right">{t('stocks.dataCount')}</th>
                <th className="px-4 py-3.5 font-semibold">{t('stocks.dateRange')}</th>
                <th className="px-4 py-3.5 font-semibold text-right">{t('stocks.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {stocks.map((stock, idx) => {
                const isEvenGroup = Math.floor(idx / 2) % 2 === 0;
                const isLastInGroup = idx % 2 === 1 || idx === stocks.length - 1;
                return (
                <tr
                  key={stock.code}
                  className={`transition-colors hover:bg-primary/[0.04] ${
                    isEvenGroup ? 'bg-white/[0.02]' : ''
                  } ${isLastInGroup ? 'border-b border-white/[0.06]' : 'border-b border-white/[0.02]'}`}
                >
                  <td className="px-3 py-3 tabular-nums text-muted-text text-xs">
                    {(page - 1) * pageSize + idx + 1}
                  </td>
                  <td className="px-4 py-3 font-mono text-sm text-foreground font-medium">{stock.code}</td>
                  <td className="px-4 py-3 text-foreground text-sm">
                    {stock.name || <span className="text-muted-text italic">—</span>}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-secondary-text text-sm">
                    {stock.data_count}
                  </td>
                  <td className="px-4 py-3 text-secondary-text text-sm">
                    {stock.first_date && stock.last_date
                      ? `${stock.first_date} ~ ${stock.last_date}`
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1.5 rounded-lg border border-primary/20 bg-primary/[0.04] px-3 py-1.5 text-xs font-medium text-primary/80 transition-all hover:border-primary/50 hover:bg-primary/[0.1] hover:text-primary"
                        onClick={() => void handleViewKLine(stock)}
                      >
                        <TrendingUp className="h-3.5 w-3.5" />
                        {t('stocks.kline')}
                      </button>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-secondary-text transition-all hover:border-white/[0.2] hover:bg-white/[0.06] hover:text-foreground"
                        onClick={() => handleAnalyze(stock)}
                      >
                        <BarChart3 className="h-3.5 w-3.5" />
                        {t('stocks.analyze')}
                      </button>
                    </div>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          onPageChange={handlePageChange}
        />
        </>
      )}

      {/* K-Line Drawer */}
      <Drawer
        isOpen={klineOpen}
        onClose={handleCloseKLine}
        title={klineTitle}
        width="max-w-4xl"
      >
        {klineLoading ? (
          <div className="flex items-center justify-center py-20 text-secondary text-sm">
            {t('stocks.loading')}
          </div>
        ) : (
          <StockKLineChart data={klineData} />
        )}
      </Drawer>
    </div>
  );
};

export default StocksPage;
