import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "AI Voice Cloning: Custom Voice Cloning in Minutes | Fliki",
  description: "Clone your voice with Fliki's AI voice cloning and generate natural-sounding voiceovers in seconds—fast and easy.",
};

export default function VoiceCloningPage() {
  return (
    <FeaturePageLayout
      badge="AI Voice Cloning"
      title="AI Voice Cloning: Custom Voice Cloning in Minutes"
      description="Clone your voice with Fliki's AI voice cloning and generate natural-sounding voiceovers in seconds—fast and easy."
      features={[
        {
          title: "Clone your voice with AI in minutes",
          description: "Experience the magic of AI voice cloning and create natural, high-quality voices that truly connect with your audience.",
        },
        {
          title: "2-minute voice recording",
          description: "Get a realistic clone of your voice by recording just a 2-minute sample. Save time on manual recordings with Fliki's AI-based Voice Cloning.",
        },
        {
          title: "2,000+ ultra-realistic voices",
          description: "Choose from over 2000 ultra realistic voices in 80+ languages for all your content needs—or use your own cloned voice.",
        },
        {
          title: "Commercial use included",
          description: "Use AI Voice Cloning for commercial purposes, provided that you have the required consent. Ideal for YouTube, podcasts, and branded content.",
        },
        {
          title: "Fast approval turnaround",
          description: "Cloned voices are typically approved within an hour, with a maximum wait time of 6 hours for full processing.",
        },
        {
          title: "Emotion-rich voice output",
          description: "Add a touch of emotion to your audio using voices marked with the emotion indicator. Go beyond flat narration.",
        },
      ]}
      faqs={[
        {
          q: "What is AI voice cloning?",
          a: "AI voice cloning is an advanced technology that utilizes artificial intelligence to replicate and generate custom voices based on a short audio sample recording.",
        },
        {
          q: "Whose voice can I clone?",
          a: "You can clone the voice of a person who has provided explicit consent for their voice to be used for cloning purposes. It is prohibited to clone voices without consent.",
        },
        {
          q: "How does AI Voice cloning work?",
          a: "AI voice cloning works by analyzing and understanding the unique vocal characteristics of a chosen voice model. It then uses this data to generate new speech that sounds like the original speaker.",
        },
        {
          q: "Can I use AI Voice Cloning for commercial purposes?",
          a: "Certainly, you can use AI Voice Cloning for commercial purposes, provided that you have the user's consent and the voice is used in accordance with our terms of service.",
        },
        {
          q: "How long does it take to get the Cloned Voice approved?",
          a: "The cloned voices typically take up to 6 hours for approval, but in most cases, they are approved within an hour.",
        },
      ]}
    />
  );
}
