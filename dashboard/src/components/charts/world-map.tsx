"use client";

import * as React from "react";
import maplibregl, { type Map, type Marker } from "maplibre-gl";

import "maplibre-gl/dist/maplibre-gl.css";

import { cn } from "@/lib/utils";

export interface WorldMapMarker {
  id: string;
  lng: number;
  lat: number;
  tone?: "primary" | "success" | "warning" | "critical";
  label?: string;
}

export interface WorldMapProps {
  markers: WorldMapMarker[];
  className?: string;
  styleUrl?: string;
  initialCenter?: [number, number];
  initialZoom?: number;
}

const TONE_TO_COLOR: Record<NonNullable<WorldMapMarker["tone"]>, string> = {
  primary: "hsl(217 91% 60%)",
  success: "hsl(142 66% 45%)",
  warning: "hsl(38 92% 55%)",
  critical: "hsl(0 72% 51%)",
};

export default function WorldMap({
  markers,
  className,
  styleUrl,
  initialCenter = [-15, 20],
  initialZoom = 1.4,
}: WorldMapProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const mapRef = React.useRef<Map | null>(null);
  const markersRef = React.useRef<Marker[]>([]);

  const resolvedStyle =
    styleUrl ??
    process.env.NEXT_PUBLIC_MAP_STYLE_URL ??
    "https://demotiles.maplibre.org/style.json";

  React.useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: resolvedStyle,
      center: initialCenter,
      zoom: initialZoom,
      attributionControl: { compact: true },
    });
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      markersRef.current = [];
    };
  }, [resolvedStyle, initialCenter, initialZoom]);

  React.useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    for (const marker of markersRef.current) marker.remove();
    markersRef.current = [];

    const paint = () => {
      for (const m of markers) {
        const el = document.createElement("div");
        const color = TONE_TO_COLOR[m.tone ?? "primary"];
        el.style.width = "10px";
        el.style.height = "10px";
        el.style.borderRadius = "9999px";
        el.style.background = color;
        el.style.boxShadow = `0 0 0 4px ${color}22, 0 0 12px ${color}66`;
        el.setAttribute("aria-label", m.label ?? m.id);
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([m.lng, m.lat])
          .addTo(map);
        markersRef.current.push(marker);
      }
    };

    if (map.loaded()) paint();
    else map.once("load", paint);
  }, [markers]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "h-full min-h-[320px] w-full overflow-hidden rounded-xl border bg-muted",
        className,
      )}
    />
  );
}
