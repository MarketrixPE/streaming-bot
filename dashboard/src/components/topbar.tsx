"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import { Bell, LogOut, Moon, Search, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

interface TopbarProps {
  title: string;
  subtitle?: string;
}

export function Topbar({ title, subtitle }: TopbarProps) {
  const t = useTranslations("common");
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  const effectiveTheme = mounted ? (theme === "system" ? resolvedTheme : theme) : "dark";

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur">
      <div className="flex flex-1 items-center gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold leading-tight">{title}</h1>
          {subtitle ? (
            <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        <Separator orientation="vertical" className="mx-2 hidden h-6 md:block" />
        <div className="relative hidden max-w-xs flex-1 md:block">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder={t("search")} className="h-9 pl-8" aria-label={t("search")} />
        </div>
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle theme"
          onClick={() => setTheme(effectiveTheme === "dark" ? "light" : "dark")}
        >
          <Sun className={cn("h-4 w-4", effectiveTheme === "dark" && "hidden")} />
          <Moon className={cn("h-4 w-4", effectiveTheme !== "dark" && "hidden")} />
        </Button>
        <Button variant="ghost" size="icon" aria-label="Notifications">
          <Bell className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" aria-label={t("logout")}>
          <LogOut className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
