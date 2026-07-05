import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";

import {
  Modal,
  ModalBody,
  ModalDescription,
  ModalFooter,
  ModalHeader,
  ModalInfo,
} from "./modal";
import { Button } from "../button/button";

const meta = {
  component: Modal,
} satisfies Meta<typeof Modal>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: () => {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Open Modal</Button>
        <Modal open={open} onClose={() => setOpen(false)}>
          <ModalHeader onClose={() => setOpen(false)}>Title text</ModalHeader>
          <ModalBody>
            <ModalDescription>
              text text text text text text text text
            </ModalDescription>
            <ModalInfo>text text text text text text text text text</ModalInfo>
          </ModalBody>
          <ModalFooter>
            <Button
              variant="tertiary"
              className="flex-1"
              onClick={() => setOpen(false)}
            >
              button
            </Button>
            <Button variant="primary" className="flex-1">
              button
            </Button>
          </ModalFooter>
        </Modal>
      </>
    );
  },
};

export const WithInputs: Story = {
  render: () => {
    const [open, setOpen] = useState(false);
    return (
      <>
        <Button onClick={() => setOpen(true)}>Open Modal</Button>
        <Modal open={open} onClose={() => setOpen(false)}>
          <ModalHeader onClose={() => setOpen(false)}>Title text</ModalHeader>
          <ModalBody>
            <ModalDescription>
              text text text text text text text text
            </ModalDescription>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-3">
                <p className="text-paragraph leading-paragraph font-regular text-grey-2">
                  text text text text text text text text text
                </p>
                <input
                  placeholder="Textfield"
                  className="h-[34px] w-full rounded-[4px] border border-border bg-grey-5 px-4 py-2 text-paragraph leading-paragraph font-regular text-grey-2 outline-none placeholder:text-grey-2 focus:border-border-active focus:bg-background focus:text-primary-black"
                />
              </div>
              <div className="flex flex-col gap-3">
                <p className="text-paragraph leading-paragraph font-regular text-grey-2">
                  text text text text text text text text text
                </p>
                <input
                  placeholder="Textfield"
                  className="h-[34px] w-full rounded-[4px] border border-border bg-grey-5 px-4 py-2 text-paragraph leading-paragraph font-regular text-grey-2 outline-none placeholder:text-grey-2 focus:border-border-active focus:bg-background focus:text-primary-black"
                />
              </div>
            </div>
          </ModalBody>
          <ModalFooter>
            <Button
              variant="tertiary"
              className="flex-1"
              onClick={() => setOpen(false)}
            >
              button
            </Button>
            <Button variant="primary" className="flex-1">
              button
            </Button>
          </ModalFooter>
        </Modal>
      </>
    );
  },
};
