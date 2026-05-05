import { Link } from "@/i18n/navigation";
import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function AccountAffiliatePage() {
  return (
    <div className="space-y-6">
      <div className="rounded-[var(--radius-xl)] border border-[var(--brand-600)]/20 bg-gradient-to-r from-[var(--brand-600)]/6 to-transparent p-5">
        <h2 className="font-bold text-base text-[var(--text)] mb-1">Welcome to our Affiliate Program! 🤝</h2>
        <p className="text-sm text-[var(--text-secondary)]">
          Refer your friends, followers, and customers to earn <strong className="text-[var(--brand-600)]">30% recurring commissions for a lifetime!</strong>
        </p>
      </div>

      <section className="rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--surface)] p-6">
        <h2 className="text-sm font-semibold text-[var(--text)] mb-3">Your rewards for referring new customers</h2>
        <div className="flex items-center gap-3 p-4 rounded-[var(--radius-lg)] bg-emerald-50 border border-emerald-200 mb-6">
          <span className="text-2xl">💰</span>
          <p className="text-sm text-emerald-800 font-medium">You get <strong>30% recurring commissions for lifetime</strong> for each referred customer.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button className="gap-1.5">
            Join the program <ExternalLink className="h-3.5 w-3.5" />
          </Button>
          <Button variant="outline" className="gap-1.5">
            Affiliate dashboard <ExternalLink className="h-3.5 w-3.5" />
          </Button>
        </div>
      </section>

      <p className="text-xs text-[var(--text-muted)]">
        Questions? Reach us at{" "}
        <a href="mailto:support@fliki.ai" className="text-[var(--brand-600)] hover:underline">support@fliki.ai</a>
      </p>
    </div>
  );
}
