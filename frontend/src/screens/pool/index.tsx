/**
 * Alphas (spec §4.5): everything stored locally, and what is submittable. Submission stays
 * on BRAIN: this screen links there and never submits.
 */

import { Link, useParams } from '@tanstack/react-router'
import { useState } from 'react'
import { POOL_TABS } from '@/shell/nav'
import { Empty, LINK, Page, PageHeader, Panel, TabBar, TabLink } from '@/ui/kit'
import { DetailSheet } from './detail'
import { Stored } from './stored'
import { Submittable } from './submittable'
import { AlphaCounts, SyncAlphasButton } from './vault'

export function PoolScreen() {
  const { tab } = useParams({ from: '/pool/$tab' })
  const [detailId, setDetailId] = useState<string | null>(null)

  const body =
    tab === 'stored' ? (
      <Stored onOpen={setDetailId} />
    ) : tab === 'submittable' ? (
      <Submittable onOpen={setDetailId} />
    ) : (
      <Panel>
        <Empty title={`No tab called “${tab}”`}>
          <Link to="/pool/$tab" params={{ tab: POOL_TABS[0].tab }} className={LINK}>
            Go to {POOL_TABS[0].label}
          </Link>
        </Empty>
      </Panel>
    )

  return (
    <Page>
      <PageHeader title="Alphas" actions={<SyncAlphasButton />} />
      <AlphaCounts />
      <TabBar>
        {POOL_TABS.map((t) => (
          <TabLink key={t.tab} to="/pool/$tab" params={{ tab: t.tab }}>
            {t.label}
          </TabLink>
        ))}
      </TabBar>
      {body}
      <DetailSheet alphaId={detailId} onClose={() => setDetailId(null)} />
    </Page>
  )
}
