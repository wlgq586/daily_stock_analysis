import { useMemo } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from 'recharts';
import type { KLineData } from '../../api/stocks';

type StockKLineChartProps = {
  data: KLineData[];
};

type ChartData = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  pctChg: number | null;
  isUp: boolean;
};

/** Format date string to show month-day */
function formatDate(dateStr: string): string {
  if (dateStr.length >= 10) {
    return dateStr.substring(5, 10);
  }
  return dateStr;
}

/** Format volume to 万/亿 */
function formatVolume(v: number | null): string {
  if (!v || v === 0) return '0';
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(0)}万`;
  return String(v);
}

/** Format number to 2 decimal places */
function formatNumber(n: number | null): string {
  if (n == null) return '-';
  return n.toFixed(2);
}

export const StockKLineChart: React.FC<StockKLineChartProps> = ({ data }) => {
  const chartData: ChartData[] = useMemo(
    () =>
      data.map((d) => ({
        date: d.date,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
        volume: d.volume ?? null,
        pctChg: d.change_percent ?? null,
        isUp: d.close >= d.open,
      })),
    [data],
  );

  if (data.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-secondary text-sm">
        暂无 K 线数据
      </div>
    );
  }

  // Calculate Y-axis domain for price
  const prices = chartData.flatMap((d) => [d.high, d.low]);
  const priceMin = Math.min(...prices);
  const priceMax = Math.max(...prices);
  const pricePad = (priceMax - priceMin) * 0.05 || 1;

  // Calculate Y-axis domain for volume
  const volumes = chartData.map((d) => d.volume ?? 0);
  const volMax = Math.max(...volumes);

  // Color based on first and last close
  const firstClose = chartData[0]?.close ?? 0;
  const lastClose = chartData[chartData.length - 1]?.close ?? 0;

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: any[] }) => {
    if (!active || !payload?.length) return null;
    const row = payload[0]?.payload as ChartData | undefined;
    if (!row) return null;
    return (
      <div className="rounded-lg border border-white/10 bg-base p-3 shadow-lg text-xs">
        <p className="font-medium text-foreground mb-1">{row.date}</p>
        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
          <span className="text-secondary">开盘</span>
          <span className="text-foreground text-right">{formatNumber(row.open)}</span>
          <span className="text-secondary">最高</span>
          <span className="text-green-500 text-right">{formatNumber(row.high)}</span>
          <span className="text-secondary">最低</span>
          <span className="text-red-500 text-right">{formatNumber(row.low)}</span>
          <span className="text-secondary">收盘</span>
          <span className={row.isUp ? 'text-green-500 text-right' : 'text-red-500 text-right'}>
            {formatNumber(row.close)}
          </span>
          <span className="text-secondary">涨跌幅</span>
          <span className={(row.pctChg ?? 0) >= 0 ? 'text-green-500 text-right' : 'text-red-500 text-right'}>
            {row.pctChg != null ? `${row.pctChg.toFixed(2)}%` : '-'}
          </span>
          <span className="text-secondary">成交量</span>
          <span className="text-foreground text-right">{formatVolume(row.volume)}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Summary line */}
      <div className="flex items-center gap-4 text-sm">
        <span className="text-secondary">
          起始: <span className="text-foreground font-medium">{chartData[0]?.date}</span>
        </span>
        <span className="text-secondary">
          最新: <span className="text-foreground font-medium">{chartData[chartData.length - 1]?.date}</span>
        </span>
        <span className="text-secondary">
          条数: <span className="text-foreground font-medium">{chartData.length}</span>
        </span>
        <span className="text-secondary">
          涨跌: {' '}
          <span
            className={`font-medium ${
              lastClose >= firstClose ? 'text-green-500' : 'text-red-500'
            }`}
          >
            {data[data.length - 1]?.close != null && data[0]?.close > 0
              ? `${(((data[data.length - 1].close - data[0].close) / data[0].close) * 100).toFixed(2)}%`
              : '-'}
          </span>
        </span>
      </div>

      {/* Candlestick + Volume Chart */}
      <ResponsiveContainer width="100%" height={420}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.3} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: 'var(--secondary-text)' }}
            tickFormatter={formatDate}
            interval="preserveStartEnd"
            minTickGap={40}
          />
          {/* Price Y-axis */}
          <YAxis
            yAxisId="price"
            domain={[priceMin - pricePad, priceMax + pricePad]}
            tick={{ fontSize: 10, fill: 'var(--secondary-text)' }}
            tickFormatter={(v: number) => v.toFixed(2)}
            width={65}
          />
          {/* Volume Y-axis */}
          <YAxis
            yAxisId="volume"
            orientation="right"
            domain={[0, volMax * 4]}
            tick={{ fontSize: 10, fill: 'var(--secondary-text)' }}
            tickFormatter={(v: number) => formatVolume(v)}
            width={55}
          />
          <Tooltip content={<CustomTooltip />} />

          {/* Volume bars */}
          <Bar
            yAxisId="volume"
            dataKey="volume"
            fill="var(--muted_blue)"
            opacity={0.3}
            isAnimationActive={false}
          >
            {chartData.map((entry) => (
              <Cell
                key={`vol-${entry.date}`}
                fill={entry.isUp ? 'var(--green_500, #22c55e)' : 'var(--red_500, #ef4444)'}
                fillOpacity={0.35}
              />
            ))}
          </Bar>

          {/* MA5 Line */}
          <Line
            yAxisId="price"
            type="monotone"
            dataKey={(d: unknown) => {
              const items = data as KLineData[];
              const idx = chartData.indexOf(d as ChartData);
              if (idx < 4) return null;
              const slice = items.slice(idx - 4, idx + 1);
              const sum = slice.reduce((acc, item) => acc + (item.close || 0), 0);
              return sum / 5;
            }}
            stroke="#f59e0b"
            strokeWidth={1}
            dot={false}
            name="MA5"
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
};
