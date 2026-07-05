import type { Meta, StoryObj } from "@storybook/react";

import { Tooltip } from "./tooltip";
import { Button } from "../button/button";

const meta = {
  component: Tooltip,
} satisfies Meta<typeof Tooltip>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Hover: Story = {
  render: () => (
    <div className="flex h-[200px] items-center justify-center">
      <Tooltip content="선생님이 스캔한 답안지에서 나의 답안을 찾아옵니다">
        <Button variant="secondary">내 답안지 가져오기</Button>
      </Tooltip>
    </div>
  ),
};

export const WithBackdrop: Story = {
  render: () => (
    <div className="flex h-[200px] items-center justify-center">
      <Tooltip backdrop side="bottom" content="탭해서 닫거나 배경을 클릭하세요">
        <Button variant="secondary">탭해서 안내 보기</Button>
      </Tooltip>
    </div>
  ),
};

export const SidePlacements: Story = {
  render: () => (
    <div className="grid grid-cols-2 gap-12 p-16">
      <Tooltip content="top side" side="top">
        <Button variant="tertiary">top</Button>
      </Tooltip>
      <Tooltip content="bottom side" side="bottom">
        <Button variant="tertiary">bottom</Button>
      </Tooltip>
      <Tooltip content="left side" side="left">
        <Button variant="tertiary">left</Button>
      </Tooltip>
      <Tooltip content="right side" side="right">
        <Button variant="tertiary">right</Button>
      </Tooltip>
    </div>
  ),
};
