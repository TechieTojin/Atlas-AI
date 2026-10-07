import { QueryForm } from '../components/QueryForm'
import { EyebrowPill, FeaturePill } from '../components/PageHero'
import { ResearchHeroArt } from '../components/art/ResearchHeroArt'
import { Leaf } from '../components/art/Leaf'
import { useI18n } from '../i18n'
import {
  AtlasMark,
  BarChartIcon,
  BookIcon,
  FileTextIcon,
  RocketIcon,
  ShieldCheckIcon,
  SparkleIcon,
  SparklesIcon,
  TargetIcon,
} from '../components/icons'

const CAPABILITIES = [
  { icon: SparklesIcon, label: 'research.capabilities.multiAgent' },
  { icon: SparkleIcon, label: 'research.capabilities.verified' },
  { icon: ShieldCheckIcon, label: 'research.capabilities.analysis' },
  { icon: FileTextIcon, label: 'research.capabilities.reports' },
] as const

const BENEFITS = [
  { icon: RocketIcon, title: 'research.benefits.timeTitle', text: 'research.benefits.timeText' },
  { icon: BookIcon, title: 'research.benefits.knowledgeTitle', text: 'research.benefits.knowledgeText' },
  { icon: TargetIcon, title: 'research.benefits.insightsTitle', text: 'research.benefits.insightsText' },
  { icon: BarChartIcon, title: 'research.benefits.reportsTitle', text: 'research.benefits.reportsText' },
] as const

export function ResearchPage() {
  const { t } = useI18n()
  return (
    <div className="research-page">
      <div className="research-backdrop" aria-hidden="true">
        <div className="research-terrain" />
        <Leaf size={56} rotate={30} className="research-leaf-ground-a" />
        <Leaf size={38} rotate={-60} className="research-leaf-ground-b" />
      </div>

      <section className="research-hero">
        <div className="research-hero-copy">
          <EyebrowPill icon={SparkleIcon} uppercase>
            {t('research.eyebrow')}
          </EyebrowPill>
          <h1 className="research-wordmark">
            <span className="research-wordmark-text">Atlas</span>
            <AtlasMark size={44} className="research-wordmark-leaf" />
          </h1>
          <p className="research-tagline">{t('research.tagline')}</p>
          <ul className="capability-row" aria-label={t('research.capabilitiesLabel')}>
            {CAPABILITIES.map(({ icon, label }) => (
              <li key={label}>
                <FeaturePill icon={icon} label={t(label)} />
              </li>
            ))}
          </ul>
        </div>
        <ResearchHeroArt />
        <p className="script-note research-script" aria-hidden="true">
          {t('research.scriptLine1')}
          <br />
          {t('research.scriptLine2')}
          <br />
          {t('research.scriptLine3')}
        </p>
      </section>

      <QueryForm />

      <section className="benefit-strip" aria-label={t('research.benefitsLabel')}>
        {BENEFITS.map(({ icon: Icon, title, text }) => (
          <div key={title} className="benefit">
            <span className="benefit-icon">
              <Icon size={20} />
            </span>
            <span className="benefit-body">
              <span className="benefit-title">{t(title)}</span>
              <span className="benefit-text">{t(text)}</span>
            </span>
          </div>
        ))}
      </section>
    </div>
  )
}
