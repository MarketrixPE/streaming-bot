"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Activity,
  AlertTriangle,
  ChevronsLeft,
  ChevronsRight,
  LayoutDashboard,
  ListChecks,
  Music2,
  Users,
} from "lucide-react";

import {
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarRoot,
  useSidebar,
} from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  key: "overview" | "catalog" | "accounts" | "jobs" | "anomaly";
  icon: React.ElementType;
}

const NAV: NavItem[] = [
  { href: "/overview", key: "overview", icon: LayoutDashboard },
  { href: "/catalog", key: "catalog", icon: Music2 },
  { href: "/accounts", key: "accounts", icon: Users },
  { href: "/jobs", key: "jobs", icon: ListChecks },
  { href: "/anomaly", key: "anomaly", icon: AlertTriangle },
];

export function Sidebar() {
  const pathname = usePathname();
  const tNav = useTranslations("nav");
  const tApp = useTranslations("app");
  const { collapsed, setCollapsed } = useSidebar();

  return (
    <SidebarRoot>
      <SidebarHeader className="justify-between">
        <div className="flex items-center gap-2 overflow-hidden">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Activity className="h-4 w-4" />
          </div>
          {collapsed ? null : (
            <div className="flex flex-col leading-tight">
              <span className="text-sm font-semibold">{tApp("name")}</span>
              <span className="truncate text-[10px] text-muted-foreground">
                {tApp("tagline")}
              </span>
            </div>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronsRight className="h-4 w-4" />
          ) : (
            <ChevronsLeft className="h-4 w-4" />
          )}
        </Button>
      </SidebarHeader>
      <SidebarContent>
        {NAV.map((item) => {
          const isActive = pathname?.startsWith(item.href) ?? false;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "group flex h-9 items-center gap-3 rounded-md px-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {collapsed ? null : <span>{tNav(item.key)}</span>}
            </Link>
          );
        })}
      </SidebarContent>
      <SidebarFooter>
        {collapsed ? null : (
          <p className="px-2 text-[10px] uppercase tracking-wider text-muted-foreground">
            v0.1 MVP
          </p>
        )}
      </SidebarFooter>
    </SidebarRoot>
  );
}
