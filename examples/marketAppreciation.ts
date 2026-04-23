type AppreciationCard = {
  label: string;
  value: string;
};

type MarketAppreciationResponse = {
  market_key: string;
  property_type_slug: string;
  source_key: string | null;
  source_name: string | null;
  property_type_label: string | null;
  available: boolean;
  latest_benchmark_price: number | null;
  latest_benchmark_price_display: string | null;
  latest_date: string | null;
  change_12m: string | null;
  change_1m: string | null;
  appreciation_5y_cagr: string | null;
  appreciation_10y_cagr: string | null;
  trend_direction: string | null;
  trend_label: string | null;
  data_quality_flag: string | null;
  empty_message: string | null;
  notes: string | null;
  metric_cards: AppreciationCard[];
};

export async function fetchMarketAppreciation(
  marketKey: string,
  propertyType: string = "composite",
): Promise<MarketAppreciationResponse> {
  const response = await fetch(`/api/markets/${marketKey}/appreciation?property_type=${propertyType}`);
  if (!response.ok) {
    throw new Error(`Failed to load appreciation for ${marketKey}`);
  }
  return response.json();
}

export function renderAppreciationSummary(data: MarketAppreciationResponse): string {
  if (!data.available) {
    return data.empty_message ?? "Appreciation data is not available for this market.";
  }

  return [
    `Benchmark price: ${data.latest_benchmark_price_display ?? "—"}`,
    `5-year annualized appreciation: ${data.appreciation_5y_cagr ?? "—"}`,
    `10-year annualized appreciation: ${data.appreciation_10y_cagr ?? "—"}`,
    `12-month change: ${data.change_12m ?? "—"}`,
    `Source: ${data.source_name ?? "Unknown"}`,
  ].join("\n");
}
