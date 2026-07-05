import type { Meta, StoryObj } from "@storybook/react";
import { PlusIcon } from "lucide-react";

import { Button } from "./button";

const meta = {
  component: Button,
  argTypes: {
    variant: {
      options: ["primary", "secondary", "ghost", "tertiary"],
      control: { type: "select" },
    },
    size: {
      options: ["lg", "sm"],
      control: { type: "select" },
    },
    iconLeft: {
      options: ["none", "plus"],
      mapping: { none: undefined, plus: <PlusIcon /> },
      control: { type: "select" },
    },
    iconRight: {
      options: ["none", "plus"],
      mapping: { none: undefined, plus: <PlusIcon /> },
      control: { type: "select" },
    },
  },
} satisfies Meta<typeof Button>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Primary: Story = {
  args: {
    variant: "primary",
    size: "lg",
    children: "button",
  },
};

export const Secondary: Story = {
  args: {
    variant: "secondary",
    size: "lg",
    children: "button",
  },
};

export const Ghost: Story = {
  args: {
    variant: "ghost",
    size: "lg",
    children: "button",
  },
};

export const Tertiary: Story = {
  args: {
    variant: "tertiary",
    size: "lg",
    children: "button",
  },
};

export const Small: Story = {
  args: {
    variant: "primary",
    size: "sm",
    children: "button",
  },
};

export const Disabled: Story = {
  args: {
    variant: "primary",
    size: "lg",
    children: "button",
    disabled: true,
  },
};

export const WithIconLeft: Story = {
  args: {
    variant: "primary",
    size: "lg",
    iconLeft: "plus",
    children: "button",
  },
};

export const WithIconBoth: Story = {
  args: {
    variant: "primary",
    size: "lg",
    iconLeft: "plus",
    iconRight: "plus",
    children: "button",
  },
};

export const AllVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-6">
      {(["lg", "sm"] as const).map((size) => (
        <div key={size} className="flex flex-col gap-3">
          <p className="text-sm font-medium text-grey-2">Size: {size}</p>
          <div className="flex flex-wrap items-center gap-3">
            {(["primary", "secondary", "ghost", "tertiary"] as const).map(
              (variant) => (
                <Button
                  key={variant}
                  variant={variant}
                  size={size}
                  iconLeft={<PlusIcon />}
                  iconRight={<PlusIcon />}
                >
                  button
                </Button>
              ),
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {(["primary", "secondary", "ghost", "tertiary"] as const).map(
              (variant) => (
                <Button
                  key={variant}
                  variant={variant}
                  size={size}
                  iconLeft={<PlusIcon />}
                  iconRight={<PlusIcon />}
                  disabled
                >
                  button
                </Button>
              ),
            )}
          </div>
        </div>
      ))}
    </div>
  ),
};
