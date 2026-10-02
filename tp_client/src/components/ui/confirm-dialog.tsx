"use client";

import { useCallback, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export type ConfirmOptions = { title: string; description: string; action: string };

/** `confirm()` resolves true only on the destructive button; render `dialog` once in the caller. */
export function useConfirm() {
  const [ask, setAsk] = useState<
    (ConfirmOptions & { open: boolean; resolve: (ok: boolean) => void }) | null
  >(null);
  const cancel = useRef<HTMLButtonElement>(null);

  const confirm = useCallback(
    (options: ConfirmOptions) =>
      new Promise<boolean>((resolve) => setAsk({ ...options, open: true, resolve })),
    [],
  );

  const settle = (ok: boolean) => {
    if (!ask?.open) return;
    ask.resolve(ok);
    setAsk({ ...ask, open: false });
  };

  const dialog = (
    <Dialog open={ask?.open ?? false} onOpenChange={(open) => !open && settle(false)}>
      <DialogContent className="sm:max-w-[400px]" initialFocus={cancel}>
        <DialogHeader>
          <DialogTitle>{ask?.title}</DialogTitle>
          <DialogDescription>{ask?.description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose ref={cancel} render={<Button variant="outline" />}>
            Cancel
          </DialogClose>
          <Button variant="destructive" onClick={() => settle(true)}>
            {ask?.action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );

  return [confirm, dialog] as const;
}
