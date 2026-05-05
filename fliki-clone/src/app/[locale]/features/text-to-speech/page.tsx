import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Free Text to Speech Online with Ultra-Realistic AI Voices | Fliki",
  description: "Experience the next generation of text to speech technology with our ultra-realistic AI voices. Choose from over 2000 voices in 80+ languages and 100+ accents.",
};

export default function TextToSpeechPage() {
  return (
    <FeaturePageLayout
      badge="Text to Speech"
      title="Free Text to Speech Online with Ultra-Realistic AI Voices"
      description="Experience the next generation of text to speech technology with our ultra-realistic AI voices. Choose from over 2000 voices in 80+ languages and 100+ accents, perfect for creating YouTube and podcast content."
      features={[
        {
          title: "Try free text to speech",
          description: "Transform your text into lifelike speech. Choose from over 2000 ultra realistic voices in 80+ languages, saving time and cost on voiceover artists.",
        },
        {
          title: "Studio-quality voice overs in minutes",
          description: "Experience the power of AI voices through our free text-to-speech tool. Capture your audience's attention with high-quality, natural-sounding AI voices with a diverse selection available.",
        },
        {
          title: "100+ accents supported",
          description: "Beyond 80+ languages, Fliki supports 100+ regional accents—so your content sounds native to every audience, everywhere in the world.",
        },
        {
          title: "Perfect for YouTube & podcasts",
          description: "Create compelling narration for YouTube videos, podcasts, e-learning courses, and audiobooks—all without a recording studio.",
        },
        {
          title: "Emotion-aware speech",
          description: "Add expressive emotion to your AI-generated speech. Certain voices support emotional tones to make your content more engaging and human.",
        },
        {
          title: "Fair usage free plan",
          description: "The text to speech tool is free to use within our Fair Usage Policy rate limits. Upgrade to a paid plan for unlimited generation.",
        },
      ]}
      faqs={[
        {
          q: "What is the maximum duration of the audio created?",
          a: "In Fliki you can create voiceovers up to 30 minutes with the Premium subscription plan.",
        },
        {
          q: "Does Fliki support emotions?",
          a: "Yes, Fliki supports emotions! With certain voices marked with the ⚡ icon, you can add a touch of emotion to your videos and audio.",
        },
        {
          q: "What is text-to-speech (TTS) technology?",
          a: "Text-to-speech (TTS) technology converts written text into spoken language, allowing users to listen to the content instead of reading it. Fliki uses advanced AI to make this sound natural.",
        },
        {
          q: "Is the text to speech free to use?",
          a: "Yes, Fliki text to speech is free to use. However, we do have a Fair Usage Policy (FUP) rate limit in place to ensure fair access for all users.",
        },
        {
          q: "What languages does the text-to-speech service support?",
          a: "The Fliki text-to-speech service supports 80+ languages and 100+ dialects.",
        },
      ]}
    />
  );
}
