import { Link } from "@/i18n/navigation";
import { ArrowRight, Heart, Users, Zap, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MarketingTopnav } from "@/components/marketing/topnav";
import { Footer } from "@/components/marketing/footer";

export const metadata = {
  title: "About Fliki | AI Video & Voiceover Platform",
  description: "Fliki is a text-to-video and text-to-speech creator that helps you create quality audio and video content in minutes.",
};

const stats = [
  { label: "Active users", value: "2M+" },
  { label: "Videos created", value: "10M+" },
  { label: "Languages supported", value: "80+" },
  { label: "AI voices available", value: "2,000+" },
];

const values = [
  {
    icon: Zap,
    title: "Speed & simplicity",
    description: "We believe creating professional content shouldn't take hours. Our tools turn minutes of effort into high-quality output.",
  },
  {
    icon: Globe,
    title: "Global accessibility",
    description: "Language shouldn't be a barrier. We support 80+ languages and 100+ accents so your message reaches everyone, everywhere.",
  },
  {
    icon: Heart,
    title: "Creator-first",
    description: "Every feature we build starts with the creator in mind. We listen to our community and ship what actually matters.",
  },
  {
    icon: Users,
    title: "Team-ready",
    description: "Whether you're a solo creator or a 500-person enterprise team, Fliki scales with you and your content needs.",
  },
];

export default function AboutPage() {
  return (
    <>
      <MarketingTopnav />
      <main>
        {/* Hero */}
        <section className="relative overflow-hidden bg-[var(--bg)] pt-20 pb-24 text-center">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[480px] bg-gradient-to-b from-[var(--brand-600)]/8 via-transparent to-transparent" />
          <div className="relative mx-auto max-w-5xl px-4">
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-[var(--text)] leading-[1.1] mb-6">
              About Fliki
            </h1>
            <p className="mx-auto max-w-2xl text-lg text-[var(--text-secondary)] mb-10">
              Fliki is a text-to-video and text-to-speech creator that helps you create quality audio and video content in minutes. We&apos;re on a mission to democratize content creation with the power of AI.
            </p>
            <Button size="lg" asChild>
              <Link href="/signup">
                Get started free <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>

        {/* Stats */}
        <section className="py-16 bg-[var(--bg-subtle)]">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-8 text-center">
              {stats.map((s) => (
                <div key={s.label}>
                  <p className="text-3xl sm:text-4xl font-extrabold text-[var(--brand-600)]">{s.value}</p>
                  <p className="mt-1 text-sm text-[var(--text-secondary)]">{s.label}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Vision */}
        <section className="py-24 bg-[var(--bg)]">
          <div className="mx-auto max-w-3xl px-4 text-center">
            <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text)] mb-6">Our vision & mission</h2>
            <p className="text-lg text-[var(--text-secondary)] leading-relaxed mb-6">
              We have a vision to create a platform where users could create audio and video content and simplify this process with the power of AI. We believe that this technology has the potential to revolutionize how people communicate and share their ideas with the world.
            </p>
            <p className="text-[var(--text-secondary)] leading-relaxed">
              Founded by Atul Yadav, Fliki started as a simple idea: what if creating professional videos was as easy as writing a few sentences? Today, over 2 million creators use Fliki to bring their ideas to life—without any video editing experience.
            </p>
          </div>
        </section>

        {/* Values */}
        <section className="py-24 bg-[var(--bg-subtle)]">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="text-center mb-16">
              <h2 className="text-3xl sm:text-4xl font-bold text-[var(--text)] mb-4">What we stand for</h2>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
              {values.map((v) => (
                <div key={v.title} className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
                  <div className="mb-4 h-11 w-11 rounded-[var(--radius-lg)] bg-[var(--brand-600)]/10 flex items-center justify-center">
                    <v.icon className="h-5 w-5 text-[var(--brand-600)]" />
                  </div>
                  <h3 className="text-base font-semibold text-[var(--text)] mb-2">{v.title}</h3>
                  <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{v.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Contact */}
        <section className="py-24 bg-[var(--brand-600)]">
          <div className="mx-auto max-w-3xl px-4 text-center">
            <h2 className="text-3xl font-extrabold text-white mb-4">We&apos;re always an email away</h2>
            <p className="text-white/80 text-lg mb-8">
              Have questions, feedback, or just want to say hello? We&apos;d love to hear from you.
            </p>
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <Button size="lg" variant="secondary" asChild>
                <Link href="/signup">
                  Start creating free <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
              <Button size="lg" className="bg-white/10 text-white border border-white/20 hover:bg-white/20" asChild>
                <a href="mailto:support@fliki.ai">Contact us</a>
              </Button>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
