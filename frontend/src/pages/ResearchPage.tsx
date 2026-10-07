import { QueryForm } from '../components/QueryForm'
import { EyebrowPill, FeaturePill } from '../components/PageHero'
import { ResearchHeroArt } from '../components/art/ResearchHeroArt'
import { Leaf } from '../components/art/Leaf'
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
  { icon: SparklesIcon, label: 'Multi-Agent Research' },
  { icon: SparkleIcon, label: 'Verified Sources' },
  { icon: ShieldCheckIcon, label: 'In-depth Analysis' },
  { icon: FileTextIcon, label: 'Clear & Structured Reports' },
]

const BENEFITS = [
  { icon: RocketIcon, title: 'Save Time', text: 'Get accurate answers in seconds.' },
  { icon: BookIcon, title: 'Reliable Knowledge', text: 'From trusted and verified sources.' },
  { icon: TargetIcon, title: 'Deeper Insights', text: 'Powered by advanced AI agents.' },
  { icon: BarChartIcon, title: 'Beautiful Reports', text: 'Well-structured, easy to understand.' },
]

export function ResearchPage() {
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
            AI-Powered Research
          </EyebrowPill>
          <h1 className="research-wordmark">
            <span className="research-wordmark-text">Atlas</span>
            <AtlasMark size={44} className="research-wordmark-leaf" />
          </h1>
          <p className="research-tagline">Your Research Partner for a Smarter Tomorrow</p>
          <ul className="capability-row" aria-label="Capabilities">
            {CAPABILITIES.map(({ icon, label }) => (
              <li key={label}>
                <FeaturePill icon={icon} label={label} />
              </li>
            ))}
          </ul>
        </div>
        <ResearchHeroArt />
        <p className="script-note research-script" aria-hidden="true">
          Research
          <br />
          Smarter
          <br />
          Live Better
        </p>
      </section>

      <QueryForm />

      <section className="benefit-strip" aria-label="Why Atlas">
        {BENEFITS.map(({ icon: Icon, title, text }) => (
          <div key={title} className="benefit">
            <span className="benefit-icon">
              <Icon size={20} />
            </span>
            <span className="benefit-body">
              <span className="benefit-title">{title}</span>
              <span className="benefit-text">{text}</span>
            </span>
          </div>
        ))}
      </section>
    </div>
  )
}
