import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";

import { Dropdown, type DropdownOption } from "./dropdown";

const defaultOptions: DropdownOption[] = [
  { label: "항목 1", value: "1" },
  { label: "항목 2", value: "2" },
  { label: "항목 3", value: "3" },
  { label: "항목 4", value: "4" },
  { label: "항목 5", value: "5" },
];

const meta = {
  component: Dropdown,
} satisfies Meta<typeof Dropdown>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    options: defaultOptions,
    placeholder: "Placeholder",
  },
  render: (args) => {
    const [value, setValue] = useState<string | undefined>(undefined);
    return (
      <div className="w-80">
        <Dropdown {...args} value={value} onChange={setValue} />
      </div>
    );
  },
};

export const WithSelection: Story = {
  args: {
    options: defaultOptions,
  },
  render: (args) => {
    const [value, setValue] = useState<string | undefined>("2");
    return (
      <div className="w-80">
        <Dropdown {...args} value={value} onChange={setValue} />
      </div>
    );
  },
};

export const Disabled: Story = {
  args: {
    options: defaultOptions,
    disabled: true,
    placeholder: "Placeholder",
  },
  render: (args) => (
    <div className="w-80">
      <Dropdown {...args} />
    </div>
  ),
};

export const WithDisabledOption: Story = {
  args: {
    options: [
      { label: "항목 1", value: "1" },
      { label: "항목 2", value: "2" },
      { label: "항목 3", value: "3", disabled: true },
      { label: "항목 4", value: "4" },
      { label: "항목 5", value: "5" },
    ],
  },
  render: (args) => {
    const [value, setValue] = useState<string | undefined>(undefined);
    return (
      <div className="w-80">
        <Dropdown {...args} value={value} onChange={setValue} />
      </div>
    );
  },
};
