import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts';
import type {
  IChartApi,
  ISeriesApi,
  Time,
  CandlestickData,
  HistogramData,
  LineData,
  MouseEventParams,
} from 'lightweight-charts';
import type { KLineData } from '../../api/stocks';

type StockKLineChartProps = {
  data: KLineData[];
};

/** A股习惯：红涨绿跌 */
const UP_COLOR = '#ef4444';
const DOWN_COLOR = '#22c55e';

/** 均线配置 */
const MA_CONFIGS = [
  { period: 5, color: '#f59e0b', label: 'MA5' },
  { period: 10, color: '#3b82f6', label: 'MA10' },
  { period: 20, color: '#a855f7', label: 'MA20' },
  { period: 60, color: '#14b8a6', label: 'MA60' },
] as const;

/** 转成 lightweight-charts 的 time（yyyy-mm-dd） */
function toTime(dateStr: string): Time {
  return (dateStr.length > 10 ? dateStr.substring(0, 10) : dateStr) as Time;
}

/** 格式化成交量：万/亿 */
function formatVolume(v: number | null | undefined): string {
  if (!v || v === 0) return '-';
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (v >= 1e4) return `${(v / 1e4).toFixed(1)}万`;
  return String(Math.round(v));
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '-';
  return n.toFixed(2);
}

/** 计算移动平均线（滑动窗口） */
function calcMA(data: KLineData[], period: number): LineData[] {
  const result: LineData[] = [];
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    sum += data[i].close;
    if (i >= period) sum -= data[i - period].close;
    if (i >= period - 1) {
      result.push({ time: toTime(data[i].date), value: sum / period });
    }
  }
  return result;
}

type HoverInfo = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  pctChg: number | null;
  isUp: boolean;
  maValues: (number | null)[];
};

