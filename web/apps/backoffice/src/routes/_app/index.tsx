import { createFileRoute, Link } from "@tanstack/react-router";

import {
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
  },
  {
    title: "도서 데이터셋",
    description: "정보나루/도서관 장서 데이터를 기반으로 청구기호와 도서 후보를 매칭합니다.",
    to: "/books",
    icon: DatabaseIcon,
  },
  {
    title: "매칭 검수",
    description: "청구기호, 제목, 저자 후보를 비교하고 수동 검수 대상을 확인합니다.",
    to: "/shelf-ops",
    icon: SearchCheckIcon,
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

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
          {ACTIONS.map((action) => {
            const Icon = action.icon;

            return (
              <Card key={action.title} className="min-h-56 transition-colors hover:border-zinc-500">
                <Link to={action.to} className="flex min-h-56 flex-col">
                  <CardHeader className="px-6 pt-7">
                    <div className="mb-5 flex size-12 items-center justify-center bg-zinc-950 text-white">
                      <Icon className="size-6" />
                    </div>
                    <CardTitle className="text-lg">
                      {action.title}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="px-6 pb-7">
                    <p className="text-sm leading-6 text-muted-foreground">
                      {action.description}
                    </p>
                  </CardContent>
                </Link>
              </Card>
            );
          })}
        </div>

        <footer className="mt-16 border-t py-8 text-xs leading-6 text-muted-foreground">
          <nav className="mb-3 flex flex-wrap gap-x-4 font-semibold text-zinc-700">
            <a href="#about">ABOUT</a>
            <a href="#contact">CONTACT</a>
            <a href="#terms">TERMS &amp; CONDITIONS</a>
            <a href="#privacy">PRIVACY POLICY</a>
          </nav>
          <p>ⓒ ShelfAlign, All rights reserved</p>
          <p>등록번호 000-00-00000 | 상호 ShelfAlign | 대표자명 임준수</p>
          <p>
            연락처 02-0000-0000 | 사업장주소 서울특별시 종로구 홍지문2길 20 상명대학교 학생회관
          </p>
        </footer>
      </div>
    </>
  );
}
