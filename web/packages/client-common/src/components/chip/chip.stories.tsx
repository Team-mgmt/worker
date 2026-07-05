import type { Meta, StoryObj } from "@storybook/react";

import { Chip } from "./chip";

const meta = {
  component: Chip,
  argTypes: {
    active: {
      control: { type: "boolean" },
    },
  },
} satisfies Meta<typeof Chip>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Active: Story = {
  args: {
    active: true,
    children: "Label",
  },
};

export const Inactive: Story = {
  args: {
    active: false,
    children: "Label",
  },
};

export const AllStates: Story = {
  render: () => (
    <div className="flex items-center gap-3">
      <Chip active>Label</Chip>
      <Chip>Label</Chip>
    </div>
  ),
};
