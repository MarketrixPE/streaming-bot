import Link from "next/link";
import { Activity } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const t = await getTranslations("auth");
  const tApp = await getTranslations("app");

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6">
      <Card className="w-full max-w-md border-muted">
        <CardHeader className="flex flex-row items-center gap-3 pb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Activity className="h-5 w-5" />
          </div>
          <div>
            <CardTitle className="text-lg">{tApp("name")}</CardTitle>
            <p className="text-xs text-muted-foreground">{t("subtitle")}</p>
          </div>
        </CardHeader>
        <CardContent>
          <form
            action="/api/auth/sign-in/email"
            method="post"
            className="flex flex-col gap-3"
          >
            <label className="flex flex-col gap-1 text-sm font-medium">
              {t("email")}
              <Input
                type="email"
                name="email"
                autoComplete="email"
                required
                aria-label={t("email")}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm font-medium">
              {t("password")}
              <Input
                type="password"
                name="password"
                autoComplete="current-password"
                required
                aria-label={t("password")}
              />
            </label>
            <Button type="submit" size="lg">
              {t("submit")}
            </Button>
          </form>
          <p className="mt-4 text-xs text-muted-foreground">
            <Link href="/overview" className="underline-offset-4 hover:underline">
              {tApp("name")} MVP
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
