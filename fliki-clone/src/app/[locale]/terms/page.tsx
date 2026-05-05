import { Link } from "@/i18n/navigation";
import { MarketingTopnav } from "@/components/marketing/topnav";
import { Footer } from "@/components/marketing/footer";

export const metadata = {
  title: "Terms and Conditions | Fliki",
  description: "Read Fliki's terms and conditions of service.",
};

const sections = [
  {
    title: "1. Acceptance of Terms",
    content: "By accessing or using Fliki, you agree to be bound by these Terms and Conditions and all applicable laws and regulations. If you do not agree with any of these terms, you are prohibited from using or accessing this site.",
  },
  {
    title: "2. Use License",
    content: "Permission is granted to temporarily use Fliki's services for personal, non-commercial transitory viewing only. This is the grant of a license, not a transfer of title, and under this license you may not: modify or copy the materials; use the materials for any commercial purpose; attempt to decompile or reverse engineer any software contained in Fliki; or remove any copyright or other proprietary notations from the materials.",
  },
  {
    title: "3. Content & AI Generated Output",
    content: "Fliki provides AI-powered tools to generate video and audio content. You are solely responsible for the content you create using our platform. You must not use Fliki to create content that is illegal, harmful, deceptive, or infringes on the rights of others.",
  },
  {
    title: "4. Voice Cloning",
    content: "When using Fliki's voice cloning feature, you must only clone voices with explicit consent from the voice owner. Cloning voices without consent, or using cloned voices to deceive or harm others, is strictly prohibited and may result in immediate account termination.",
  },
  {
    title: "5. Account Responsibility",
    content: "You are responsible for maintaining the confidentiality of your account and password and for restricting access to your computer. You agree to accept responsibility for all activities that occur under your account.",
  },
  {
    title: "6. Subscription & Billing",
    content: "Paid subscriptions are billed in advance on a monthly or annual basis and are non-refundable. Fliki reserves the right to modify pricing at any time with reasonable notice to subscribers.",
  },
  {
    title: "7. Termination",
    content: "Fliki may terminate or suspend your account and access to the service immediately, without prior notice or liability, for any reason, including if you breach these Terms.",
  },
  {
    title: "8. Limitation of Liability",
    content: "In no event shall Fliki, its directors, employees, or agents be liable for any indirect, incidental, special, consequential, or punitive damages, including loss of profits, data, use, or goodwill, arising out of your use or inability to use the service.",
  },
  {
    title: "9. Changes to Terms",
    content: "Fliki reserves the right to modify these terms at any time. We will notify users of significant changes via email or a prominent notice on our platform. Your continued use of the service after changes constitutes acceptance of the new terms.",
  },
  {
    title: "10. Contact",
    content: "If you have any questions about these Terms and Conditions, please contact us at support@fliki.ai.",
  },
];

export default function TermsPage() {
  return (
    <>
      <MarketingTopnav />
      <main>
        <section className="relative bg-[var(--bg)] pt-20 pb-24">
          <div className="mx-auto max-w-3xl px-4">
            <div className="mb-12">
              <h1 className="text-4xl font-extrabold text-[var(--text)] mb-4">Terms and Conditions</h1>
              <p className="text-[var(--text-secondary)]">Last updated: April 2026</p>
            </div>
            <div className="flex flex-col gap-10">
              {sections.map((s) => (
                <div key={s.title}>
                  <h2 className="text-xl font-semibold text-[var(--text)] mb-3">{s.title}</h2>
                  <p className="text-[var(--text-secondary)] leading-relaxed">{s.content}</p>
                </div>
              ))}
            </div>
            <div className="mt-16 pt-8 border-t border-[var(--border)] text-sm text-[var(--text-muted)]">
              <p>
                For questions about these terms, contact us at{" "}
                <a href="mailto:support@fliki.ai" className="text-[var(--brand-600)] hover:underline">
                  support@fliki.ai
                </a>{" "}
                or visit our{" "}
                <Link href="/privacy" className="text-[var(--brand-600)] hover:underline">
                  Privacy Policy
                </Link>
                .
              </p>
            </div>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
