"use client";

// The avatar in the app bar, and the menu behind it. Sign out is the only item so far.

import { Avatar } from "@base-ui/react/avatar";
import { Menu } from "@base-ui/react/menu";

import type { User } from "@/lib/api-types";

/** Google gives no initials, and `name` is not guaranteed, so fall back down to the email. */
function initials(user: User): string {
  const source = user.name?.trim() || user.email;
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2)).toUpperCase();
}

export function UserMenu({ user }: { user: User }) {
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label="Account"
        className="rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <Avatar.Root className="grid size-7 shrink-0 place-items-center overflow-hidden rounded-full bg-[#d7cfba] text-[11px] font-semibold text-ink-soft select-none">
          {user.picture ? (
            <Avatar.Image src={user.picture} alt="" className="size-full object-cover" />
          ) : null}
          <Avatar.Fallback>{initials(user)}</Avatar.Fallback>
        </Avatar.Root>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner side="bottom" align="end" sideOffset={8}>
          <Menu.Popup className="z-50 min-w-56 origin-(--transform-origin) rounded-lg bg-popover p-1.5 text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95">
            <div className="px-2.5 py-2">
              {user.name ? (
                <p className="truncate text-[13.5px] font-medium">{user.name}</p>
              ) : null}
              <p className="truncate text-xs text-muted-foreground">{user.email}</p>
            </div>
            <div className="my-1 h-px bg-border" />
            {/* A form, not fetch: sign-out is a mutation, and the handler redirects. */}
            <form action="/api/auth/signout" method="post">
              <Menu.Item
                render={<button type="submit" />}
                nativeButton
                className="flex w-full cursor-default items-center rounded-md px-2.5 py-1.5 text-[13.5px] outline-none data-highlighted:bg-muted"
              >
                Sign out
              </Menu.Item>
            </form>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}
