import { Link } from "@/i18n/navigation";
import { MarketingTopnav } from "@/components/marketing/topnav";
import { Footer } from "@/components/marketing/footer";

export const metadata = {
  title: "Privacy Policy | Fliki",
  description: "Learn how Fliki collects, uses, and protects your personal information.",
};

const sections = [
  {
    title: "1. Information We Collect",
    content: "We collect information you provide directly to us, such as when you create an account, subscribe to a plan, or contact support. This includes name, email address, payment information, and any content you create using our platform. We also automatically collect certain information about your device and how you interact with Fliki.",
  },
  {
    title: "2. How We Use Your Information",
    content: "We use the information we collect to provide, maintain, and improve our services; process transactions; send you technical notices and support messages; respond to your comments and questions; and send you marketing communications (with your consent). We also use data to monitor and analyze trends, usage, and activities in connection with our services.",
  },
  {
    title: "3. AI-Generated Content & Voice Data",
    content: "When you use Fliki's voice cloning feature, we process audio recordings to create voice models. These recordings and voice models are stored securely and used solely to provide the voice cloning service to you. We do not share your voice data with third parties except as required to provide the service.",
  },
  {
    title: "4. Sharing of Information",
    content: "We do not share your personal information with third parties except in the following circumstances: with your consent; to third-party vendors who provide services on our behalf; in response to a legal request; to protect the rights and safety of Fliki and our users; or in connection with a merger, sale, or acquisition of Fliki.",
  },
  {
    title: "5. Data Retention",
    content: "We retain your information for as long as your account is active or as needed to provide our services. You may request deletion of your account and associated data at any time by contacting support@fliki.ai.",
  },
  {
    title: "6. Security",
    content: "We take reasonable measures to protect your personal information from unauthorized access, use, alteration, or destruction. However, no internet transmission or electronic storage is ever fully secure, and we cannot guarantee absolute security.",
  },
  {
    title: "7. Cookies & Tracking",
    content: "We use cookies and similar tracking technologies to collect information about your browsing activities and to improve your experience on our platform. You can instruct your browser to refuse all cookies, but some features of Fliki may not function properly without them.",
  },
  {
    title: "8. Children's Privacy",
    content: "Fliki is not directed to children under the age of 13. We do not knowingly collect personal information from children under 13. If you believe we have inadvertently collected such information, please contact us immediately.",
  },
  {
    title: "9. Changes to This Policy",
    content: "We may update this Privacy Policy from time to time. We will notify you of any changes by posting the new policy on this page and updating the 'Last updated' date. Your continued use of Fliki after changes are posted constitutes your acceptance of the changes.",
  },
  {
    title: "10. Contact Us",
    content: "If you have any questions about this Privacy Policy or our privacy practices, please contact us at support@fliki.ai.",
  },
];

export default function PrivacyPage() {
  return (
    <>
      <MarketingTopnav />
      <main>
        <section className="relative bg-[var(--bg)] pt-20 pb-24">
          <div className="mx-auto max-w-3xl px-4">
            <div className="mb-12">
              <h1 className="text-4xl font-extrabold text-[var(--text)] mb-4">Privacy Policy</h1>
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
                For privacy-related questions, contact us at{" "}
                <a href="mailto:support@fliki.ai" className="text-[var(--brand-600)] hover:underline">
                  support@fliki.ai
                </a>{" "}
                or review our{" "}
                <Link href="/terms" className="text-[var(--brand-600)] hover:underline">
                  Terms and Conditions
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
