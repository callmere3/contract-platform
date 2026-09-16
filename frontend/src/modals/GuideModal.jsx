import { useMemo, useState } from 'react';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { useModal } from './ModalProvider';
import { useAuth } from '../auth/AuthContext';
import { guideFor } from '../content/guide';

/**
 * Инструкция к сервису — открывается из профиля.
 *
 * Два столбца: слева оглавление, справа текст выбранного раздела. Не одна
 * длинная простыня: у модалки высота ограничена 85% экрана, и в сплошной
 * прокрутке новый сотрудник теряет, где он находится.
 *
 * Показываем только те разделы, которые у человека реально есть в
 * интерфейсе (guideFor по роли): объяснять менеджеру вкладку, которой он не
 * видит, — верный способ сбить с толку.
 *
 * Текст лежит отдельно, в content/guide.js — правки формулировок не
 * требуют трогать вёрстку.
 */
export function GuideModal({ level, isTop }) {
  const { closeModal } = useModal();
  const { user } = useAuth();

  const sections = useMemo(() => guideFor(user?.role), [user?.role]);
  const [activeId, setActiveId] = useState(sections[0]?.id);
  const active = sections.find((s) => s.id === activeId) ?? sections[0];

  return (
    <Modal
      title="Инструкция"
      onClose={closeModal}
      level={level}
      isTop={isTop}
      width={820}
      footer={
        <Button variant="primary" size="sm" onClick={closeModal}>
          Закрыть
        </Button>
      }
    >
      <div className="flex gap-6 items-start">
        <nav className="w-[210px] flex-shrink-0 flex flex-col gap-0.5">
          {sections.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setActiveId(s.id)}
              className={`flex items-center gap-2.5 text-left px-2.5 py-2 rounded-input border-none cursor-pointer font-sans text-[13px] ${
                s.id === active?.id
                  ? 'bg-accent-soft text-accent font-semibold'
                  : 'bg-transparent text-text-secondary'
              }`}
            >
              <span className="text-[15px] leading-none">{s.icon}</span>
              <span className="truncate">{s.title}</span>
            </button>
          ))}
        </nav>

        <article className="flex-1 min-w-0 flex flex-col gap-3.5">
          <h3 className="m-0 text-[17px] font-semibold text-text">{active?.title}</h3>
          {active?.body.map((block, i) => (
            <Block key={i} block={block} />
          ))}
        </article>
      </div>
    </Modal>
  );
}

/** Один блок текста. Типы намеренно простые — см. комментарий в guide.js. */
function Block({ block }) {
  if (block.type === 'p') {
    return (
      <p className="m-0 text-[13.5px] text-text-secondary leading-relaxed">{block.text}</p>
    );
  }

  if (block.type === 'list') {
    return (
      <ul className="m-0 pl-5 flex flex-col gap-2 text-[13.5px] text-text-secondary leading-relaxed marker:text-accent">
        {block.items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    );
  }

  if (block.type === 'steps') {
    return (
      <ol className="m-0 pl-5 flex flex-col gap-2 text-[13.5px] text-text-secondary leading-relaxed marker:text-accent marker:font-semibold">
        {block.items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ol>
    );
  }

  if (block.type === 'qa') {
    return (
      <div className="flex flex-col gap-3">
        {block.items.map((item, i) => (
          <div key={i}>
            <div className="text-[13.5px] font-semibold text-text">{item.q}</div>
            <div className="text-[13.5px] text-text-secondary leading-relaxed mt-0.5">
              {item.a}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (block.type === 'note') {
    return (
      <div className="text-[13px] text-text-secondary leading-relaxed bg-surface-hover border-l-2 border-accent rounded-input px-3.5 py-3">
        {block.text}
      </div>
    );
  }

  return null;
}
