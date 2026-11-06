"use client";

import * as T from "@radix-ui/react-tabs";
import type { ComponentProps } from "react";

import { cn } from "@/lib/format";

export const Tabs = T.Root;

export function TabsList({ className, ...props }: ComponentProps<typeof T.List>) {
  return (
    <T.List
      className={cn("flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none]", className)}
      {...props}
    />
  );
}

export function Tab({ className, ...props }: ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        "-mb-px shrink-0 border-b-2 border-transparent px-3 py-2.5 text-sm text-muted hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg",
        className,
      )}
      {...props}
    />
  );
}

export function TabPanel({ className, ...props }: ComponentProps<typeof T.Content>) {
  return <T.Content className={cn("pt-5 focus-visible:outline-none", className)} {...props} />;
}
