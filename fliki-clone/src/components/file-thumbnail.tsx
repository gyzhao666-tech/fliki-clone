"use client";

import { cn } from "@/lib/utils";

function isProbablyVideoUrl(url: string): boolean {
  const path = url.split("?")[0].toLowerCase();
  return /\.(mp4|webm|mov|m4v|ogv|ogg)(\s*)$/.test(path);
}

/** 列表/卡片用：视频用首帧（metadata），图片用 img */
export function FileThumbnail({
  src,
  alt,
  className,
}: {
  src: string;
  alt: string;
  className?: string;
}) {
  if (isProbablyVideoUrl(src)) {
    return (
      <video
        src={src}
        preload="metadata"
        muted
        playsInline
        aria-label={alt}
        className={cn(className, "pointer-events-none")}
      />
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} className={className} />
  );
}
