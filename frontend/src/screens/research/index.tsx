/**
 * Research: papers and posts from free feeds (arXiv's quantitative finance by default), read
 * twice a day. Pick some and the LLM Power Pool and Region Agnostic Labs show one of them, in
 * turn, on every call, so the model carries the paper's idea over to BRAIN's data.
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ExternalLinkIcon, RefreshCwIcon, StarIcon } from 'lucide-react'
import { useState } from 'react'
import { fmt } from '@/lib/format'
import { useDebounced } from '@/lib/use-debounced'
import {
  Button,
  Checkbox,
  Empty,
  ErrorNotice,
  Input,
  LINK,
  Notice,
  Page,
  PageHeader,
  Panel,
  Segmented,
  Skeleton,
} from '@/ui/kit'
import { Pager } from '@/ui/table'
import { type Paper, paperPage, refreshFeeds, starPaper, useResearchPick } from './api'

const LIMIT = 30

function PaperCard({ paper }: { paper: Paper }) {
  const client = useQueryClient()
  const picked = useResearchPick((s) => s.picked.some((p) => p.id === paper.id))
  const toggle = useResearchPick((s) => s.toggle)
  const [open, setOpen] = useState(false)
  const star = useMutation({
    mutationFn: () => starPaper(paper.id, !paper.starred),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['research'] }),
  })
  return (
    <li className="flex gap-3 border-b border-hairline-subtle py-3 last:border-b-0">
      <div className="pt-0.5">
        <Checkbox
          label={<span className="sr-only">Use “{paper.title}” in LLM tasks</span>}
          checked={picked}
          onChange={() => toggle({ id: paper.id, title: paper.title })}
        />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-start justify-between gap-3">
          <button
            type="button"
            className="text-left text-body font-medium text-ink hover:underline"
            onClick={() => setOpen((v) => !v)}
          >
            {paper.title}
          </button>
          <div className="flex shrink-0 items-center gap-1">
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={paper.starred ? 'Unstar' : 'Star'}
              title={paper.starred ? 'Unstar' : 'Star'}
              onClick={() => star.mutate()}
            >
              <StarIcon className={paper.starred ? 'fill-current text-status-warning' : ''} />
            </Button>
            {paper.url && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Open the paper"
                title="Open the paper"
                render={<a href={paper.url} target="_blank" rel="noopener noreferrer" />}
              >
                <ExternalLinkIcon />
              </Button>
            )}
          </div>
        </div>
        <p className="text-body-compact text-ink-subtle">
          {paper.source} · {fmt.date(paper.published)}
          {paper.authors ? ` · ${paper.authors}` : ''}
        </p>
        <p className={`text-body text-ink-muted ${open ? '' : 'line-clamp-2'}`}>{paper.summary}</p>
      </div>
    </li>
  )
}

export function ResearchScreen() {
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const [show, setShow] = useState<'all' | 'starred'>('all')
  const [offset, setOffset] = useState(0)
  const debounced = useDebounced(search, 300)
  const picked = useResearchPick((s) => s.picked)
  const clear = useResearchPick((s) => s.clear)
  const page = useQuery({
    ...paperPage({
      search: debounced || undefined,
      starred: show === 'starred',
      limit: LIMIT,
      offset,
    }),
    placeholderData: keepPreviousData,
  })
  const refresh = useMutation({
    mutationFn: refreshFeeds,
    onSuccess: () => void client.invalidateQueries({ queryKey: ['research'] }),
  })
  const data = page.data

  return (
    <Page>
      <PageHeader
        title="Research"
        description="Papers from free feeds, read twice a day. Tick the ones worth trying and the LLM Power Pool and Region Agnostic Labs carry their ideas over to your fields, one paper a call. Results still pass the dedup, the models and BRAIN before they count."
        actions={
          <Button loading={refresh.isPending} onClick={() => refresh.mutate()}>
            <RefreshCwIcon aria-hidden />
            Read feeds now
          </Button>
        }
      />
      {picked.length > 0 && (
        <Notice
          title={`${fmt.int(picked.length)} paper${picked.length === 1 ? '' : 's'} chosen`}
          action={
            <div className="flex gap-2">
              <Button variant="ghost" onClick={clear}>
                Clear
              </Button>
              <Button variant="primary" render={<Link to="/labs/power-pool" />}>
                Use in LLM Power Pool Lab
              </Button>
              <Button render={<Link to="/labs/region-agnostic" />}>
                Use in Region Agnostic Lab
              </Button>
            </div>
          }
        >
          The next task you add in either lab draws on them.
        </Notice>
      )}
      {refresh.isError && <ErrorNotice error={refresh.error} title="Could not read the feeds" />}
      {data?.lastError && (
        <Notice tone="warn" title="A feed could not be read">
          {data.lastError}
        </Notice>
      )}
      <Panel>
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <Input
              className="max-w-sm"
              placeholder="Search titles and summaries"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setOffset(0)
              }}
            />
            <Segmented
              label="Show"
              items={[
                { value: 'all', label: 'All' },
                { value: 'starred', label: 'Starred' },
              ]}
              value={show}
              onChange={(v) => {
                setShow(v)
                setOffset(0)
              }}
            />
            <span className="text-body-compact text-ink-subtle">
              {data?.lastRead ? `Read ${fmt.ago(data.lastRead)}` : 'Not read yet'} ·{' '}
              {data?.sources.join(', ')} · add feeds in Settings
            </span>
          </div>
          {page.isError && <ErrorNotice error={page.error} title="Could not read the library" />}
          {page.isPending ? (
            <Skeleton label="Reading the library" />
          ) : !data?.papers.length ? (
            <Empty title="No papers yet">
              <p>
                Press Read feeds now. The app reads arXiv’s quantitative finance listing; see{' '}
                <a
                  className={LINK}
                  href="https://arxiv.org/list/q-fin/new"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  arXiv q-fin
                </a>
                .
              </p>
            </Empty>
          ) : (
            <ul className="flex flex-col">
              {data.papers.map((paper) => (
                <PaperCard key={paper.id} paper={paper} />
              ))}
            </ul>
          )}
          <Pager total={data?.total ?? 0} offset={offset} limit={LIMIT} onChange={setOffset} />
        </div>
      </Panel>
    </Page>
  )
}
