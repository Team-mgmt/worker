import type { Meta, StoryObj } from "@storybook/react";
import {
  BarChartIcon,
  BellIcon,
  BookOpenIcon,
  FileTextIcon,
  HomeIcon,
  SearchIcon,
  SettingsIcon,
  UserIcon,
} from "lucide-react";

import { NavButton } from "./nav-button";

const iconMap = {
  Home: <HomeIcon />,
  Settings: <SettingsIcon />,
  User: <UserIcon />,
  Search: <SearchIcon />,
  Bell: <BellIcon />,
  BookOpen: <BookOpenIcon />,
  FileText: <FileTextIcon />,
  BarChart: <BarChartIcon />,
} as const;

const meta = {
  component: NavButton,
  argTypes: {
    icon: {
      options: Object.keys(iconMap),
      mapping: iconMap,
      control: { type: "select" },
    },
  },
} satisfies Meta<typeof NavButton>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    icon: "Home",
    children: "menulist",
    active: false,
  },
};

export const Active: Story = {
  args: {
    icon: "Home",
    children: "menulist",
    active: true,
  },
};
