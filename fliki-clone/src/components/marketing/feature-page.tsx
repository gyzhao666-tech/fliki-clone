"use client";

import { Link } from "@/i18n/navigation";
import { ArrowRight, ChevronDown, Quote } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MarketingTopnav } from "@/components/marketing/topnav";
import { Footer } from "@/components/marketing/footer";

export type FeatureItem = { title: string; description: string };
export type TestimonialItem = { quote: string; author: string; role?: string };
export type FaqItem = { q: string; a: string };

export type FeaturePageProps = {
  badge: string;
  title: string;
  description: string;
  ctaLabel?: string;
  ctaHref?: string;
  features: FeatureItem[];
  testimonials?: TestimonialItem[];
  faqs: FaqItem[];
};

/* ─── Hero ─── */
function Hero({ badge, title, description, ctaLabel = "Get started free", ctaHref = "/signup" }: Pick<FeaturePageProps, "badge" | "title" | "description" | "ctaLabel" | "ctaHref">) {
  return (
    <section className="relative overflow-hidden bg-[var(--bg)] pt-20 pb-24 text-center">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[480px] bg-gradient-to-b from-[var(--brand-600)]/8 via-transparent to-transparent" />
      <div className="relative mx-auto max-w-5xl px-4">
        <Badge variant="primary" className="mb-6 inline-flex gap-1.5 px-3 py-1 text-sm">
          {badge}
        </Badge>
        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-[var(--text)] leading-[1.1] mb-6">
          {title}
        </h1>
        <p className="mx-auto max-w-2xl text-lg text-[var(--text-secondary)] mb-10">
          {description}
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Button size="lg" asChild>
            <Link href={ctaHref}>
              {ctaLabel} <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
          <Button variant="outline" size="lg" asChild>
            <Link href="/pricing">View pricing</Link>
          </Button>
        </div>
        <p className="mt-4 text-sm text-[var(--text-muted)]">No credit card required · Free plan available</p>
      </div>
    </section>
  );
}

/* ─── Features ─── */
function Features({ features }: { features: FeatureItem[] }) {
  const clean = features
    .filter((f) => f.description && !f.description.startsWith("Recovered section") && !f.description.startsWith("credit card"))
    .slice(0, 6);

  if (clean.length === 0) return null;

  return (
    <section className="py-24 bg-[var(--bg-subtle)]">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text)] mb-4">Key features</h2>
          <p className="max-w-xl mx-auto text-[var(--text-secondary)]">
            Everything you need to get started — in minutes.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {clean.map((f) => (
            <div
              key={f.title}
              className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6 hover:shadow-md transition-shadow"
            >
              <div className="mb-3 h-10 w-10 rounded-[var(--radius-lg)] bg-[var(--brand-600)]/10 flex items-center justify-center">
                <span className="text-lg font-bold text-[var(--brand-600)]">#</span>
              </div>
              <h3 className="text-base font-semibold text-[var(--text)] mb-2 line-clamp-2">{f.title}</h3>
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed line-clamp-4">{f.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Testimonials ─── */
const DEFAULT_TESTIMONIALS: TestimonialItem[] = [
  {
    quote: "Fliki makes video creation easy—just type your script, choose an AI avatar, and skip being on camera!",
    author: "Andy P.",
    role: "Real Estate Partner",
  },
  {
    quote: "I love how Fliki makes video creation easy with auto-picked visuals, voiceovers, and blog-to-video features. It's a must-have tool!",
    author: "Priyankaba G.",
  },
  {
    quote: "Fliki saves me so much time! It's 90% faster than other tools I've used for video creation.",
    author: "Tim V.",
  },
];

function Testimonials({ testimonials = DEFAULT_TESTIMONIALS }: { testimonials?: TestimonialItem[] }) {
  const list = testimonials
    .filter((t) => t.quote && !t.quote.includes("Best text-to-speech"))
    .slice(0, 3);

  return (
    <section className="py-24 bg-[var(--bg)]">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="text-center mb-16">
          <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text)] mb-4">Loved by creators worldwide</h2>
          <p className="text-[var(--text-secondary)]">Trusted by 50,000+ teams and individuals.</p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {list.map((t, i) => (
            <div
              key={i}
              className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6 flex flex-col gap-4"
            >
              <Quote className="h-6 w-6 text-[var(--brand-600)]/40 shrink-0" />
              <p className="text-sm text-[var(--text-secondary)] leading-relaxed flex-1 italic">&ldquo;{t.quote}&rdquo;</p>
              <div>
                <p className="text-sm font-semibold text-[var(--text)]">{t.author}</p>
                {t.role && <p className="text-xs text-[var(--text-muted)]">{t.role}</p>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── FAQ ─── */
function FAQ({ faqs }: { faqs: FaqItem[] }) {
  return (
    <section className="py-24 bg-[var(--bg-subtle)]">
      <div className="mx-auto max-w-3xl px-4 sm:px-6">
        <div className="text-center mb-14">
          <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text)] mb-4">Frequently asked questions</h2>
        </div>
        <div className="flex flex-col divide-y divide-[var(--border)]">
          {faqs.map((faq) => (
            <details key={faq.q} className="group py-5 cursor-pointer list-none">
              <summary className="flex items-center justify-between gap-4 text-base font-medium text-[var(--text)] select-none">
                {faq.q}
                <ChevronDown className="h-4 w-4 text-[var(--text-muted)] transition-transform group-open:rotate-180 shrink-0" />
              </summary>
              <p className="mt-3 text-sm text-[var(--text-secondary)] leading-relaxed">{faq.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Final CTA ─── */
function FinalCTA() {
  return (
    <section className="py-24 bg-[var(--brand-600)]">
      <div className="mx-auto max-w-3xl px-4 text-center">
        <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-4">Start creating for free</h2>
        <p className="text-lg mb-8 text-white/80">No credit card required. Cancel anytime.</p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Button size="lg" variant="secondary" asChild>
            <Link href="/signup">
              Get started free <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
          <Button size="lg" className="bg-white/10 text-white border border-white/20 hover:bg-white/20" asChild>
            <Link href="/pricing">View pricing</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

/* ─── Layout ─── */
export function FeaturePageLayout(props: FeaturePageProps) {
  return (
    <>
      <MarketingTopnav />
      <main>
        <Hero
          badge={props.badge}
          title={props.title}
          description={props.description}
          ctaLabel={props.ctaLabel}
          ctaHref={props.ctaHref}
        />
        <Features features={props.features} />
        <Testimonials testimonials={props.testimonials} />
        <FAQ faqs={props.faqs} />
        <FinalCTA />
      </main>
      <Footer />
    </>
  );
}
