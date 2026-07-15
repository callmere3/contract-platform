import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { CheckboxCard } from '../components/ui/CheckboxCard';
import { EditableTable } from '../components/ui/EditableTable';
import { FieldRenderer } from '../components/ui/FieldRenderer';
import { generateDocument, getTemplateFields } from '../api/templates';
import { getContragent, getContragentTemplates } from '../api/contragents';

// Ширины узких колонок в псевдотаблицах: № и галочки не должны съедать
// место у осмысленных колонок (название трека, ФИО).
const NARROW_COLUMNS = { has_profanity: 56, is_group: 64 };

let rowSeq = 0;
const newRow = (cols, preset = {}) => ({
  id: `r${++rowSeq}`,
  ...Object.fromEntries(cols.map((c) => [c.name, ''])),
  ...preset,
});

/**
 * Форма генерации документа.
 *
 * Схема полей приходит с сервера (GET /templates/{id}/fields) и полностью
 * определяет форму — здесь нет ни одного захардкоженного поля. Добавили
 * метку в .docx → она появилась в форме сама.
 *
 * ?contragent=<id> — генерация по конкретному контрагенту: поля с
 * настроенным maps_to приходят уже с подставленным default, nickname —
 * со списком вариантов. Без него (открытие из "Папок") форма пустая,
 * оператор заполняет всё руками.
 */
