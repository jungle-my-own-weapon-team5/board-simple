"use client";

import { useEffect, useState, type MouseEvent } from "react";

import { cn } from "@/lib/utils";
import type { MarkdownHeading } from "@/lib/markdownHeadings";

type PostTableOfContentsProps = {
  headings: MarkdownHeading[];
};

export default function PostTableOfContents({ headings }: PostTableOfContentsProps) {
  const [activeId, setActiveId] = useState(headings[0]?.id ?? "");

  useEffect(() => {
    setActiveId(headings[0]?.id ?? "");
  }, [headings]);

  useEffect(() => {
    if (headings.length === 0) {
      return;
    }

    const updateActiveHeading = () => {
      let currentId = headings[0].id;

      for (const heading of headings) {
        const element = document.getElementById(heading.id);

        if (!element) {
          continue;
        }

        if (element.getBoundingClientRect().top <= 128) {
          currentId = heading.id;
        } else {
          break;
        }
      }

      setActiveId(currentId);
    };

    updateActiveHeading();
    window.addEventListener("scroll", updateActiveHeading, { passive: true });
    window.addEventListener("resize", updateActiveHeading);

    return () => {
      window.removeEventListener("scroll", updateActiveHeading);
      window.removeEventListener("resize", updateActiveHeading);
    };
  }, [headings]);

  if (headings.length === 0) {
    return null;
  }

  const handleAnchorClick = (id: string) => (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();

    const element = document.getElementById(id);

    if (!element) {
      return;
    }

    element.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.pushState(
      null,
      "",
      `${window.location.pathname}${window.location.search}#${encodeURIComponent(id)}`,
    );
  };

  return (
    <aside className="hidden lg:block">
      <nav
        aria-label="게시글 목차"
        className="group fixed right-8 top-1/2 z-20 flex max-h-[calc(100vh-8rem)] w-8 -translate-y-1/2 justify-end overflow-visible transition-[width] duration-200 ease-out hover:w-[18rem] focus-within:w-[18rem]"
      >
        <div className="flex max-h-[calc(100vh-8rem)] w-full flex-col items-end gap-2 overflow-visible py-3 pr-1">
          {headings.map((heading) => {
            const isActive = activeId === heading.id;

            return (
              <a
                key={heading.id}
                href={`#${heading.id}`}
                aria-current={isActive ? "location" : undefined}
                className="group/item flex h-4 w-full items-center justify-end gap-3 outline-none"
                onClick={handleAnchorClick(heading.id)}
              >
                <span
                  className={cn(
                    "min-w-0 flex-1 translate-x-2 overflow-hidden text-ellipsis whitespace-nowrap rounded-sm bg-card/90 px-2 py-1 text-right text-xs leading-none text-muted-foreground opacity-0 shadow-sm shadow-black/5 backdrop-blur transition-all duration-200",
                    "group-hover:translate-x-0 group-hover:opacity-100 group-focus-within:translate-x-0 group-focus-within:opacity-100",
                    isActive && "font-semibold text-foreground",
                  )}
                  style={{ paddingLeft: `${0.5 + (heading.level - 1) * 0.75}rem` }}
                >
                  {heading.text}
                </span>
                <span
                  className={cn(
                    "block h-0.5 flex-none rounded-full transition-all duration-200",
                    isActive
                      ? "w-8 bg-foreground"
                      : "w-6 bg-border group-hover/item:bg-muted-foreground/70",
                  )}
                />
              </a>
            );
          })}
        </div>
      </nav>
    </aside>
  );
}
