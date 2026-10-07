interface IconProps {
  size?: number
  className?: string
}

function base(size: number | undefined) {
  return {
    width: size ?? 16,
    height: size ?? 16,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }
}

export function FileIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z" />
      <path d="M14 3v4h4" />
    </svg>
  )
}

export function FileTextIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z" />
      <path d="M14 3v4h4" />
      <path d="M9 12h6M9 16h6" />
    </svg>
  )
}

export function ExternalIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M14 5h5v5" />
      <path d="M19 5 10 14" />
      <path d="M19 13v6H5V5h6" />
    </svg>
  )
}

export function SunIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  )
}

export function MoonIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5z" />
    </svg>
  )
}

export function TrashIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 7h16" />
      <path d="M9 7V4h6v3" />
      <path d="M6 7l1 13h10l1-13" />
    </svg>
  )
}

export function DownloadIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 4v11" />
      <path d="M7 11l5 5 5-5" />
      <path d="M5 20h14" />
    </svg>
  )
}

export function CheckIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M5 13l4 4L19 7" />
    </svg>
  )
}

export function CheckCircleIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8.5 12.5l2.5 2.5 4.5-5" />
    </svg>
  )
}

export function XIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  )
}

export function XCircleIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </svg>
  )
}

export function MenuIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  )
}

export function UploadIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 16V5" />
      <path d="M7 10l5-5 5 5" />
      <path d="M5 20h14" />
    </svg>
  )
}

export function CloudUploadIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M7 18a4 4 0 0 1-.6-7.95A6 6 0 0 1 18 8.5a4.5 4.5 0 0 1-.5 9" />
      <path d="M12 12v9" />
      <path d="M8.5 15.5 12 12l3.5 3.5" />
    </svg>
  )
}

export function SearchIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m20 20-4.2-4.2" />
    </svg>
  )
}

export function FolderIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  )
}

export function FolderOpenIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1" />
      <path d="M3 10h18.5l-2 8H5z" />
    </svg>
  )
}

export function CrownIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 17h16" />
      <path d="M4 17 3 8l5 3 4-6 4 6 5-3-1 9z" />
    </svg>
  )
}

export function SparkleIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <path d="M12 7c.6 2.6 2.4 4.4 5 5-2.6.6-4.4 2.4-5 5-.6-2.6-2.4-4.4-5-5 2.6-.6 4.4-2.4 5-5z" />
    </svg>
  )
}

export function SparklesIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M10 5c.5 2.6 2 4.1 4.6 4.6C12 10.1 10.5 11.6 10 14.2 9.5 11.6 8 10.1 5.4 9.6 8 9.1 9.5 7.6 10 5z" />
      <path d="M17.5 13c.3 1.4 1.1 2.2 2.5 2.5-1.4.3-2.2 1.1-2.5 2.5-.3-1.4-1.1-2.2-2.5-2.5 1.4-.3 2.2-1.1 2.5-2.5z" />
    </svg>
  )
}

export function BoltIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M13 3 5 14h6l-1 7 8-11h-6z" />
    </svg>
  )
}

export function GlobeIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </svg>
  )
}

export function ShieldCheckIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3 5 6v5c0 4.4 3 8.2 7 9.5 4-1.3 7-5.1 7-9.5V6z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  )
}

export function PaperclipIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="m20 11-8.5 8.5a5 5 0 0 1-7-7L13 4a3.3 3.3 0 0 1 4.7 4.7L9.5 17a1.7 1.7 0 0 1-2.4-2.4L15 7" />
    </svg>
  )
}

export function ChevronDownIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}

export function ChevronRightIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="m9 6 6 6-6 6" />
    </svg>
  )
}

export function ArrowUpIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 19V5" />
      <path d="m6 11 6-6 6 6" />
    </svg>
  )
}

export function ArrowRightIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  )
}

export function ArrowLeftIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M19 12H5" />
      <path d="m11 18-6-6 6-6" />
    </svg>
  )
}

export function RocketIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M14 4c3 0 6 3 6 6-2 4-6 7-10 8l-4-4c1-4 4-8 8-10z" />
      <circle cx="14.5" cy="9.5" r="1.5" />
      <path d="M8 16c-2 .5-3 2-3.5 4 2-.5 3.5-1.5 4-3.5" />
    </svg>
  )
}

export function BookIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 6c-2-1.5-4.5-2-8-2v14c3.5 0 6 .5 8 2 2-1.5 4.5-2 8-2V4c-3.5 0-6 .5-8 2z" />
      <path d="M12 6v14" />
    </svg>
  )
}

export function TargetIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.2" fill="currentColor" />
    </svg>
  )
}

