/**
 * Приписка территории к площадке — «RU», «KZ», «AE» у Believe (см.
 * REPORT_REGIONS на сервере). Серая и мелкая (просьба владельца 25.09.2026):
 * это подсказка, какой из трёх отчётов перед глазами, а не часть названия.
 */
export default function Region({ value }) {
  if (!value) return null;
  return <span className="ml-1.5 text-[11px] font-normal text-text-muted">{value}</span>;
}
