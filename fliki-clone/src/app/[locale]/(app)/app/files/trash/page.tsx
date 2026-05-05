import { Link } from "@/i18n/navigation";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function FilesTrashPage() {
  return (
    <div className="p-6 max-w-3xl mx-auto flex flex-col items-center justify-center min-h-[50vh] text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-[var(--radius-2xl)] bg-[var(--bg-muted)] mb-4">
        <Trash2 className="h-8 w-8 text-[var(--text-muted)]" />
      </div>
      <h1 className="text-xl font-bold text-[var(--text)] mb-2">Trash</h1>
      <p className="text-sm text-[var(--text-secondary)] mb-8 max-w-md">
        Deleted files stay here for 30 days before they are removed permanently.
      </p>
      <p className="text-sm text-[var(--text-muted)] mb-6">Trash is empty.</p>
      <Button variant="outline" asChild>
        <Link href="/app/files">Back to Files</Link>
      </Button>
    </div>
  );
}
