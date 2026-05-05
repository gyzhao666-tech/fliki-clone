import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "AI Avatar Generator: Create Avatar Videos with AI | Fliki",
  description: "Transform your online presence with AI Avatar Generator. Craft AI video avatars with realistic expressions, diverse styles, custom voice cloning & more.",
};

export default function AiAvatarPage() {
  return (
    <FeaturePageLayout
      badge="AI Avatar"
      title="AI Avatar Generator: Create AI Videos with Avatars"
      description="Transform your online presence with AI Avatar Generator. Craft AI video avatars with realistic expressions, diverse styles, custom voice cloning & more."
      features={[
        {
          title: "70+ lifelike AI avatars",
          description: "Choose from a wide range of 70+ avatars to represent your narration. Capture the undivided attention of your audience with high-quality AI voices in multiple languages.",
        },
        {
          title: "Engage your audience without going on camera",
          description: "Unleash your creativity with our lifelike AI Avatars. Revolutionize your video content by crafting lifelike narratives better and faster—without needing to film yourself.",
        },
        {
          title: "Custom AI avatars for enterprise",
          description: "Enterprise users can create ultra-realistic custom AI avatars tailored to their brand identity, complete with voice cloning and branded visuals.",
        },
        {
          title: "Multilingual avatar support",
          description: "Fliki's AI Avatars are multilingual, capable of speaking various languages fluently—supporting voices in over 80 different languages.",
        },
        {
          title: "Fully customizable appearance & voice",
          description: "Personalize your AI Avatar's appearance and voice to create a perfect representation of your brand or persona in every video.",
        },
        {
          title: "Works in 4 simple steps",
          description: "Write your script, select an avatar and voice, preview your video, then export in HD. No video production skills needed.",
        },
      ]}
      faqs={[
        {
          q: "What is an AI avatar video generator?",
          a: "An AI avatar video generator, like the one offered by Fliki, creates videos featuring virtual characters or avatars. These avatars read your script and deliver it with realistic gestures and facial expressions.",
        },
        {
          q: "What are AI Avatars in video content creation?",
          a: "AI Avatars are advanced digital characters powered by artificial intelligence. They can read scripts, mimic human-like gestures, and speak in multiple languages with realistic voices.",
        },
        {
          q: "How can I create an AI Avatar using text-to-video tool?",
          a: "Fliki simplifies the process of creating AI Avatars. You just need to write or paste your script into the tool, choose the avatar, select a voice, and export your video.",
        },
        {
          q: "In which languages can the AI Avatars speak?",
          a: "Fliki's AI Avatars are multilingual, capable of speaking various languages fluently. Supporting voices in over 80 different languages.",
        },
        {
          q: "Can I customize my AI Avatar's appearance and voice in the video?",
          a: "Absolutely! Fliki provides several options for customizing your AI Avatar's appearance and voice, helping you to create a perfect representation of your brand or persona.",
        },
      ]}
    />
  );
}