export function ChartIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M5 20V12" />
      <path d="M12 20V6" />
      <path d="M19 20v-4" />
    </svg>
  )
}

export function BarChartIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 20h16" />
      <path d="M7 16v-5M12 16V7M17 16v-3" />
    </svg>
  )
}

export function PlusIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function MoreVerticalIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className} fill="currentColor" stroke="none">
      <circle cx="12" cy="5.5" r="1.6" />
      <circle cx="12" cy="12" r="1.6" />
      <circle cx="12" cy="18.5" r="1.6" />
    </svg>
  )
}

export function EyeIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

export function GridIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="4" y="4" width="6.5" height="6.5" rx="1.5" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" />
    </svg>
  )
}

export function ListIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M8 6h12M8 12h12M8 18h12" />
      <path d="M4 6h.01M4 12h.01M4 18h.01" strokeWidth={2.6} />
    </svg>
  )
}

export function ClockIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  )
}

export function UsersIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0" />
      <path d="M16 5a3.5 3.5 0 0 1 0 6.5M21.5 20a6.5 6.5 0 0 0-4.5-6.1" />
    </svg>
  )
}

export function LayersIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="m12 3 9 5-9 5-9-5z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 16 9 5 9-5" />
    </svg>
  )
}

export function RefreshIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M20 12a8 8 0 0 1-14.3 4.9" />
      <path d="M4 12a8 8 0 0 1 14.3-4.9" />
      <path d="M18 3v4.5h-4.5M6 21v-4.5h4.5" />
    </svg>
  )
}

export function LinkIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" />
      <path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" />
    </svg>
  )
}

export function ShareIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="18" cy="5" r="2.5" />
      <circle cx="6" cy="12" r="2.5" />
      <circle cx="18" cy="19" r="2.5" />
      <path d="m8.3 10.8 7.4-4.6M8.3 13.2l7.4 4.6" />
    </svg>
  )
}

export function BulbIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M9 18h6" />
      <path d="M10 21h4" />
      <path d="M12 3a6 6 0 0 0-3.5 10.9c.8.6 1.5 1.6 1.5 2.6v.5h4v-.5c0-1 .7-2 1.5-2.6A6 6 0 0 0 12 3z" />
    </svg>
  )
}

export function ListTreeIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="M4 6h1M4 12h1M4 18h1" strokeWidth={2.4} />
    </svg>
  )
}

export function InfoIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <path d="M12 8h.01" strokeWidth={2.4} />
    </svg>
  )
}

export function NetworkIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="2.5" />
      <circle cx="5" cy="6" r="2" />
      <circle cx="19" cy="6" r="2" />
      <circle cx="5" cy="18" r="2" />
      <circle cx="19" cy="18" r="2" />
      <path d="m6.6 7.3 3.6 3.1M17.4 7.3l-3.6 3.1M6.6 16.7l3.6-3.1M17.4 16.7l-3.6-3.1" />
    </svg>
  )
}

export function QuoteIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M7 7h4v6H6a1 1 0 0 1-1-1V9a2 2 0 0 1 2-2z" />
      <path d="M6 13c0 2.5 1.5 4 4 4" />
      <path d="M16 7h4v6h-5a1 1 0 0 1-1-1V9a2 2 0 0 1 2-2z" />
      <path d="M15 13c0 2.5 1.5 4 4 4" />
    </svg>
  )
}

export function ThermometerIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M10 4a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z" />
      <path d="M12 10v6" />
    </svg>
  )
}

export function CpuIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <rect x="10" y="10" width="4" height="4" />
      <path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" />
    </svg>
  )
}

export function AlertIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3 2.5 20h19z" />
      <path d="M12 10v4" />
      <path d="M12 17.5h.01" strokeWidth={2.4} />
    </svg>
  )
}

export function BellIcon({ size, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </svg>
  )
}

/** Atlas leaf mark — the brand logo used across the sidebar and hero. */
export function AtlasMark({ size, className }: IconProps) {
  return (
    <svg
      width={size ?? 20}
      height={size ?? 20}
      viewBox="0 0 32 32"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="atlas-leaf-grad" x1="6" y1="28" x2="27" y2="4" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#23b965" />
          <stop offset="1" stopColor="#7dffab" />
        </linearGradient>
      </defs>
      <path
        d="M26.5 4.5C16 5 8.2 10.3 7.2 20.4c-.3 3 .6 5.6 2.1 7.4 2.5-6.1 6.7-11.2 12.6-15-4.5 4.6-8.1 9.8-9.8 15.7 1.1.3 2.3.4 3.6.3C24.9 27.7 29.2 17.1 26.5 4.5z"
        fill="url(#atlas-leaf-grad)"
      />
    </svg>
  )
}
