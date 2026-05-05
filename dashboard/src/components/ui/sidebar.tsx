"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

interface SidebarContextValue {
  collapsed: boolean;
  setCollapsed: (value: boolean) => void;
}

const SidebarContext = React.createContext<SidebarContextValue | null>(null);

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = React.useState(false);
  const value = React.useMemo(() => ({ collapsed, setCollapsed }), [collapsed]);
  return <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>;
}

export function useSidebar(): SidebarContextValue {
  const ctx = React.useContext(SidebarContext);
  if (!ctx) throw new Error("useSidebar must be used within SidebarProvider");
  return ctx;
}

export function SidebarRoot({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  const { collapsed } = useSidebar();
  return (
    <aside
      data-collapsed={collapsed}
      className={cn(
        "hidden h-full shrink-0 border-r bg-card transition-[width] duration-200 ease-in-out md:flex md:flex-col",
        collapsed ? "w-16" : "w-60",
        className,
      )}
    >
      {children}
    </aside>
  );
}

export function SidebarHeader({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("flex h-14 items-center border-b px-4", className)}>{children}</div>
  );
}

export function SidebarContent({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <nav className={cn("flex-1 space-y-1 overflow-y-auto p-2 scrollbar-thin", className)}>
      {children}
    </nav>
  );
}

export function SidebarFooter({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return <div className={cn("border-t p-2", className)}>{children}</div>;
}
