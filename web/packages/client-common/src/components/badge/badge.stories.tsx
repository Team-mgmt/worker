import type { Meta, StoryObj } from "@storybook/react";
import { CheckIcon } from "lucide-react";

import { Badge } from "./badge";

const meta = {
  component: Badge,
  argTypes: {
    size: {
      options: ["lg", "sm"],
      control: { type: "select" },
    },
    variant: {
      options: ["default", "primary", "danger", "success"],
      control: { type: "select" },
    },
  },
} satisfies Meta<typeof Badge>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    size: "lg",
    children: "text",
  },
};

export const Small: Story = {
  args: {
    size: "sm",
    children: "text",
  },
};

export const AllSizes: Story = {
  render: () => (
    <div className="flex items-center gap-3">
      <Badge size="lg">large</Badge>
      <Badge size="sm">small</Badge>
    </div>
  ),
};

export const AllVariants: Story = {
  render: () => (
    <div className="flex items-center gap-3">
      <Badge variant="default">국어</Badge>
      <Badge variant="primary">
        <CheckIcon />
        활성
      </Badge>
      <Badge variant="danger">입력 필요</Badge>
      <Badge variant="success">입력 완료</Badge>
    </div>
  ),
};
