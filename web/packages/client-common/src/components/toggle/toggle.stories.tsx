import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";

import { Toggle } from "./toggle";

const meta = {
  component: Toggle,
  argTypes: {
    checked: {
      control: { type: "boolean" },
    },
  },
} satisfies Meta<typeof Toggle>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Off: Story = {
  args: {
    checked: false,
  },
};

export const On: Story = {
  args: {
    checked: true,
  },
};

export const Interactive: Story = {
  render: () => {
    const [checked, setChecked] = useState(false);
    return (
      <div className="flex items-center gap-3">
        <Toggle checked={checked} onChange={setChecked} />
        <span className="text-paragraph">{checked ? "On" : "Off"}</span>
      </div>
    );
  },
};
