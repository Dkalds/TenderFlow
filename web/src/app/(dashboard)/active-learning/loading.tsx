import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";

export default function ActiveLearningLoading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-80" />
      </div>
      <Card><CardContent className="py-4"><Skeleton className="h-12 w-full" /></CardContent></Card>
      <div className="grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i}><CardContent className="pt-6"><Skeleton className="h-16 w-full" /></CardContent></Card>
        ))}
      </div>
      <Card><CardContent className="pt-6"><Skeleton className="h-24 w-full" /></CardContent></Card>
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i}><CardContent className="pt-6"><Skeleton className="h-32 w-full" /></CardContent></Card>
        ))}
      </div>
    </div>
  );
}
