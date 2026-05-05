import { getLocale } from "next-intl/server";
import { redirect } from "@/i18n/navigation";

export default async function FilesCreateRedirectPage() {
  redirect({ href: "/app/create", locale: await getLocale() });
}
