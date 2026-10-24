import { EditorialMotif } from './EditorialMotif'

/** Calm editorial research motif behind the run/report hero.
 *  Accepts (and ignores) the legacy `label` prop from RunPage. */
export function ReportHeroArt(_props: { label?: string }) {
  return <EditorialMotif variant="b" />
}
