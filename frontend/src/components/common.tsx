import { parseBlocks, parseInline } from "../format";
import type { Confidence, Rating } from "../types";

export function RatingBadge({ rating, confidence }: { rating: Rating; confidence?: Confidence }) {
  return (
    <div className="rating">
      <span className={`badge badge-${rating.toLowerCase()}`}>{rating}</span>
      {confidence && <span className="rating-conf">{confidence.charAt(0) + confidence.slice(1).toLowerCase()} confidence</span>}
    </div>
  );
}

function Inline({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((part, i) => (part.bold ? <strong key={i}>{part.text}</strong> : <span key={i}>{part.text}</span>))}
    </>
  );
}

/** Paragraphs, bullet lists and **bold**. Everything is rendered as React text nodes, never as HTML. */
export function RichText({ text }: { text: string }) {
  return (
    <div className="rich">
      {parseBlocks(text).map((block, i) =>
        block.kind === "p" ? (
          <p key={i}>
            <Inline text={block.text} />
          </p>
        ) : (
          <ul key={i}>
            {block.items.map((item, j) => (
              <li key={j}>
                <Inline text={item} />
              </li>
            ))}
          </ul>
        ),
      )}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "up" | "down" }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Notice({ kind, children }: { kind: "warn" | "info" | "ok"; children: React.ReactNode }) {
  return <div className={`notice notice-${kind}`}>{children}</div>;
}
