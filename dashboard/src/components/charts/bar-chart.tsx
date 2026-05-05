"use client";

import { BarChart as TremorBarChart } from "@tremor/react";

export interface BarChartProps<T extends Record<string, unknown>> {
  data: T[];
  index: keyof T & string;
  categories: Array<keyof T & string>;
  valueFormatter?: (value: number) => string;
  colors?: string[];
  className?: string;
  layout?: "vertical" | "horizontal";
  yAxisWidth?: number;
  stack?: boolean;
}

const DEFAULT_COLORS = ["indigo", "cyan", "fuchsia", "emerald", "amber", "rose"];

export function BarChart<T extends Record<string, unknown>>({
  data,
  index,
  categories,
  valueFormatter,
  colors,
  className,
  layout = "horizontal",
  yAxisWidth = 48,
  stack = false,
}: BarChartProps<T>) {
  return (
    <TremorBarChart
      className={className}
      data={data as Array<Record<string, unknown>>}
      index={index}
      categories={categories as string[]}
      colors={colors ?? DEFAULT_COLORS.slice(0, categories.length)}
      valueFormatter={valueFormatter}
      yAxisWidth={yAxisWidth}
      layout={layout}
      stack={stack}
      showGridLines={false}
    />
  );
}
