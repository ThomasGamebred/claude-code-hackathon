interface Props {
  value: number;
  showNumber?: boolean;
  size?: "sm" | "md";
}

function color(value: number): string {
  if (value >= 0.9) return "bg-emerald-500";
  if (value >= 0.7) return "bg-gold-400";
  return "bg-rose-500";
}

function textColor(value: number): string {
  if (value >= 0.9) return "text-emerald-700";
  if (value >= 0.7) return "text-gold-700";
  return "text-rose-700";
}

export default function ConfidenceBar({
  value,
  showNumber = true,
  size = "md",
}: Props) {
  const pct = Math.max(0, Math.min(1, value));
  const h = size === "sm" ? "h-1.5" : "h-2";
  return (
    <div className="flex items-center gap-2 min-w-[8rem]">
      <div className={`flex-1 rounded-full bg-swamp-100 overflow-hidden ${h}`}>
        <div
          className={`${h} ${color(pct)} transition-all`}
          style={{ width: `${pct * 100}%` }}
        />
      </div>
      {showNumber && (
        <span className={`text-xs font-mono tabular-nums ${textColor(pct)}`}>
          {pct.toFixed(2)}
        </span>
      )}
    </div>
  );
}
