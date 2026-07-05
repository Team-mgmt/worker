import type { JSX } from "react";

import type { LinkProps } from "@tanstack/react-router";
import { Link } from "@tanstack/react-router";

import { HomeIcon } from "lucide-react";

import {
  Breadcrumb as ShadcnBreadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";

type BreadcrumbTextItem = {
  type: "text";
  label: string;
  className?: string;
};

type BreadcrumbLinkItem = {
  type: "link";
  label: string;
  className?: string;
} & Pick<LinkProps, "to" | "params">;

type BreadcrumbComponentItem = {
  type: "component";
  component: JSX.Element;
};

type Props = {
  items: (BreadcrumbTextItem | BreadcrumbLinkItem | BreadcrumbComponentItem)[];
  showHomeLabel?: boolean;
};

export function Breadcrumb({ items, showHomeLabel }: Props) {
  return (
    <ShadcnBreadcrumb>
      <BreadcrumbList>
        <BreadcrumbLink asChild>
          <Link to="/">
            <HomeIcon className="w-4 h-4 inline" />
            {showHomeLabel && <span className="ml-2">홈</span>}
          </Link>
        </BreadcrumbLink>
        {items.flatMap((item, idx) => {
          const Separator = (
            <BreadcrumbSeparator key={`breadcrumb-separator-${idx}`} />
          );

          if (item.type === "text") {
            return [
              Separator,
              <BreadcrumbItem
                key={`breadcrumb-text-${item.label}`}
                className={item.className}
              >
                {item.label}
              </BreadcrumbItem>,
            ];
          }

          if (item.type === "link") {
            return [
              Separator,
              <BreadcrumbLink
                key={`breadcrumb-link-${item.label}`}
                asChild
                className={item.className}
              >
                <Link to={item.to} params={item.params}>
                  {item.label}
                </Link>
              </BreadcrumbLink>,
            ];
          }

          if (item.type === "component") {
            return [Separator, item.component];
          }

          return [];
        })}
      </BreadcrumbList>
    </ShadcnBreadcrumb>
  );
}
