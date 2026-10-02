import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export const COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"];

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
