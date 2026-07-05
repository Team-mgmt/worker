import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";

import { SearchBar } from "./search-bar";

const meta = {
  component: SearchBar,
} satisfies Meta<typeof SearchBar>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    placeholder: "Textfield",
  },
};

export const Disabled: Story = {
  args: {
    placeholder: "Textfield",
    disabled: true,
  },
};

export const Interactive: Story = {
  render: () => {
    const [value, setValue] = useState("Textfield");
    return (
      <SearchBar
        placeholder="Textfield"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onClear={() => setValue("")}
      />
    );
  },
};
