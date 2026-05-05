import { Link } from "@/i18n/navigation";
import { Download, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MarketingTopnav } from "@/components/marketing/topnav";
import { Footer } from "@/components/marketing/footer";

export const metadata = {
  title: "Media Kit | Fliki",
  description: "Fliki's recent press coverage and brand resources for social media posts, webpages, mobile applications, or print materials.",
};

const brandColors = [
  { name: "Brand Pink", hex: "#fd3074", cls: "bg-[#fd3074]" },
  { name: "Brand Blue", hex: "#444ce7", cls: "bg-[#444ce7]" },
  { name: "Dark Text", hex: "#101828", cls: "bg-[#101828]" },
  { name: "Light Background", hex: "#f9fafb", cls: "bg-[#f9fafb] border" },
];

const resources = [
  { title: "Logo (PNG, SVG)", description: "Primary logo in color and monochrome. The color and shape should not be modified, with sufficient space around the logo." },
  { title: "Brand colors", description: "Official Fliki color palette with hex codes, for digital and print use." },
  { title: "Product screenshots", description: "High-resolution screenshots of the Fliki editor, dashboard, and feature pages." },
  { title: "Press description", description: "Short and long-form descriptions of Fliki for media use." },
];

export default function PressPage() {
  return (
    <>
      <MarketingTopnav />
      <main>
        {/* Hero */}
        <section className="relative overflow-hidden bg-[var(--bg)] pt-20 pb-24 text-center">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[480px] bg-gradient-to-b from-[var(--brand-600)]/8 via-transparent to-transparent" />
          <div className="relative mx-auto max-w-5xl px-4">
            <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight text-[var(--text)] leading-[1.1] mb-6">
              Media Kit
            </h1>
            <p className="mx-auto max-w-2xl text-lg text-[var(--text-secondary)] mb-10">
              Fliki&apos;s brand resources that you can include on your social media posts, webpage, mobile application, or in print materials.
            </p>
            <Button size="lg" asChild>
              <a href="#resources">
                <Download className="h-4 w-4" /> Browse resources
              </a>
            </Button>
          </div>
        </section>

        {/* What is Fliki */}
        <section className="py-20 bg-[var(--bg-subtle)]">
          <div className="mx-auto max-w-3xl px-4">
            <h2 className="text-2xl font-bold text-[var(--text)] mb-6 text-center">What is Fliki?</h2>
            <div className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-8">
              <p className="text-[var(--text-secondary)] leading-relaxed mb-4">
                <strong className="text-[var(--text)]">Short description:</strong> Fliki is an AI-powered text-to-video and text-to-speech platform that helps creators and teams produce professional videos and voiceovers in minutes — no editing skills required.
              </p>
              <p className="text-[var(--text-secondary)] leading-relaxed">
                <strong className="text-[var(--text)]">Long description:</strong> Fliki is a cutting-edge AI content creation platform that transforms text into professional-quality videos and voiceovers. With 2,000+ ultra-realistic AI voices in 80+ languages, a vast stock media library, and AI avatar technology, Fliki enables individuals and enterprise teams to create stunning content at scale — from social media videos to e-learning courses, podcasts, and marketing materials.
              </p>
            </div>
          </div>
        </section>

        {/* Brand Colors */}
        <section className="py-20 bg-[var(--bg)]">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <h2 className="text-2xl font-bold text-[var(--text)] mb-10 text-center">Brand colors</h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
              {brandColors.map((c) => (
                <div key={c.name} className="text-center">
                  <div className={`${c.cls} h-20 w-full rounded-[var(--radius-xl)] mb-3`} />
                  <p className="text-sm font-medium text-[var(--text)]">{c.name}</p>
                  <p className="text-xs text-[var(--text-muted)] font-mono">{c.hex}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Resources */}
        <section id="resources" className="py-20 bg-[var(--bg-subtle)]">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <h2 className="text-2xl font-bold text-[var(--text)] mb-10 text-center">Brand resources</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
              {resources.map((r) => (
                <div key={r.title} className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6 flex gap-4 items-start">
                  <div className="h-10 w-10 rounded-[var(--radius-lg)] bg-[var(--brand-600)]/10 flex items-center justify-center shrink-0">
                    <Download className="h-4 w-4 text-[var(--brand-600)]" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-[var(--text)] mb-1">{r.title}</h3>
                    <p className="text-sm text-[var(--text-secondary)]">{r.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="py-24 bg-[var(--brand-600)]">
          <div className="mx-auto max-w-3xl px-4 text-center">
            <h2 className="text-3xl font-extrabold text-white mb-4">Have questions about coverage?</h2>
            <p className="text-white/80 mb-8">We&apos;re always an email away — say hello at support@fliki.ai.</p>
            <Button size="lg" variant="secondary" asChild>
              <Link href="/signup">
                Try Fliki free <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
