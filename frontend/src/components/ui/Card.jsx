export function Card({ children, className = '' }) {
  return (
    <div
      className={`bg-surface border border-border rounded-card shadow-card overflow-hidden ${className}`}
    >
      {children}
    </div>
  );
}
