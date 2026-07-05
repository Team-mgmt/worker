import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { CheckIcon, ClockIcon, Trash2Icon } from "lucide-react";

import { cn } from "@/lib/utils";

import { queries } from "@/queries";
import { formatBytes } from "@/routes/_app/documents/-lib/format";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface VersionHistorySidebarProps {
  slug: string;
  activeVersionId: string | undefined;
}

export function VersionHistorySidebar({
  slug,
  activeVersionId,
}: VersionHistorySidebarProps) {
  const { data: versions } = useSuspenseQuery(queries.document.versions(slug));

  const isLatestActive = !activeVersionId;

  return (
    <Card className="lg:sticky lg:top-4 lg:self-start lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClockIcon size={16} />
          버전 기록
          <span className="text-xs font-normal text-muted-foreground">
            ({versions.length})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {versions.map((version) => {
          const isActive = version.isLatest
            ? isLatestActive
            : activeVersionId === version.versionId;

          return (
            <Link
              key={version.versionId}
              to="/documents/$slug"
              params={{ slug }}
              search={version.isLatest ? {} : { versionId: version.versionId }}
              className={cn(
                "block rounded-md border p-2 text-xs transition hover:bg-accent",
                isActive && "border-primary bg-accent",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1">
                  {version.isLatest && (
                    <Badge variant="default" className="h-5 px-1.5 text-[10px]">
                      최신
                    </Badge>
                  )}
                  {version.isDeleteMarker && (
                    <Badge
                      variant="destructive"
                      className="h-5 px-1.5 text-[10px]"
                    >
                      <Trash2Icon size={10} className="mr-0.5" />
                      삭제
                    </Badge>
                  )}
                  {isActive && <CheckIcon size={12} className="text-primary" />}
                </div>
                <span className="text-muted-foreground">
                  {formatBytes(version.size)}
                </span>
              </div>
              <div className="mt-1 text-muted-foreground">
                {version.lastModified
                  ? new Date(version.lastModified).toLocaleString()
                  : "-"}
              </div>
              <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground/70">
                {version.versionId}
              </div>
            </Link>
          );
        })}
      </CardContent>
    </Card>
  );
}
