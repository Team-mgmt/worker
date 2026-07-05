import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { CheckIcon, ChevronsUpDownIcon, XIcon } from "lucide-react";

import { ADMIN_ORGANIZATION_ID, GUEST_ORGANIZATION_ID } from "@/lib/constants";
import { cn } from "@/lib/utils";

import { queries } from "@/queries";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface OrganizationSelectProps {
  value: string | null;
  onChange: (value: string | null) => void;
  optional?: boolean;
}

export function OrganizationSelect({
  value,
  onChange,
  optional = false,
}: OrganizationSelectProps) {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const { data } = useQuery(queries.organization.list(1, 1000));
  const organizations = (data?.data ?? []).filter(
    (org) =>
      org.id !== ADMIN_ORGANIZATION_ID && org.id !== GUEST_ORGANIZATION_ID,
  );

  const selectedOrganization = organizations.find((org) => org.id === value);

  const filteredOrganizations = organizations.filter((org) =>
    org.name.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const handleSelect = (orgId: string) => {
    onChange(orgId === value ? null : orgId);
    setOpen(false);
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation();
    onChange(null);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className="w-full justify-between font-normal"
        >
          {selectedOrganization ? (
            <span className="truncate">{selectedOrganization.name}</span>
          ) : (
            <span className="text-muted-foreground">조직을 선택하세요</span>
          )}
          <div className="flex items-center gap-1">
            {optional && value && (
              <XIcon
                className="size-4 shrink-0 opacity-50 hover:opacity-100"
                onClick={handleClear}
              />
            )}
            <ChevronsUpDownIcon className="size-4 shrink-0 opacity-50" />
          </div>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-(--radix-popover-trigger-width) p-0">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder="조직 이름을 검색하세요..."
            value={searchQuery}
            onValueChange={setSearchQuery}
          />
          <CommandList>
            <CommandEmpty>검색 결과가 없습니다</CommandEmpty>
            <CommandGroup>
              {filteredOrganizations.map((org) => (
                <CommandItem
                  key={org.id}
                  value={org.id}
                  onSelect={() => handleSelect(org.id)}
                >
                  <CheckIcon
                    className={cn(
                      "mr-2 size-4",
                      value === org.id ? "opacity-100" : "opacity-0",
                    )}
                  />
                  {org.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
