import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Best PPT to Video Converter with AI Voiceover | Fliki",
  description: "Convert PowerPoint to professional video with AI voiceover and captions. Upload PPT or PPTX, choose from 2,000+ voices in 80+ languages. Free online, no software needed.",
};

export default function PptToVideoPage() {
  return (
    <FeaturePageLayout
      badge="PPT to Video"
      title="Convert PowerPoint to Video with AI Voiceover"
      description="Convert PowerPoint to professional video with AI voiceover and captions. Upload PPT or PPTX, choose from 2,000+ voices in 80+ languages. Free online, no software needed."
      features={[
        {
          title: "Seamless PPT to Video conversion",
          description: "Tired of spending hours converting PowerPoint presentations into engaging videos? Fliki's PPT to Video feature auto-generates scripts and adds AI avatars, lifelike voiceovers, and music in seconds.",
        },
        {
          title: "AI voiceover in 80+ languages",
          description: "Choose from 2,000+ AI voices in 80+ languages. Your presentation slides are automatically narrated in your chosen voice and language.",
        },
        {
          title: "Auto-captions included",
          description: "Every video created from your PPT includes auto-generated captions for accessibility and engagement—no extra steps required.",
        },
        {
          title: "Add your own voiceover",
          description: "While Fliki offers a wide range of AI voices, you can also add your own recorded voiceover to the converted video for a personal touch.",
        },
        {
          title: "Preserve original presentation quality",
          description: "Our PPT to Video feature preserves the quality of your original presentation slides while adding motion, voice, and music.",
        },
        {
          title: "No software download needed",
          description: "Fliki is fully web-based. Upload your PPT or PPTX file directly in the browser and start converting—no installation required.",
        },
      ]}
      faqs={[
        {
          q: "How does the PPT to Video feature work?",
          a: "The PPT to Video feature uses advanced AI technology to automatically convert your PowerPoint presentations into captivating videos. Upload your file, select a voice, and Fliki handles the rest.",
        },
        {
          q: "Can I customize the appearance and layout of the videos created with PPT to Video?",
          a: "Absolutely! Fliki offers a variety of customization options, allowing you to personalize the appearance and layout of your converted videos.",
        },
        {
          q: "Will the converted videos maintain the quality of my original presentation?",
          a: "Yes, definitely! Our PPT to Video feature is designed to maintain the quality of your original presentation throughout the conversion process.",
        },
        {
          q: "Can I add my own voiceover to the videos created with PPT to Video?",
          a: "Yes! While our platform offers a wide range of AI voices, we also provide the option to add your own recorded voiceover to the converted video.",
        },
        {
          q: "Do I need any other software to use Fliki's PPT to Video?",
          a: "No. Fliki is fully web-based and works entirely in your browser. Just upload your PPT or PPTX file and start converting.",
        },
      ]}
    />
  );
}
