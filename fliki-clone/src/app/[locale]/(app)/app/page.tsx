import { getLocale } from "next-intl/server";
import { redirect } from "@/i18n/navigation";

export default async function AppHomePage() {
  redirect({ href: "/app/files", locale: await getLocale() });
}
