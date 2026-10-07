/** Decorative leaf, drawn with SVG so it inherits the page's green palette. */
export function Leaf({
  size = 48,
  rotate = 0,
  className,
  style,
}: {
  size?: number
  rotate?: number
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={`art-leaf${className ? ` ${className}` : ''}`}
      style={{ transform: `rotate(${rotate}deg)`, ...style }}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="leaf-fill" x1="10" y1="56" x2="54" y2="8" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#176e3f" />
          <stop offset="0.55" stopColor="#2fb86a" />
          <stop offset="1" stopColor="#9bffbf" />
        </linearGradient>
      </defs>
      <path
        d="M54 8C34 9 18 20 14 40c-1 7 1 13 5 17 4-12 11-23 22-32C32 34 26 44 23 56c2 1 5 1 7 1C47 55 56 36 54 8z"
        fill="url(#leaf-fill)"
      />
      <path d="M22 56C27 42 35 31 46 22" stroke="#d6ffe5" strokeOpacity="0.55" strokeWidth="1.2" fill="none" />
    </svg>
  )
}
