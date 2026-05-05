import { Link } from "@/i18n/navigation";
import { ArrowRight, Mic, Film, Sparkles, Users, Globe, Image, FileText, Video } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MarketingTopnav } from "@/components/marketing/topnav";
import { Footer } from "@/components/marketing/footer";

const features = [
  {
    icon: Film,
    title: "Text to Video",
    description: "Transform your text into videos easily with AI text-to-video generator. Create videos for YouTube, Instagram and TikTok just by entering your script or a prompt.",
    href: "/features/text-to-video",
  },
  {
    icon: Mic,
    title: "AI Voiceover",
    description: "Transforming text into engaging narrations with AI voices. Choose from over 2000 ultra realistic voices in 80+ languages for all your content needs.",
    href: "/features/voiceover",
  },
  {
    icon: Sparkles,
    title: "Idea to Video",
    description: "Create videos for social media in seconds by entering your prompt and let AI turn it into stunning videos with AI voices.",
    href: "/features/idea-to-video",
  },
  {
    icon: Users,
    title: "AI Avatar",
    description: "Unleash your creativity with our lifelike AI Avatars. Revolutionize your video content by crafting lifelike narratives better and faster!",
    href: "/features/ai-avatar",
  },
  {
    icon: Globe,
    title: "Text to Speech",
    description: "Experience the next generation of text to speech technology with our ultra-realistic AI voices. Choose from over 2000 voices in 80+ languages and 100+ accents.",
    href: "/features/text-to-speech",
  },
  {
    icon: Video,
    title: "Voice Cloning",
    description: "Get a realistic clone of your voice by recording a 2-min sample. Save time on manual recordings with Fliki's AI-based Voice Cloning.",
    href: "/features/voice-cloning",
  },
  {
    icon: FileText,
    title: "Blog to Video",
    description: "Create engaging videos from blog articles with Fliki's Blog to Video feature. Enhance SEO and drive engagement by converting blog posts into videos.",
    href: "/features/blog-to-video",
  },
  {
    icon: Image,
    title: "Image to Video",
    description: "Create videos from your images with lifelike voiceovers, sound effects, music, animations, and more. No video skills required!",
    href: "/features/image-to-video",
  },
  {
    icon: FileText,
    title: "PPT to Video",
    description: "Repurpose your PowerPoint by converting it to video. Just upload your PPT, and Fliki auto-generates scripts and adds AI avatars and lifelike voiceovers.",
    href: "/features/ppt-to-video",
  },
];

export const metadata = {
  title: "Features - Fliki",
  description: "Check out all the text-to-video and text-to-speech features offered by Fliki.",
};

export default function FeaturesPage() {
  return (
    <>
      <MarketingTopnav />
      <main>
        {/* Hero */}
        <section className="relative overflow-hidden bg-[var(--bg)] pt-20 pb-24 text-center">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-[400px] bg-gradient-to-b from-[var(--brand-600)]/8 via-transparent to-transparent" />
          <div className="relative mx-auto max-w-5xl px-4">
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight text-[var(--text)] leading-[1.1] mb-6">
              All <span className="text-[var(--brand-600)]">Features</span>
            </h1>
            <p className="mx-auto max-w-2xl text-lg text-[var(--text-secondary)] mb-10">
              Check out all the text-to-video and text-to-speech features offered by Fliki.
            </p>
            <Button size="lg" asChild>
              <Link href="/signup">
                Get started free <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>

        {/* Features grid */}
        <section className="py-24 bg-[var(--bg-subtle)]">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
              {features.map((f) => (
                <Link
                  key={f.title}
                  href={f.href}
                  className="group rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6 hover:shadow-md hover:border-[var(--brand-600)]/40 transition-all"
                >
                  <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-[var(--radius-lg)] bg-[var(--brand-600)]/10 group-hover:bg-[var(--brand-600)]/20 transition-colors">
                    <f.icon className="h-5 w-5 text-[var(--brand-600)]" />
                  </div>
                  <h3 className="text-base font-semibold text-[var(--text)] mb-2 flex items-center gap-2">
                    {f.title}
                    <ArrowRight className="h-3.5 w-3.5 text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity" />
                  </h3>
                  <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{f.description}</p>
                </Link>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="py-24 bg-[var(--brand-600)]">
          <div className="mx-auto max-w-3xl px-4 text-center">
            <h2 className="text-3xl sm:text-4xl font-extrabold text-white mb-4">
              Start creating for free
            </h2>
            <p className="text-lg mb-8 text-white/80">
              No credit card required. Trusted by 50,000+ teams worldwide.
            </p>
            <Button size="lg" variant="secondary" asChild>
              <Link href="/signup">
                Get started free <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
