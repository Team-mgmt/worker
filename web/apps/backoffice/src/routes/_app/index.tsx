import { createFileRoute, Link } from "@tanstack/react-router";

import {
  BookOpenCheckIcon,
  DatabaseIcon,
  ImageUpIcon,
  SearchCheckIcon,
} from "lucide-react";

import { Breadcrumb } from "@/components/Breadcrumb";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const Route = createFileRoute("/_app/")({
  component: RouteComponent,
});

const ACTIONS = [
  {
    title: "서가 스캔 검수",
    description: "서가 이미지, 책등 BBox, OCR, DB 매칭, 오배열 판정을 한 화면에서 검수합니다.",
    to: "/shelf-ops",
    icon: ImageUpIcon,
    primary: true,
  },
  {
    title: "도서 데이터셋",
    description: "정보나루/도서관 장서 데이터를 기반으로 청구기호와 도서 후보를 매칭합니다.",
    to: "/books",
    icon: DatabaseIcon,
    primary: false,
  },
  {
    title: "매칭 검수",
    description: "청구기호, 제목, 저자 후보를 비교하고 수동 검수 대상을 확인합니다.",
    to: "/shelf-ops",
    icon: SearchCheckIcon,
    primary: false,
  },
];

function RouteComponent() {
  return (
    <>
      <Breadcrumb items={[]} showHomeLabel />
      <div className="mt-6">
        <div className="mb-5">
          <h2 className="text-xl font-extrabold">ShelfAlign Backoffice</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            도서관 서가 인식과 오배열 검수를 위한 운영 화면
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {ACTIONS.map((action) => {
            const Icon = action.icon;

            return (
              <Card
                key={action.title}
                className={
                  action.primary
                    ? "border-zinc-900 bg-zinc-950 text-white"
                    : undefined
                }
              >
                <Link to={action.to}>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Icon className="size-5" />
                      {action.title}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p
                      className={
                        action.primary
                          ? "text-sm text-zinc-300"
                          : "text-sm text-muted-foreground"
                      }
                    >
                      {action.description}
                    </p>
                  </CardContent>
                </Link>
              </Card>
            );
          })}
        </div>

        <Card className="mt-4">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BookOpenCheckIcon className="size-5" />
              운영 파이프라인
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-4">
              {["이미지 업로드", "책등 검출", "DB 매칭", "오배열 판정"].map(
                (step, index) => (
                  <div key={step} className="rounded-md border px-3 py-2">
                    <p className="text-xs text-muted-foreground">
                      Step {index + 1}
                    </p>
                    <p className="mt-1 font-semibold">{step}</p>
                  </div>
                ),
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
