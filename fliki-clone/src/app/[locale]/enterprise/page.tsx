import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Enterprise AI Video Creation at Scale | Fliki",
  description: "Unlock the power of Fliki for your enterprise. Effortlessly create high-quality videos at scale, perfect for teams in any industry—all from your browser or via the API.",
};

export default function EnterprisePage() {
  return (
    <FeaturePageLayout
      badge="Enterprise"
      title="Bring your team together and create content at scale"
      description="Unlock the power of Fliki for your enterprise: Effortlessly create high-quality videos at scale, perfect for teams in any industry — all from your browser or via the API."
      ctaLabel="Contact sales"
      ctaHref="/signup"
      features={[
        {
          title: "AI video creation at scale",
          description: "Harness the power of AI-driven video creation to captivate your audience like never before. Increase engagement with professional-grade social media videos tailored to drive sales.",
        },
        {
          title: "Team collaboration tools",
          description: "Bring your entire team together with shared workspaces, brand kits, and collaborative video projects. Manage permissions and content at scale.",
        },
        {
          title: "Training & internal communication",
          description: "Make training sessions twice as impactful with Fliki's intuitive AI technology. Say goodbye to mundane training materials with AI-generated video content.",
        },
        {
          title: "Multilingual global reach",
          description: "Break free from geographical constraints and connect your entire workforce with Fliki's multi-lingual AI voices in 80+ languages.",
        },
        {
          title: "Text-to-Speech API integration",
          description: "Integrate Fliki's ultra-realistic AI voices into your applications and workflows. Choose from 2,500+ voices in 80+ languages and 100+ accents.",
        },
        {
          title: "On-brand video templates",
          description: "Browse through a diverse range of high-quality video templates and lock brand colors, fonts, and logos across your entire team's output.",
        },
      ]}
      faqs={[
        {
          q: "Can I use Fliki AI Video generator for free?",
          a: "Yes, Fliki offers a tier that allows users to explore text to voice and text to video features without any cost. You can upgrade to a paid plan for enterprise-level features.",
        },
        {
          q: "How does Fliki differ from other text-to-video and text-to-speech tools in the market?",
          a: "Fliki stands out because it combines text to video AI and text to speech AI capabilities in one platform, making it the ideal solution for enterprise teams.",
        },
        {
          q: "Which languages are supported?",
          a: "Fliki supports over 80 languages in over 100 dialects. The AI speech generator offers 1,300+ ultra-realistic voices, ensuring you can reach your global audience.",
        },
        {
          q: "Do I need any special software or equipment?",
          a: "No. Fliki is fully web-based. You only need a device with internet access and a modern browser to get started.",
        },
        {
          q: "Does Fliki support Voice Cloning?",
          a: "Fliki supports voice cloning, allowing you to replicate your own voice or create unique voices for different characters across your enterprise content.",
        },
      ]}
    />
  );
}
