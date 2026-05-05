import { Link } from "@/i18n/navigation";
import { Check, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MarketingTopnav } from "@/components/marketing/topnav";
import { Footer } from "@/components/marketing/footer";

const plans = [
  {
    name: "Free",
    price: "$0",
    period: "/month",
    description: "Perfect for getting started with AI video creation.",
    cta: "Get started free",
    ctaHref: "/signup",
    variant: "outline" as const,
    highlight: false,
    features: [
      "5 minutes of video/month",
      "720p export quality",
      "600+ AI voices",
      "Basic stock media",
      "Watermark on exports",
    ],
  },
  {
    name: "Standard",
    price: "$21",
    period: "/month",
    description: "Best for individuals and content creators.",
    cta: "Start free trial",
    ctaHref: "/signup?plan=standard",
    variant: "primary" as const,
    highlight: true,
    badge: "Most popular",
    features: [
      "130 minutes of video/month",
      "1080p export quality",
      "900+ AI voices",
      "Full stock media library",
      "No watermark",
      "Priority rendering",
      "Commercial license",
    ],
  },
  {
    name: "Premium",
    price: "$66",
    period: "/month",
    description: "For teams and high-volume creators.",
    cta: "Start free trial",
    ctaHref: "/signup?plan=premium",
    variant: "outline" as const,
    highlight: false,
    features: [
      "Unlimited minutes",
      "4K export quality",
      "900+ AI voices",
      "Full stock media library",
      "No watermark",
      "Priority rendering",
      "Commercial license",
      "Team collaboration",
      "API access",
      "Dedicated support",
    ],
  },
];

const compare = [
  { feature: "Video minutes / month", free: "5 min", standard: "130 min", premium: "Unlimited" },
  { feature: "Export quality", free: "720p", standard: "1080p", premium: "4K" },
  { feature: "AI voices", free: "600+", standard: "900+", premium: "900+" },
  { feature: "Stock media", free: "Basic", standard: "Full", premium: "Full" },
  { feature: "Watermark", free: "Yes", standard: "No", premium: "No" },
  { feature: "Commercial license", free: "—", standard: "✓", premium: "✓" },
  { feature: "API access", free: "—", standard: "—", premium: "✓" },
  { feature: "Team collaboration", free: "—", standard: "—", premium: "✓" },
];

export default function PricingPage() {
  return (
    <>
      <MarketingTopnav />
      <main className="bg-[var(--bg)] origin-top scale-[1.5]">
        {/* Header */}
        <section className="pt-20 pb-12 text-center px-4">
          <Badge variant="primary" className="mb-4">Pricing</Badge>
          <h1 className="text-4xl sm:text-5xl font-extrabold text-[var(--text)] mb-4">
            Simple, transparent pricing
          </h1>
          <p className="max-w-lg mx-auto text-lg text-[var(--text-secondary)]">
            Start for free, upgrade when you need more. All plans include a 7-day free trial.
          </p>
        </section>

        {/* Plans */}
        <section className="pb-20 px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
            {plans.map((plan) => (
              <div
                key={plan.name}
                className={`relative rounded-[var(--radius-2xl)] border p-7 flex flex-col gap-6 ${
                  plan.highlight
                    ? "border-[var(--brand-600)] shadow-xl bg-[var(--brand-600)]/5"
                    : "border-[var(--border)] bg-[var(--surface)]"
                }`}
              >
                {plan.badge && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[var(--brand-600)] text-white text-xs font-semibold px-3 py-1 rounded-full">
                    {plan.badge}
                  </span>
                )}

                <div>
                  <p className="text-sm font-semibold text-[var(--text-secondary)] mb-2">{plan.name}</p>
                  <div className="flex items-end gap-1 mb-2">
                    <span className="text-4xl font-extrabold text-[var(--text)]">{plan.price}</span>
                    <span className="text-[var(--text-muted)] mb-1">{plan.period}</span>
                  </div>
                  <p className="text-sm text-[var(--text-secondary)]">{plan.description}</p>
                </div>

                <Button variant={plan.variant} className="w-full" asChild>
                  <Link href={plan.ctaHref}>
                    {plan.cta} <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>

                <ul className="flex flex-col gap-2.5">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-2.5 text-sm text-[var(--text-secondary)]">
                      <Check className="h-4 w-4 text-[var(--brand-600)] mt-0.5 shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        {/* Compare table */}
        <section className="pb-24 px-4">
          <div className="mx-auto max-w-7xl">
            <h2 className="text-2xl font-bold text-[var(--text)] text-center mb-8">Full feature comparison</h2>
            <div className="overflow-x-auto rounded-[var(--radius-xl)] border border-[var(--border)]">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)] bg-[var(--bg-subtle)]">
                    <th className="text-left px-5 py-3 font-semibold text-[var(--text)]">Feature</th>
                    {["Free", "Standard", "Premium"].map((h) => (
                      <th key={h} className="px-5 py-3 font-semibold text-[var(--text)] text-center">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {compare.map((row, i) => (
                    <tr key={row.feature} className={i % 2 === 0 ? "bg-[var(--surface)]" : "bg-[var(--bg-subtle)]"}>
                      <td className="px-5 py-3 text-[var(--text-secondary)]">{row.feature}</td>
                      <td className="px-5 py-3 text-center text-[var(--text-secondary)]">{row.free}</td>
                      <td className="px-5 py-3 text-center text-[var(--text-secondary)] font-medium">{row.standard}</td>
                      <td className="px-5 py-3 text-center text-[var(--text-secondary)]">{row.premium}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
