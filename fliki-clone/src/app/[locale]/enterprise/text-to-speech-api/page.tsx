import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Text to Speech API with Ultra-Realistic AI Voices | Fliki",
  description: "Integrate natural AI voices with our text-to-speech API. Choose from 2,500+ voices in 80+ languages and 100+ accents to engage your global audience.",
};

export default function TtsApiPage() {
  return (
    <FeaturePageLayout
      badge="TTS API"
      title="Text to Speech API with Ultra-Realistic AI Voices"
      description="Integrate natural AI voices with our text-to-speech API. Choose from 2,500+ voices in 80+ languages and 100+ accents to engage your global audience."
      ctaLabel="Get API access"
      ctaHref="/signup"
      features={[
        {
          title: "Enhance your apps with natural-sounding speech",
          description: "Integrate Fliki's text-to-speech API to deliver an immersive and engaging user experience. Access a vast library of ultra-realistic AI voices to customize voiceovers for any use case.",
        },
        {
          title: "2,500+ voices in 80+ languages",
          description: "Effortlessly integrate natural-sounding AI voices into your applications. Choose from over 2,500 voices in 80+ languages and 100+ accents to captivate your global audience.",
        },
        {
          title: "Language-agnostic REST API",
          description: "Fliki's text-to-speech API is language-agnostic and can be integrated using any programming language that supports HTTP requests—Python, Node.js, Java, Go, and more.",
        },
        {
          title: "Simple 4-step integration",
          description: "Get started with the API in minutes. Authenticate, choose a voice, send your text, and receive audio output. Full documentation and SDKs are provided.",
        },
        {
          title: "Trusted by 50,000+ companies",
          description: "From startups to large enterprises, developers around the world rely on Fliki's TTS API to power their applications with natural-sounding speech.",
        },
        {
          title: "Scalable for any workload",
          description: "Built for production-grade workloads. Fliki's API scales seamlessly from dozens to millions of API calls, with SLA guarantees for enterprise customers.",
        },
      ]}
      faqs={[
        {
          q: "Can I use Fliki AI Video generator for free?",
          a: "Yes, Fliki offers a tier that allows users to explore text to voice and text to video features without any cost. API access is available on paid plans.",
        },
        {
          q: "How does Fliki differ from other TTS APIs in the market?",
          a: "Fliki stands out because it combines text to video AI and text to speech AI capabilities, giving you an all-in-one platform rather than separate point solutions.",
        },
        {
          q: "Which languages are supported?",
          a: "Fliki supports over 80 languages in over 100 dialects. The AI speech generator offers 1,300+ ultra-realistic voices for global audience reach.",
        },
        {
          q: "What programming languages are supported for API integration?",
          a: "Fliki's text-to-speech API is language-agnostic and can be integrated using any programming language that supports HTTP requests.",
        },
        {
          q: "Do I need any special software or equipment?",
          a: "No. Fliki is fully web-based and the API can be called from any environment that supports HTTP requests. No additional software is required.",
        },
      ]}
    />
  );
}
