"use client";

import { Area, AreaChart, ResponsiveContainer } from "recharts";

export interface SparklineProps {
  data: Array<{ t: string; value: number }>;
  colorVar?: string;
  height?: number;
}

export function Sparkline({ data, colorVar = "217 91% 60%", height = 48 }: SparklineProps) {
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, bottom: 0, left: 0, right: 0 }}>
          <defs>
            <linearGradient id="sparkline" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={`hsl(${colorVar})`} stopOpacity={0.5} />
              <stop offset="100%" stopColor={`hsl(${colorVar})`} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="value"
            stroke={`hsl(${colorVar})`}
            strokeWidth={2}
            fill="url(#sparkline)"
            dot={false}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
