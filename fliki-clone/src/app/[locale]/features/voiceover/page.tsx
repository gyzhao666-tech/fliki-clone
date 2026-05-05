import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Free AI Voice Generator - 2,000+ Voices, 80+ Languages | Fliki",
  description: "Generate ultra-realistic AI voiceovers in 80+ languages with 2,000+ voices. Perfect for videos, podcasts, e-learning, and ads. Preview voices free. No mic needed.",
};

export default function VoiceoverPage() {
  return (
    <FeaturePageLayout
      badge="AI Voiceover"
      title="AI Voice Generator: 2,000+ Realistic Voices in 80+ Languages"
      description="Generate ultra-realistic AI voiceovers in 80+ languages with 2,000+ voices. Perfect for videos, podcasts, e-learning, and ads. Preview voices free. No mic needed."
      features={[
        {
          title: "2,000+ ultra-realistic voices",
          description: "Transform your text into lifelike speech. Choose from over 2000 ultra realistic voices in 80+ languages, saving time and cost on voiceover artists.",
        },
        {
          title: "Create AI voiceover speech in seconds",
          description: "Craft captivating content with ease using our cutting-edge AI voice generator. Our AI-powered voices are high-quality, incredibly lifelike, and available in dozens of accents.",
        },
        {
          title: "Emotion-aware voice generation",
          description: "Add a touch of emotion to your voiceovers using voices marked with the ⚡ icon. Go beyond flat narration with expressive, context-aware AI speech.",
        },
        {
          title: "Up to 30 minutes of audio",
          description: "Create voiceovers up to 30 minutes in length with the Premium subscription plan. Ideal for e-learning, long-form podcasts, and corporate training.",
        },
        {
          title: "Voice customization options",
          description: "Customize pitch, speed, and style to suit your needs. Choose between conversational, professional, and expressive voice styles.",
        },
        {
          title: "No microphone required",
          description: "Skip the recording setup entirely. Just type your script and let Fliki generate studio-quality voiceovers instantly—no microphone or editing experience needed.",
        },
      ]}
      faqs={[
        {
          q: "What is the maximum duration of the audio created?",
          a: "In Fliki you can create voiceovers up to 30 minutes with the Premium subscription plan.",
        },
        {
          q: "Can I customize the voice used in the Voiceover feature?",
          a: "Absolutely! Fliki offers a range of high-quality AI voices that can be customized to suit your needs. You can choose between different styles, pitches, and speeds.",
        },
        {
          q: "Does Fliki support emotions?",
          a: "Yes, Fliki supports emotions! With certain voices marked with the ⚡ icon, you can add a touch of emotion to your videos—making them more engaging.",
        },
        {
          q: "Is the script-based editing system easy to use?",
          a: "Yes, our script-based editing system is designed to be user-friendly and intuitive. Simply input your text into the script editor and the AI handles the rest.",
        },
        {
          q: "What is an AI voice generator?",
          a: "An AI voice generator utilizes artificial intelligence technology to create lifelike speech from written text, offering a fast, cost-effective alternative to human voiceover artists.",
        },
      ]}
    />
  );
}
