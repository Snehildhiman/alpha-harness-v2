import { type ClassValue, clsx } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

/** The `--text-*` and `--radius-*` scales in index.css; unregistered, twMerge reads `text-body` as a colour. */
const twMerge = extendTailwindMerge({
  extend: {
    theme: { text: ['caption', 'body-compact', 'body', 'title', 'headline'], radius: ['pill'] },
  },
})

/** Class names where a later conflicting utility wins (`cn('h-8', 'h-7')` → `h-7`), so props can override variants. */
export const cn = (...inputs: ClassValue[]): string => twMerge(clsx(inputs))
