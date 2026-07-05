import type { Meta, StoryObj } from "@storybook/react";

import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from "./table";

const meta = {
  component: Table,
} satisfies Meta<typeof Table>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHeaderCell>이름</TableHeaderCell>
          <TableHeaderCell>반</TableHeaderCell>
          <TableHeaderCell>점수</TableHeaderCell>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow>
          <TableCell>김철수</TableCell>
          <TableCell>1반</TableCell>
          <TableCell>95</TableCell>
        </TableRow>
        <TableRow>
          <TableCell>이영희</TableCell>
          <TableCell>2반</TableCell>
          <TableCell>88</TableCell>
        </TableRow>
        <TableRow>
          <TableCell>박지민</TableCell>
          <TableCell>1반</TableCell>
          <TableCell>92</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  ),
};