export const StockKLineChart: React.FC<StockKLineChartProps> = ({ data }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);

  /** 按日期索引原始数据 + 预计算均线，供 crosshair 联动 */
  const { rowByTime, maLines, pctChgByTime } = useMemo(() => {
    const rowMap = new Map<string, KLineData>();
    const pctMap = new Map<string, number | null>();
    data.forEach((d, i) => {
      const key = String(toTime(d.date));
      rowMap.set(key, d);
      if (d.change_percent != null) {
        pctMap.set(key, d.change_percent);
      } else if (i > 0 && data[i - 1].close > 0) {
        pctMap.set(key, ((d.close - data[i - 1].close) / data[i - 1].close) * 100);
      } else {
        pctMap.set(key, null);
      }
    });
    const lines = MA_CONFIGS.map((cfg) => ({
      ...cfg,
      points: calcMA(data, cfg.period),
      byTime: new Map(calcMA(data, cfg.period).map((p) => [String(p.time), p.value])),
    }));
    return { rowByTime: rowMap, maLines: lines, pctChgByTime: pctMap };
  }, [data]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || data.length === 0) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#94a3b8',
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: 'rgba(148, 163, 184, 0.08)' },
        horzLines: { color: 'rgba(148, 163, 184, 0.08)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { labelBackgroundColor: '#334155' },
        horzLine: { labelBackgroundColor: '#334155' },
      },
      rightPriceScale: {
        borderColor: 'rgba(148, 163, 184, 0.2)',
        scaleMargins: { top: 0.05, bottom: 0.22 },
      },
      timeScale: {
        borderColor: 'rgba(148, 163, 184, 0.2)',
        rightOffset: 2,
        minBarSpacing: 2,
      },
      localization: {
        priceFormatter: (p: number) => p.toFixed(2),
      },
    });
    chartRef.current = chart;

    // 蜡烛图主图
    const candleSeries: ISeriesApi<'Candlestick'> = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
      priceLineVisible: false,
    });
    const candleData: CandlestickData[] = data.map((d) => ({
      time: toTime(d.date),
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }));
    candleSeries.setData(candleData);

    // 成交量副图（独立价格轴，压缩在底部 18%）
    const volumeSeries: ISeriesApi<'Histogram'> = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.84, bottom: 0 },
    });
    const volumeData: HistogramData[] = data.map((d) => ({
      time: toTime(d.date),
      value: d.volume ?? 0,
      color: d.close >= d.open ? 'rgba(239, 68, 68, 0.45)' : 'rgba(34, 197, 94, 0.45)',
    }));
    volumeSeries.setData(volumeData);

    // 均线
    maLines.forEach((cfg) => {
      const line: ISeriesApi<'Line'> = chart.addSeries(LineSeries, {
        color: cfg.color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      line.setData(cfg.points);
    });

    // crosshair 联动顶部 legend
    const handleCrosshairMove = (param: MouseEventParams) => {
      if (!param.time) {
        setHover(null);
        return;
      }
      const key = String(param.time);
      const row = rowByTime.get(key);
      if (!row) {
        setHover(null);
        return;
      }
      setHover({
        date: row.date,
        open: row.open,
        high: row.high,
        low: row.low,
        close: row.close,
        volume: row.volume ?? null,
        pctChg: pctChgByTime.get(key) ?? null,
        isUp: row.close >= row.open,
        maValues: maLines.map((cfg) => cfg.byTime.get(key) ?? null),
      });
    };
    chart.subscribeCrosshairMove(handleCrosshairMove);

    // 默认显示最近 120 根，可拖动/缩放查看全部
    const timeScale = chart.timeScale();
    if (data.length > 120) {
      timeScale.setVisibleLogicalRange({
        from: data.length - 120,
        to: data.length + 2,
      });
    } else {
      timeScale.fitContent();
    }

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove);
      chart.remove();
      chartRef.current = null;
    };
  }, [data, maLines, rowByTime, pctChgByTime]);

  if (data.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-secondary text-sm">
        暂无 K 线数据
      </div>
    );
  }

  const last = data[data.length - 1];
  const lastKey = String(toTime(last.date));
  const display: HoverInfo = hover ?? {
    date: last.date,
    open: last.open,
    high: last.high,
    low: last.low,
    close: last.close,
    volume: last.volume ?? null,
    pctChg: pctChgByTime.get(lastKey) ?? null,
    isUp: last.close >= last.open,
    maValues: maLines.map((cfg) => cfg.byTime.get(lastKey) ?? null),
  };
  const pctColor = (display.pctChg ?? 0) >= 0 ? 'text-red-500' : 'text-green-500';

  return (
    <div className="space-y-2">
      {/* OHLC legend（悬浮联动） */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums">
        <span className="font-medium text-foreground">{display.date.substring(0, 10)}</span>
        <span className="text-secondary">
          开 <span className="text-foreground">{formatNumber(display.open)}</span>
        </span>
        <span className="text-secondary">
          高 <span className="text-red-500">{formatNumber(display.high)}</span>
        </span>
        <span className="text-secondary">
          低 <span className="text-green-500">{formatNumber(display.low)}</span>
        </span>
        <span className="text-secondary">
          收 <span className={display.isUp ? 'text-red-500' : 'text-green-500'}>{formatNumber(display.close)}</span>
        </span>
        <span className="text-secondary">
          涨跌 {' '}
          <span className={pctColor}>
            {display.pctChg != null ? `${display.pctChg >= 0 ? '+' : ''}${display.pctChg.toFixed(2)}%` : '-'}
          </span>
        </span>
        <span className="text-secondary">
          量 <span className="text-foreground">{formatVolume(display.volume)}</span>
        </span>
      </div>

      {/* 均线 legend */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums">
        {maLines.map((cfg, i) => (
          <span key={cfg.label} style={{ color: cfg.color }}>
            {cfg.label}: {formatNumber(display.maValues[i])}
          </span>
        ))}
      </div>

      {/* 图表容器 */}
      <div ref={containerRef} className="h-[420px] w-full" />

      {/* 底部统计 */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-secondary">
        <span>
          区间: <span className="text-foreground">{data[0]?.date?.substring(0, 10)} ~ {last.date?.substring(0, 10)}</span>
        </span>
        <span>
          条数: <span className="text-foreground">{data.length}</span>
        </span>
        <span>
          区间涨跌: {' '}
          <span className={last.close >= data[0].close ? 'text-red-500' : 'text-green-500'}>
            {data[0].close > 0
              ? `${(((last.close - data[0].close) / data[0].close) * 100).toFixed(2)}%`
              : '-'}
          </span>
        </span>
        <span className="text-muted-text">滚轮缩放 · 拖动平移</span>
      </div>
    </div>
  );
};
