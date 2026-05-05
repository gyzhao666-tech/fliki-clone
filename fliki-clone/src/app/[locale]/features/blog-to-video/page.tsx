import { FeaturePageLayout } from "@/components/marketing/feature-page";

export const metadata = {
  title: "Turn Blog to Video with AI in Minutes | Fliki",
  description: "Create engaging videos from blog articles with Fliki's Blog to Video feature. Enhance SEO and drive engagement by converting blog posts into videos with a few clicks.",
};

export default function BlogToVideoPage() {
  return (
    <FeaturePageLayout
      badge="Blog to Video"
      title="Turn Blog to Video with AI Instantly"
      description="Create engaging videos from blog articles with Fliki's Blog to Video feature. Enhance SEO and drive engagement by converting blog posts into videos with a few clicks."
      features={[
        {
          title: "Convert blog posts in minutes",
          description: "Convert your blog posts into captivating videos effortlessly with our Blog to Video tool. With script-based editing, high-quality AI voices, and a vast media library, create professional videos fast.",
        },
        {
          title: "Automatic script generation",
          description: "Simply provide the URL of your blog post, and Fliki automatically extracts the key points, generates a script, and builds a video around it.",
        },
        {
          title: "Multiple video lengths",
          description: "Choose from short (1 min), medium (2 min) and full-length videos when using the Blog to Video feature.",
        },
        {
          title: "Boost SEO with video content",
          description: "Enhance your SEO strategy by repurposing blog content into videos. Video content drives more engagement and improves search rankings.",
        },
        {
          title: "Export in MP4 with aspect ratios",
          description: "Export your blog-to-video in MP4 format with different aspect ratios—landscape, square, and portrait—for every platform.",
        },
        {
          title: "Ready-made video templates",
          description: "Browse through a diverse range of high-quality video templates designed to simplify the creation process for any purpose.",
        },
      ]}
      faqs={[
        {
          q: "How does the Blog to Video tool work?",
          a: "The Blog to Video feature simplifies the process of transforming your blog posts into engaging videos. Simply provide the URL of your blog post, and Fliki automatically extracts content and generates a video.",
        },
        {
          q: "What is the duration of the video created?",
          a: "You have the option to choose from short (1 min), medium (2 min) and full videos while creating using the blog to video feature.",
        },
        {
          q: "Can I export the videos I make with Fliki?",
          a: "Yes, Fliki allows you to export the videos you create. You can export your videos in MP4 format in different aspect ratios.",
        },
      ]}
    />
  );
}
