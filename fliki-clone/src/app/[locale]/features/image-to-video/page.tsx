import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Image to Video AI: Transform Your Photos into Stunning Videos | Fliki",
  description: "Create videos from your images with lifelike voiceovers, sound effects, music, animations, and more using our image to video AI. No video skills are required!",
};

export default function ImageToVideoPage() {
  return (
    <FeaturePageLayout
      badge="Image to Video"
      title="Image to Video AI: Transform Your Photos into Stunning Videos"
      description="Create videos from your images with lifelike voiceovers, sound effects, music, animations, and more using our image to video AI. No video skills are required!"
      features={[
        {
          title: "Transform photos into cinematic videos",
          description: "Give your visuals a stunningly cinematic dimension. Fliki's Image to Video AI captures your audience's attention with next-generation video creation from still images.",
        },
        {
          title: "Lifelike AI voiceovers",
          description: "Add natural-sounding AI voiceovers to your photo videos. Choose from 2,000+ voices in 80+ languages to narrate your images.",
        },
        {
          title: "Animations & motion effects",
          description: "Bring your photos to life with animations, transitions, and motion effects that transform static images into dynamic video content.",
        },
        {
          title: "Sound effects & background music",
          description: "Add the perfect audio ambiance with built-in sound effects and royalty-free background music—no external audio editing needed.",
        },
        {
          title: "Convert slideshows to videos",
          description: "Fliki's image to video AI allows you to easily convert slideshows into interactive, engaging videos for any platform.",
        },
        {
          title: "No video skills required",
          description: "Designed for creators of all skill levels. Simply upload your images, add a script or voiceover, and export a professional video.",
        },
      ]}
      faqs={[
        {
          q: "How can I convert my pictures into videos?",
          a: "With Fliki, converting pictures into videos is simple. Upload your images, choose your preferred AI voice, add a script or narration, and export the video.",
        },
        {
          q: "How do I add a voiceover to my photos using Fliki?",
          a: "Once you've uploaded your pictures, proceed to the script-based editing mode. Add your narration text and Fliki's AI will generate the voiceover automatically.",
        },
        {
          q: "What is the best free online image to video AI?",
          a: "Fliki stands out for its unique features including realistic voices, a vast media library, customizable animations, and an intuitive script-based editor.",
        },
        {
          q: "Can I convert slideshows into videos with Fliki's image to video AI?",
          a: "Absolutely! Fliki's innovative image to video AI features allow you to easily convert your slideshows into interactive, engaging video content.",
        },
        {
          q: "How does Fliki's image to video AI compare to other online video creators?",
          a: "Fliki offers a unique blend of professional quality and user-friendly design—with AI voiceovers, animations, and music all in one seamless workflow.",
        },
      ]}
    />
  );
}
