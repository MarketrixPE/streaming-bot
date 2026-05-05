"use client";

import { AreaChart as TremorAreaChart } from "@tremor/react";

export interface AreaChartProps<T extends Record<string, unknown>> {
  data: T[];
  index: keyof T & string;
  categories: Array<keyof T & string>;
  valueFormatter?: (value: number) => string;
  className?: string;
  colors?: string[];
  yAxisWidth?: number;
  showLegend?: boolean;
}

const DEFAULT_COLORS = ["indigo", "cyan", "fuchsia", "emerald", "amber", "rose"];

export function AreaChart<T extends Record<string, unknown>>({
  data,
  index,
  categories,
  valueFormatter,
  className,
  colors,
  yAxisWidth = 48,
  showLegend = true,
}: AreaChartProps<T>) {
  return (
    <TremorAreaChart
      className={className}
      data={data as Array<Record<string, unknown>>}
      index={index}
      categories={categories as string[]}
      colors={colors ?? DEFAULT_COLORS.slice(0, categories.length)}
      valueFormatter={valueFormatter}
      yAxisWidth={yAxisWidth}
      showLegend={showLegend}
      showGridLines={false}
      curveType="monotone"
    />
  );
}
