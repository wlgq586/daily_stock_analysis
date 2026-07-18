import apiClient from './index';

export type ExtractItem = {
  code?: string | null;
  name?: string | null;
  confidence: string;
};

export type ExtractFromImageResponse = {
  codes: string[];
  items?: ExtractItem[];
  rawText?: string;
};

export type StockListItem = {
  code: string;
  name?: string | null;
  data_count: number;
  first_date?: string | null;
  last_date?: string | null;
};

export type StockListResponse = {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  stocks: StockListItem[];
};

export type KLineData = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  amount?: number | null;
  change_percent?: number | null;
};

export type StockHistoryResponse = {
  stock_code: string;
  stock_name?: string | null;
  period: string;
  data: KLineData[];
};

export const stocksApi = {
  async extractFromImage(file: File): Promise<ExtractFromImageResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
    const response = await apiClient.post(
      '/api/v1/stocks/extract-from-image',
      formData,
      {
        headers,
        timeout: 60000, // Vision API can be slow; 60s
      },
    );

    const data = response.data as { codes?: string[]; items?: ExtractItem[]; raw_text?: string };
    return {
      codes: data.codes ?? [],
      items: data.items,
      rawText: data.raw_text,
    };
  },

  async parseImport(file?: File, text?: string): Promise<ExtractFromImageResponse> {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
      const response = await apiClient.post('/api/v1/stocks/parse-import', formData, { headers });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    if (text) {
      const response = await apiClient.post('/api/v1/stocks/parse-import', { text });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    throw new Error('请提供文件或粘贴文本');
  },

  async listStocks(params?: {
    page?: number;
    pageSize?: number;
    search?: string;
  }): Promise<StockListResponse> {
    const query: Record<string, string> = {};
    if (params?.page) query.page = String(params.page);
    if (params?.pageSize) query.page_size = String(params.pageSize);
    if (params?.search) query.search = params.search;
    const response = await apiClient.get('/api/v1/stocks/', { params: query });
    return response.data as StockListResponse;
  },

  async getStockKLine(
    stockCode: string,
    startDate?: string,
    endDate?: string,
  ): Promise<StockHistoryResponse> {
    const params: Record<string, string> = {};
    if (startDate) params.start_date = startDate;
    if (endDate) params.end_date = endDate;
    const response = await apiClient.get(`/api/v1/stocks/${stockCode}/kline`, { params });
    return response.data as StockHistoryResponse;
  },
};
