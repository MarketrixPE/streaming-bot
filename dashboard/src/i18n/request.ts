import { getRequestConfig } from "next-intl/server";

type SupportedLocale = "es" | "en";

const SUPPORTED: SupportedLocale[] = ["es", "en"];
const DEFAULT_LOCALE: SupportedLocale = "es";

const isSupported = (value: string | undefined): value is SupportedLocale =>
  SUPPORTED.includes(value as SupportedLocale);

export default getRequestConfig(async () => {
  const envLocale = process.env.NEXT_PUBLIC_DEFAULT_LOCALE;
  const locale: SupportedLocale = isSupported(envLocale) ? envLocale : DEFAULT_LOCALE;

  const messages = (await import(`./messages/${locale}.json`)).default as Record<
    string,
    unknown
  >;

  return {
    locale,
    messages,
  };
});
