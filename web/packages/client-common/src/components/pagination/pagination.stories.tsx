import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";

import { Pagination } from "./pagination";

const meta = {
  component: Pagination,
} satisfies Meta<typeof Pagination>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => {
    const [page, setPage] = useState(1);
    return (
      <Pagination currentPage={page} totalPages={10} onPageChange={setPage} />
    );
  },
};

export const ManyPages: Story = {
  render: () => {
    const [page, setPage] = useState(1);
    return (
      <Pagination currentPage={page} totalPages={50} onPageChange={setPage} />
    );
  },
};

export const FewPages: Story = {
  render: () => {
    const [page, setPage] = useState(1);
    return (
      <Pagination currentPage={page} totalPages={3} onPageChange={setPage} />
    );
  },
};
