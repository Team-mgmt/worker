import type { Meta, StoryObj } from "@storybook/react";

import { TextInput } from "./text-input";

const meta = {
  component: TextInput,
} satisfies Meta<typeof TextInput>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    placeholder: "Textfield",
  },
};

export const WithValue: Story = {
  args: {
    defaultValue: "Textfield",
  },
};

export const Disabled: Story = {
  args: {
    placeholder: "Textfield",
    disabled: true,
  },
};
