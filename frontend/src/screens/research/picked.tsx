/** The papers an LLM lab task will draw on, shown in the lab's form. */

import { Link } from '@tanstack/react-router'
import { Button, LINK, Panel } from '@/ui/kit'
import { useResearchPick } from './api'

export function ResearchPicked() {
  const picked = useResearchPick((s) => s.picked)
  const clear = useResearchPick((s) => s.clear)
  return (
    <Panel
      title="Research"
      actions={
        picked.length > 0 ? (
          <Button variant="ghost" size="sm" onClick={clear}>
            Clear
          </Button>
        ) : undefined
      }
    >
      {picked.length === 0 ? (
        <p className="text-body text-ink-subtle">
          No papers chosen. Pick some on the{' '}
          <Link to="/research" className={LINK}>
            Research
          </Link>{' '}
          screen and every LLM call shows one of them, in turn, beside your fields.
        </p>
      ) : (
        <ul className="flex flex-col gap-1 text-body">
          {picked.map((p) => (
            <li key={p.id} className="truncate">
              {p.title}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

/** The ids a lab request sends. */
export function useResearchIds(): number[] {
  return useResearchPick((s) => s.picked).map((p) => p.id)
}
