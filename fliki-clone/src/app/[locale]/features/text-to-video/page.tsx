import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Free Text to Video AI - Create Videos from Text | Fliki",
  description: "Turn scripts, blogs, URLs, and prompts into professional AI videos with voiceover and captions. 80+ languages, 2,000+ voices. Trusted by 50,000+ teams.",
};

export default function TextToVideoPage() {
  return (
    <FeaturePageLayout
      badge="Text to Video"
      title="Text to Video AI: Turn Any Text into Video"
      description="Turn scripts, blogs, URLs, and prompts into professional AI videos with voiceover and captions. 80+ languages, 2,000+ voices. Trusted by 50,000+ teams. Try free."
      features={[
        {
          title: "Text to Video AI editor",
          description: "No video editing skills? No problem. Fliki's text to video AI tool turns your scripts into scroll-stopping content with voice cloning, consistent characters, and customizable AI avatars.",
        },
        {
          title: "Multiple input formats",
          description: "Supported inputs include plain text, blog URLs, ChatGPT scripts, PowerPoint files, and plain prompts—convert anything into a video.",
        },
        {
          title: "2,000+ AI voices in 80+ languages",
          description: "Create videos for YouTube, Instagram, and TikTok just by entering your text script or even a prompt. Choose from thousands of ultra-realistic voices.",
        },
        {
          title: "Trusted by 50,000+ teams",
          description: "From solo creators to enterprise teams, Fliki's text-to-video AI is used by professionals around the world to produce high-quality content at scale.",
        },
        {
          title: "Auto captions & branding",
          description: "Automatically add captions and brand kit elements to every video. Keep your content consistent and on-brand with no manual work.",
        },
        {
          title: "Ready-made video templates",
          description: "Browse through a diverse range of high-quality video templates designed to simplify creation for any purpose—social, ads, education, and more.",
        },
      ]}
      faqs={[
        {
          q: "How to generate AI video from text?",
          a: "You can generate an AI video from text by entering your script into Fliki's platform and selecting your preferred settings such as voice, avatar, and visuals. The AI will then create a video automatically.",
        },
        {
          q: "What is the best text to video AI generator?",
          a: "Fliki is one of the best text-to-video AI tools, thanks to its realistic AI voices, customizable avatars, and script-to-video workflow that handles visuals automatically.",
        },
        {
          q: "How does text-to-video AI work?",
          a: "Text-to-video AI works by analyzing the text input and using machine learning algorithms to create a video that matches the content—including voiceover, visuals, and captions.",
        },
        {
          q: "Is there a limit on the length of text I can convert to a video?",
          a: "Yes, there is a character limit of 15,000 characters for the text you can convert to a video.",
        },
        {
          q: "Is Fliki free to use?",
          a: "Yes, you can get started with Fliki text to video for free. Check our pricing plans to see the free tier limits and available upgrades.",
        },
      ]}
    />
  );
}