export function DocFormPage() {
  const { templateId } = useParams();
  const [searchParams] = useSearchParams();
  const contragentId = searchParams.get('contragent');
  const navigate = useNavigate();

  const [schema, setSchema] = useState(null);
  const [values, setValues] = useState({});
  const [lists, setLists] = useState({}); // {fieldName: [row, ...]}
  const [contragent, setContragent] = useState(null);
  const [pairedAct, setPairedAct] = useState(null);
  const [wantsPairedAct, setWantsPairedAct] = useState(true);
  const [format, setFormat] = useState('docx');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [data, detail] = await Promise.all([
          getTemplateFields(templateId, contragentId),
          contragentId ? getContragent(contragentId) : Promise.resolve(null),
        ]);
        if (cancelled) return;

        setSchema(data);
        setContragent(detail);

        // Стартовые значения — из default'ов схемы (сервер уже подставил
        // туда данные контрагента для полей с maps_to).
        const initial = {};
        const initialLists = {};
        const startNickname = data.fields.find((f) => f.name === 'nickname')?.default || '';
        data.fields.forEach((f) => {
          if (f.type === 'list') {
            const cols = f.item_fields ?? [];
            // Одна пустая строка сразу — иначе оператор видит пустую
            // таблицу и должен догадаться нажать "+ Добавить строку".
            initialLists[f.name] = [newRow(cols, presetForRow(f, detail, startNickname))];
          } else if (f.type === 'flag') {
            initial[f.name] = Boolean(f.default);
          } else {
            initial[f.name] = f.default ?? '';
          }
        });
        setValues(initial);
        setLists(initialLists);

        // Парный Акт: только для Приложения, открытого по контрагенту.
        // Ищем среди документов ЭТОГО контрагента — они уже отфильтрованы
        // по той же связке тегов, поэтому Акт из другой связки сюда попасть
        // не может (та же логика, что в боевой версии).
        if (contragentId && data.doc_type === 'appendix') {
          const docs = await getContragentTemplates(contragentId);
          if (cancelled) return;
          setPairedAct(docs.templates.find((t) => t.doc_type === 'act') ?? null);
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId, contragentId]);

  /**
   * Автоподстановка в строки списков. Логика перенесена из боевой версии:
   *  - в таблице треков колонка "исполнитель" заполняется псевдонимом;
   *  - в сноске "Исполнители" в одной строке сразу и псевдоним, и ФИО —
   *    раз контрагент известен, ФИО для той же строки тоже известно.
   * Значения остаются редактируемыми — это стартовое значение, не блокировка.
   *
   * nickname передаётся аргументом, а не берётся из схемы: при старте это
   * default с сервера, а для строк, добавленных позже — уже то, что оператор
   * реально выбрал в поле "Псевдоним".
   */
  function presetForRow(field, detail, nickname) {
    if (!detail) return {};
    const preset = {};
    const cols = (field.item_fields ?? []).map((c) => c.name);
    if (cols.includes('performer') && nickname) preset.performer = nickname;
    if (cols.includes('nickname') && nickname) preset.nickname = nickname;
    if (cols.includes('fio') && detail.name) preset.fio = detail.name;
    return preset;
  }

  const setValue = useCallback(
    (name, v) => {
      setValues((s) => ({ ...s, [name]: v }));

      // Выбор псевдонима подхватывают таблицы: колонка исполнителя в треках
      // и псевдоним в сноске "Исполнители". Заполняем только ПУСТЫЕ ячейки —
      // если оператор уже вписал туда что-то своё, не затираем.
      //
      // Нужно именно здесь, а не только при старте: когда у контрагента
      // несколько псевдонимов, сервер намеренно не ставит default (не
      // выбирает за оператора), поэтому на момент отрисовки таблиц
      // подставлять ещё нечего — значение появляется только сейчас.
      if (name !== 'nickname' || !v) return;
      setLists((s) => {
        const next = {};
        Object.entries(s).forEach(([listName, rows]) => {
          next[listName] = rows.map((row) => {
            const patch = {};
            if ('performer' in row && !row.performer) patch.performer = v;
            if ('nickname' in row && !row.nickname) patch.nickname = v;
            if ('fio' in row && !row.fio && contragent?.name) patch.fio = contragent.name;
            return Object.keys(patch).length ? { ...row, ...patch } : row;
          });
        });
        return next;
      });
    },
    [contragent],
  );

  const changeCell = useCallback(
    (fieldName, rowId, key, v) =>
      setLists((s) => ({
        ...s,
        [fieldName]: s[fieldName].map((r) => (r.id === rowId ? { ...r, [key]: v } : r)),
      })),
    [],
  );

  const addRow = useCallback(
    (field) =>
      setLists((s) => ({
        ...s,
        // values.nickname — то, что реально выбрано СЕЙЧАС, а не default из
        // схемы: новая строка должна подхватить текущий выбор оператора.
        [field.name]: [...s[field.name], newRow(field.item_fields ?? [], presetForRow(field, contragent, values.nickname))],
      })),
    [contragent, values.nickname],
  );

  const removeRow = useCallback(
    (fieldName, rowId) =>
      setLists((s) => ({
        ...s,
        // Последнюю строку не удаляем: пустая таблица без единой строки —
        // тупик, из которого видно только кнопку "+ Добавить".
        [fieldName]: s[fieldName].length > 1 ? s[fieldName].filter((r) => r.id !== rowId) : s[fieldName],
      })),
    [],
  );

  /**
   * Сборка тела запроса. Формат — плоский dict сырых данных формы, всё
   * вычисляемое (номер договора, сноски) достраивает build_context на сервере.
   *
   * Пустые строки списков отбрасываем, но галочки (has_profanity/is_group)
   * при проверке "строка пустая?" не учитываем — иначе строка, где оператор
   * только поставил галочку и ничего не ввёл, считалась бы заполненной и
   * попала бы в документ пустой (та же фильтрация, что в боевой версии).
   */
  function collect() {
    const data = {};
    schema.fields.forEach((f) => {
      if (f.type === 'list') {
        const cols = (f.item_fields ?? []).map((c) => c.name);
        data[f.name] = (lists[f.name] ?? [])
          .map((row) => Object.fromEntries(cols.map((c) => [c, typeof row[c] === 'boolean' ? row[c] : (row[c] ?? '').trim()])))
          .filter((item) =>
            Object.entries(item).some(([k, v]) => k !== 'has_profanity' && k !== 'is_group' && v),
          );
      } else if (f.type === 'flag') {
        data[f.name] = Boolean(values[f.name]);
      } else {
        data[f.name] = (values[f.name] ?? '').trim();
      }
    });
    return data;
  }

  async function download(id, filename) {
    const blob = await generateDocument(id, collect(), format, contragentId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${filename}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function handleGenerate() {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await download(templateId, schema.name);
      if (pairedAct && wantsPairedAct) {
        try {
          await download(pairedAct.id, pairedAct.name);
          setNotice('Приложение и Акт сформированы и скачаны.');
        } catch (e) {
          // Основной документ уже скачан — не откатываем его, просто
          // сообщаем про Акт отдельно (в нём может быть метка, которой
          // нет в форме Приложения — это поймает find_missing_variables).
          setNotice(`Документ скачан, но Акт сформировать не удалось: ${e.message}`);
        }
      } else {
        setNotice('Документ сформирован и скачан.');
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  // Группы полей в порядке, заданном сервером (GROUP_ORDER в
  // template_analysis.py) — не пересортировываем на фронте.
  const groups = useMemo(() => {
    if (!schema) return [];
    const order = [];
    const byGroup = new Map();
    schema.fields.forEach((f) => {
      if (!byGroup.has(f.group)) {
        byGroup.set(f.group, []);
        order.push(f.group);
      }
      byGroup.get(f.group).push(f);
    });
    return order.map((name) => ({ name, fields: byGroup.get(name) }));
  }, [schema]);

  if (loading) {
    return <div className="max-w-[980px] mx-auto px-8 pt-12 text-[13px] text-text-muted">Загрузка формы…</div>;
  }
  if (error && !schema) {
    return <div className="max-w-[980px] mx-auto px-8 pt-12 text-[13px] text-accent">{error}</div>;
  }

  return (
    <div className="max-w-[980px] mx-auto px-8 pt-12 pb-20">
      <Card>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border gap-4">
          <div className="min-w-0">
            <div className="text-[13px] font-bold tracking-[0.04em] text-text truncate">
              {schema.name}
            </div>
            {contragent && (
              <div className="text-[11px] text-text-muted mt-0.5 truncate">{contragent.title}</div>
            )}
          </div>
          <Button variant="secondary" size="sm" onClick={() => navigate(-1)}>
            ← Назад
          </Button>
        </div>

        <div className="px-6 py-6">
          {groups.map((group) => (
            <div key={group.name} className="mb-8 last:mb-0">
              <div className="text-[11px] font-bold tracking-[0.08em] text-text-muted mb-[18px] uppercase">
                {group.name}
              </div>

              <div className="grid grid-cols-3 gap-5">
                {group.fields
                  .filter((f) => f.type !== 'list' && f.type !== 'flag')
                  .map((f) => (
                    <FieldRenderer
                      key={f.name}
                      field={f}
                      value={values[f.name]}
                      onChange={(v) => setValue(f.name, v)}
                      // Номер договора при генерации по контрагенту берётся
                      // из карточки и не редактируется — визуально обычный
                      // input (см. design-tokens §6.1).
                      readOnly={f.name === 'contract' && f.maps_to === 'contragent.contract_number' && Boolean(contragentId)}
                    />
                  ))}
              </div>

              {group.fields.filter((f) => f.type === 'flag').length > 0 && (
                <div className="grid grid-cols-2 gap-4 mt-5">
                  {group.fields
                    .filter((f) => f.type === 'flag')
                    .map((f) => (
                      <CheckboxCard
                        key={f.name}
                        label={f.label}
                        hint={f.hint}
                        checked={Boolean(values[f.name])}
                        onChange={(e) => setValue(f.name, e.target.checked)}
                      />
                    ))}
                </div>
              )}

              {group.fields
                .filter((f) => f.type === 'list')
                .map((f) => (
                  <div key={f.name} className="mt-5">
                    <div className="text-xs text-text-secondary mb-2">{f.label}</div>
                    <EditableTable
                      columns={(f.item_fields ?? []).map((c) => ({
                        key: c.name,
                        label: c.label,
                        width: NARROW_COLUMNS[c.name],
                        // Галочки внутри строк: НЛ у трека, "группа" у исполнителя.
                        type:
                          c.name === 'has_profanity' || c.name === 'is_group'
                            ? 'flag'
                            : (c.name === 'performer' || c.name === 'nickname') &&
                                schema.fields.find((x) => x.name === 'nickname')?.nickname_options?.length
                              ? 'select'
                              : 'text',
                        options: schema.fields.find((x) => x.name === 'nickname')?.nickname_options,
                      }))}
                      rows={lists[f.name] ?? []}
                      onChangeCell={(rowId, key, v) => changeCell(f.name, rowId, key, v)}
                      onRemoveRow={(rowId) => removeRow(f.name, rowId)}
                      onAddRow={() => addRow(f)}
                    />
                    {f.hint && (
                      <div className="text-[11px] text-text-muted -mt-3 mb-5 leading-snug">{f.hint}</div>
                    )}
                  </div>
                ))}
            </div>
          ))}

          {pairedAct && (
            <div className="mb-6">
              <CheckboxCard
                label={`Также сформировать «${pairedAct.name}» по тем же данным`}
                hint="Приложение и Акт обычно подписываются одним числом на одних и тех же треках"
                checked={wantsPairedAct}
                onChange={(e) => setWantsPairedAct(e.target.checked)}
              />
            </div>
          )}

          <div className="flex items-center gap-3 pt-6 border-t border-border">
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              className="bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans outline-none"
            >
              <option value="docx">Word (.docx)</option>
              <option value="pdf">PDF</option>
            </select>
            {/* Единственная кнопка с акцентной заливкой во всём приложении —
                финальное действие генерации (см. design-tokens §6.1). */}
            <Button variant="accent" size="sm" onClick={handleGenerate} disabled={busy}>
              {busy ? 'Формируем…' : 'Сформировать документ'}
            </Button>
            {notice && !error && <span className="text-[13px] text-text-muted">{notice}</span>}
            {error && <span className="text-[13px] text-accent">{error}</span>}
          </div>
        </div>
      </Card>
    </div>
  );
}
