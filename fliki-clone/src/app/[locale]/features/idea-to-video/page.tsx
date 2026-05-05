import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Idea to Video AI - Turn Prompts into Videos Free | Fliki",
  description: "Prompt in your idea and select video length, Fliki auto-generates scripts, adds rich visuals, lifelike voiceovers and music in seconds.",
};

export default function IdeaToVideoPage() {
  return (
    <FeaturePageLayout
      badge="Idea to Video"
      title="Idea to Video: Create Videos from Prompt"
      description="Prompt in your idea and select video length, Fliki auto-generates scripts, adds rich visuals, lifelike voiceovers and music in seconds. Try Fliki Prompt to Video now."
      features={[
        {
          title: "Idea to Video in seconds",
          description: "Are you looking to generate videos for social media with just a prompt? Enter a few words to describe your video idea, style, or tone, and Fliki creates it within seconds.",
        },
        {
          title: "Choose your video length",
          description: "Choose from short (1 min), medium (2 min), and long (5 min) videos. Fliki adapts the script and pacing automatically to your selected length.",
        },
        {
          title: "Auto-generated script & visuals",
          description: "Fliki accepts ideas in the form of prompts along with the tone of the video, generates a script, and auto-selects visuals and voiceovers for you.",
        },
        {
          title: "Social media ready output",
          description: "Create videos for YouTube, Instagram, and TikTok just by entering your prompt. Let AI turn your ideas into stunning videos with AI voices.",
        },
        {
          title: "Export in multiple formats",
          description: "Export your videos in MP4 format. Aspect ratios are available for landscape, portrait, and square—perfect for every platform.",
        },
        {
          title: "Ready-made video templates",
          description: "Browse through a diverse range of high-quality video templates designed to simplify creation for any purpose.",
        },
      ]}
      faqs={[
        {
          q: "How does idea to video work?",
          a: "Fliki accepts ideas in the form of prompts along with the tone of the video and generates a script, then auto-selects visuals and voiceovers to produce a complete video.",
        },
        {
          q: "What is the duration of the video created?",
          a: "You have the option to choose from short (1 min), medium (2 min) and long (5 min) videos while creating the video.",
        },
        {
          q: "What type of videos are best suited for idea to video?",
          a: "Fliki's text to video AI tool allows you to generate a wide range of videos to suit various purposes including explainer videos, social media content, product demos, and more.",
        },
        {
          q: "Can I export the videos I make with Fliki?",
          a: "Yes, Fliki allows you to export the videos you create. You can export your videos in formats like MP4.",
        },
        {
          q: "Do I need any other software or technical tools to use Fliki?",
          a: "No additional software is needed. Fliki is fully web-based and works in your browser. Just enter your idea and let the AI handle the rest.",
        },
      ]}
    />
  );
}
