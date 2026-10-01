export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-border px-1 font-mono text-[10.5px] text-faint">
      {children}
    </kbd>
  );
}
