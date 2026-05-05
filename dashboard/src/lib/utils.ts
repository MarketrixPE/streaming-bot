import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatNumber(value: number, locale = "es-ES"): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}

export function formatCurrency(value: number, currency = "USD", locale = "es-ES"): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatPercent(value: number, locale = "es-ES"): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatRelative(iso: string, locale = "es-ES"): string {
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return "-";
  const diff = target - Date.now();
  const abs = Math.abs(diff);
  const minute = 60_000;
  const hour = minute * 60;
  const day = hour * 24;

  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (abs < minute) return rtf.format(Math.round(diff / 1000), "second");
  if (abs < hour) return rtf.format(Math.round(diff / minute), "minute");
  if (abs < day) return rtf.format(Math.round(diff / hour), "hour");
  return rtf.format(Math.round(diff / day), "day");
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}
