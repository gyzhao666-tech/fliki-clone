/** 是否为项目剪辑页（非 export 子页）：用于沉浸式加宽布局 */
export function isProjectWorkspacePath(pathname: string): boolean {
  const parts = pathname.replace(/\/$/, "").split("/").filter(Boolean);
  if (parts.length === 0) return false;
  let i = 0;
  if (parts[0] === "en" || parts[0] === "zh") {
    i = 1;
  }
  return (
    parts[i] === "app" &&
    parts[i + 1] === "project" &&
    parts.length === i + 3
  );
}
