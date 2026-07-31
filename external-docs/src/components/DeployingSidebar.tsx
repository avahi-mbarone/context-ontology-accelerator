// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useCallback } from "react";

type NavItem = {
  id: string;
  label: string;
};

type NavSection = {
  stage: string;
  items: NavItem[];
};

const SECTIONS: NavSection[] = [
  {
    stage: "Setup",
    items: [
      { id: "prerequisites", label: "Prerequisites" },
      { id: "aws-account-setup", label: "AWS Account Setup" },
      { id: "installation", label: "Installation" },
    ],
  },
  {
    stage: "Deploy",
    items: [
      { id: "deploy", label: "Deploy" },
      { id: "post-deployment", label: "Post-Deployment" },
      { id: "updating", label: "Updating" },
    ],
  },
  {
    stage: "Operations",
    items: [
      { id: "tearing-down", label: "Tearing Down" },
      { id: "troubleshooting", label: "Troubleshooting" },
    ],
  },
];

const ALL_IDS = SECTIONS.flatMap((s) => s.items.map((i) => i.id));

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .trim();
}

export function DeployingSidebar(): React.JSX.Element {
  const [activeId, setActiveId] = useState<string>(ALL_IDS[0]!);

  const handleClick = useCallback((id: string) => {
    // Find the heading element in the rendered markdown
    const headings = document.querySelectorAll(".prose h2");
    for (const heading of headings) {
      if (slugify(heading.textContent ?? "") === id) {
        heading.scrollIntoView({ behavior: "smooth", block: "start" });
        setActiveId(id);
        break;
      }
    }
  }, []);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        // Find the topmost visible heading
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible.length > 0) {
          const slug = slugify(visible[0]!.target.textContent ?? "");
          if (ALL_IDS.includes(slug)) {
            setActiveId(slug);
          }
        }
      },
      { rootMargin: "-80px 0px -60% 0px", threshold: 0 },
    );

    // Observe all h2 headings in the prose
    const headings = document.querySelectorAll(".prose h2");
    headings.forEach((h) => observer.observe(h));

    return () => observer.disconnect();
  }, []);

  return (
    <aside className="hidden w-56 shrink-0 border-r border-rule py-8 pr-6 md:block">
      {SECTIONS.map((section) => (
        <div key={section.stage} className="mb-6">
          <p className="mb-2 text-[11px] font-medium tracking-[0.18em] uppercase text-terracotta">
            {section.stage}
          </p>
          <ul className="space-y-0.5">
            {section.items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => handleClick(item.id)}
                  className={`block w-full text-left rounded-md px-3 py-2 text-[13.5px] font-medium transition-colors ${
                    activeId === item.id
                      ? "bg-terracotta/8 text-terracotta-deep"
                      : "text-ink-muted hover:text-ink hover:bg-ink/[0.03]"
                  }`}
                >
                  {item.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </aside>
  );
}
