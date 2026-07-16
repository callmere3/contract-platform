import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { CheckboxCard } from '../components/ui/CheckboxCard';
import { EditableTable } from '../components/ui/EditableTable';
import { FieldRenderer } from '../components/ui/FieldRenderer';
import { generateDocument, getTemplateFields } from '../api/templates';
import { getContragent, getContragentTemplates } from '../api/contragents';
import { useAuth } from '../auth/AuthContext';
import { canFillDemoData } from '../auth/permissions';

// Ширины узких колонок в псевдотаблицах: № и галочки не должны съедать
// место у осмысленных колонок (название трека, ФИО).
const NARROW_COLUMNS = { has_profanity: 56, is_group: 64 };

// Чекбоксы-колонки, которых НЕТ в схеме с сервера (item_fields), но которые
// нужны чисто на фронте: НЛ (ненормативная лексика) у каждого трека и
// «Группа» у каждого исполнителя в сноске. Backend ждёт их в payload
// (build_profanity_note/build_performer_note в context_builder.py), поэтому
// они добавляются к колонкам таблицы и попадают в collect() — см. columnsFor.
const EXTRA_CHECKBOX_COLUMN = {
  tracks: { name: 'has_profanity', label: 'НЛ' },
  performers: { name: 'is_group', label: 'Группа' },
};

// Полный список колонок поля-списка: колонки из схемы + фронтовый чекбокс.
function columnsFor(field) {
  const base = field.item_fields ?? [];
  const extra = EXTRA_CHECKBOX_COLUMN[field.name];
  return extra ? [...base, extra] : base;
}

let rowSeq = 0;
const newRow = (cols, preset = {}) => ({
  id: `r${++rowSeq}`,
  ...Object.fromEntries(cols.map((c) => [c.name, ''])),
  ...preset,
});

// Уникальные никнеймы исполнителей из столбца «Исполнитель» таблицы треков,
// в порядке появления. Несколько исполнителей в одной ячейке через запятую
// («IVAN, PETROV») считаются РАЗНЫМИ исполнителями (как в боевом index.html:
// syncPerformers) — каждый попадёт в сноску отдельной строкой.
function uniquePerformerNicks(tracksRows) {
  const nicks = [];
  const seen = new Set();
  (tracksRows ?? []).forEach((row) => {
    String(row.performer ?? '')
      .split(',')
      .forEach((part) => {
        const v = part.trim();
        const key = v.toLowerCase();
        if (v && !seen.has(key)) {
          seen.add(key);
          nicks.push(v);
        }
      });
  });
  return nicks;
}

// Пересобирает строки сноски «Исполнители» из уникальных исполнителей
// таблицы треков (зеркало syncPerformers из index.html). ФИО и отметку
// «Группа» сохраняем по никнейму, чтобы не терять уже введённое оператором.
// Если исполнителей в треках ещё нет — сноску не трогаем (там обычно одна
// пустая строка, которую оператор может заполнить руками).
//
// Если исполнитель, выбранный в треках, — один из псевдонимов контрагента,
// его ФИО достоверно известно (= ФИО контрагента) и подставляется в новую
// строку сноски автоматически. Верхнее поле «Псевдоним» при этом может быть
// не заполнено — важно именно то, что выбрано в таблице треков. Для чужого
// имени (вписанного вручную, не из списка) ФИО оставляем пустым.
//
// Возвращает ТОТ ЖЕ массив (prevRows) когда состав не изменился — чтобы не
// провоцировать лишний ре-рендер и не сбрасывать фокус при правках треков.
function rebuildPerformers(tracksRows, prevRows, perfColumns, contragent) {
  const nicks = uniquePerformerNicks(tracksRows);
  if (!nicks.length) return prevRows;

  const byNick = new Map();
  (prevRows ?? []).forEach((r) => {
    const key = (r.nickname ?? '').trim().toLowerCase();
    if (key && !byNick.has(key)) byNick.set(key, r);
  });

  const knownNicks = new Set((contragent?.nicknames ?? []).map((n) => n.toLowerCase()));
  const contragentFio = contragent?.name ?? '';

  const rebuilt = nicks.map((nick) => {
    const existing = byNick.get(nick.toLowerCase());
    if (existing) return existing.nickname === nick ? existing : { ...existing, nickname: nick };
    const preset = { nickname: nick };
    if (contragentFio && knownNicks.has(nick.toLowerCase())) preset.fio = contragentFio;
    return newRow(perfColumns, preset);
  });

  const unchanged =
    prevRows &&
    rebuilt.length === prevRows.length &&
    rebuilt.every((r, i) => r === prevRows[i]);
  return unchanged ? prevRows : rebuilt;
}

// Кварталы — как в build_term_end на бэкенде (app/context_builder.py):
// срок действия всегда до конца квартала, а не произвольного числа.
const QUARTER_ENDS = { 1: '31 марта', 2: '30 июня', 3: '30 сентября', 4: '31 декабря' };

/**
 * Живой пересчёт "Срок действия" — зеркало build_term_end() на бэкенде:
 * +5 лет от даты документа, до конца квартала. День исходной даты на
 * результат не влияет (только месяц определяет квартал, год — год+5),
 * поэтому в отличие от Python-версии не нужно даже отдельно обрабатывать
 * 29 февраля — это чисто техническая деталь работы с датами в Python,
 * которая не отражается на итоговом тексте.
 */
function computeTermEnd(isoDate) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate || '');
  if (!m) return '';
  const month = Number(m[2]);
  const futureYear = Number(m[1]) + 5;
  const quarter = Math.floor((month - 1) / 3) + 1;
  return `${QUARTER_ENDS[quarter]} ${futureYear} г.`;
}

/** Целое неотрицательное число из строки формы (пробелы/неразрывные пробелы игнорируются) — null, если не число. */
function parseFormAmount(raw) {
  if (raw == null) return null;
  const s = String(raw).trim().replace(/\s/g, '');
  if (!s) return null;
  if (!/^\d+$/.test(s)) return null;
  return Number(s);
}

/** Живой пересчёт "Штраф за непереданный трек" — зеркало resolve_penalty_raw() на бэкенде: сумма аванса / количество треков. */
function computePenalty(advanceRaw, countRaw) {
  const advance = parseFormAmount(advanceRaw);
  const count = parseFormAmount(countRaw);
  if (advance === null || !count) return '';
  return String(Math.round(advance / count));
}

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

  const { user } = useAuth();
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

  // "Тронуто" = оператор сам вписал значение в term_end/penalty — тогда
  // живой пересчёт останавливается и не перезаписывает его выбор.
  // Если поле потом ОЧИЩЕНО обратно — снова считаем полем "в авторежиме"
  // (см. setValue ниже): то же правило "пусто = авто", что и на бэкенде
  // (resolve_penalty_raw/term_end в build_context — там оно решается по
  // тому же признаку: явное значение или пустая строка).
  const [termEndTouched, setTermEndTouched] = useState(false);
  const [penaltyTouched, setPenaltyTouched] = useState(false);

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
            const cols = columnsFor(f);
            // Одна пустая строка сразу — иначе оператор видит пустую
            // таблицу и должен догадаться нажать "+ Добавить строку".
            initialLists[f.name] = [newRow(cols, presetForRow(f, detail, startNickname))];
          } else if (f.type === 'flag') {
            initial[f.name] = Boolean(f.default);
          } else if (f.type === 'choice') {
            // Без явного default выбираем ПЕРВЫЙ вариант, а не пустую строку:
            // иначе select показывает первый вариант (напр. «Сингл»), но в
            // state лежит '', и на бэкенд уходит '' — а там release_type
            // != 'none' истинно, и блок релиза попал бы в документ даже
            // для сингла. С 'none' форма, состояние и бэкенд согласованы.
            initial[f.name] = f.default || f.choices?.[0]?.value || '';
          } else {
            initial[f.name] = f.default ?? '';
          }
        });
        setValues(initial);
        setLists(initialLists);
        setTermEndTouched(false);
        setPenaltyTouched(false);

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

  // Приложение/Акт (LINKED_DOC_TYPES на бэкенде) — своя дата "date", у
  // комбинированного Договора срок действия считается от "c_date".
  const termEndSourceDate = schema && ['appendix', 'act'].includes(schema.doc_type)
    ? values.date
    : values.c_date;

  // Живой пересчёт "Срок действия" при изменении даты документа — пока
  // оператор не вписал в term_end что-то своё (см. touched выше). Условие
  // на schema гарантирует, что это выполнится только для шаблонов, где
  // term_end реально есть в форме (иначе пишем в values ключ, которым
  // никто не воспользуется — не вредно, но незачем).
  useEffect(() => {
    if (termEndTouched) return;
    if (!schema?.fields.some((f) => f.name === 'term_end')) return;
    setValues((s) => ({ ...s, term_end: computeTermEnd(termEndSourceDate) }));
  }, [termEndSourceDate, termEndTouched, schema]);

  // Живой пересчёт "Штраф за непереданный трек" = сумма аванса / количество
  // треков, пока оператор не вписал в penalty что-то своё.
  useEffect(() => {
    if (penaltyTouched) return;
    if (!schema?.fields.some((f) => f.name === 'penalty')) return;
    setValues((s) => ({ ...s, penalty: computePenalty(values.advance, values.count) }));
  }, [values.advance, values.count, penaltyTouched, schema]);

  // Синхронизация сноски «Исполнители» с таблицей треков: любой исполнитель,
  // появившийся в треках (в т.ч. второй, и каждый из перечисленных через
  // запятую), автоматически попадает в сноску; если он из псевдонимов
  // контрагента — с подставленным ФИО (см. rebuildPerformers). Зависит только
  // от lists.tracks/contragent, поэтому правки самой сноски (ФИО, «Группа»)
  // её не пересобирают.
  useEffect(() => {
    const perfField = schema?.fields.find((f) => f.name === 'performers');
    if (!perfField || !schema.fields.some((f) => f.name === 'tracks')) return;
    const perfColumns = columnsFor(perfField);
    setLists((s) => {
      const next = rebuildPerformers(s.tracks, s.performers, perfColumns, contragent);
      return next === s.performers ? s : { ...s, performers: next };
    });
  }, [lists.tracks, schema, contragent]);

  /**
   * Автоподстановка в строки списков. Логика перенесена из боевой версии:
   *  - в таблице треков колонка "исполнитель" заполняется псевдонимом;
   *  - в сноске "Исполнители" ФИО подставляется ТОЛЬКО вместе с псевдонимом —
   *    то есть когда исполнитель действительно выбран из псевдонимов
   *    контрагента: только тогда мы наверняка знаем его ФИО. Без выбранного
   *    псевдонима (например, у контрагента вообще нет псевдонимов, или строка
   *    добавлена пустой) ФИО НЕ предзаполняем — иначе в сноске появлялось бы
   *    ФИО контрагента при пустом исполнителе.
   * Значения остаются редактируемыми — это стартовое значение, не блокировка.
   *
   * nickname передаётся аргументом, а не берётся из схемы: при старте это
   * default с сервера, а для строк, добавленных позже — уже то, что оператор
   * реально выбрал в поле "Псевдоним".
   */
  /**
   * Заполняет форму демо-данными (кнопка только у админа, см.
   * canFillDemoData). Значения берутся ИЗ СХЕМЫ — поле `demo`, которое
   * сервер кладёт рядом с label/hint (см. DEMO_VALUES в
   * template_analysis.py). Здесь их сознательно нет: форма строится из
   * .docx, и списка полей на фронте быть не должно — иначе кнопка
   * потребовала бы правки при каждом новом шаблоне (ИП/ООО). Так же она
   * работает одинаково для договора, приложения и акта: у каждого свой
   * набор меток, и каждое поле знает своё демо-значение само.
   *
   * Поля без demo не трогаем: у c_date/delivery_date уже есть автодефолт,
   * а term_end/penalty пересчитаются сами из подставленных c_date и
   * advance/count — их и надо проверять расчётом, а не подставленным
   * числом.
   *
   * locked-поля пропускаем: дата, зафиксированная в карточке контрагента,
   * не редактируется в принципе — затирать её демо-значением значило бы
   * обойти собственное правило (см. get_template_fields на бэкенде).
   */
  function fillDemo() {
    if (!schema) return;

    setValues((prev) => {
      const next = { ...prev };
      schema.fields.forEach((f) => {
        if (f.type === 'list' || f.locked) return;
        if (f.demo === null || f.demo === undefined) return;
        next[f.name] = f.demo;
      });
      return next;
    });

    setLists((prev) => {
      const next = { ...prev };
      schema.fields.forEach((f) => {
        if (f.type !== 'list' || !f.demo?.length) return;
        // newRow заполнит все колонки пустыми и наложит демо-строку сверху —
        // так строка получит id и колонки, которых в демо нет.
        next[f.name] = f.demo.map((row) => newRow(columnsFor(f), row));
      });
      return next;
    });

    setNotice('Форма заполнена тестовыми данными.');
  }

  function presetForRow(field, detail, nickname) {
    if (!detail || !nickname) return {};
    const preset = {};
    const cols = (field.item_fields ?? []).map((c) => c.name);
    if (cols.includes('performer')) preset.performer = nickname;
    if (cols.includes('nickname')) preset.nickname = nickname;
    if (cols.includes('fio') && detail.name) preset.fio = detail.name;
    return preset;
  }

  const setValue = useCallback(
    (name, v) => {
      setValues((s) => ({ ...s, [name]: v }));

      // Прямой ввод оператора в term_end/penalty — отмечаем "тронуто", чтобы
      // эффекты живого пересчёта ниже перестали его перезаписывать. Пустое
      // значение снимает пометку — оператор фактически вернул поле в
      // авторежим (см. комментарий у useState выше).
      if (name === 'term_end') setTermEndTouched(Boolean(v));
      if (name === 'penalty') setPenaltyTouched(Boolean(v));

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
        [field.name]: [...s[field.name], newRow(columnsFor(field), presetForRow(field, contragent, values.nickname))],
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
        const cols = columnsFor(f).map((c) => c.name);
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

  // Имя файла приходит с сервера в Content-Disposition — уже с расширением
  // и по формуле "{титл} - {тип документа}{ номер} {номер договора}"
  // (см. build_document_filename на бэкенде). Здесь его не собираем: раньше
  // фронт подставлял название шаблона ("Договор_СГ_роялти.docx"), и у
  // истории генерации имя выходило другим.
  async function download(id) {
    const { blob, filename } = await generateDocument(id, collect(), format, contragentId);
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
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
      await download(templateId);
      if (pairedAct && wantsPairedAct) {
        try {
          await download(pairedAct.id);
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

  // Условная видимость полей — зеркало wireupReleaseVisibility в старом
  // index.html. В шаблоне эти блоки под {% if %}, поэтому скрытое просто
  // не попадёт в документ; здесь прячем их и в форме, чтобы не путать
  // оператора полями, которые ни на что не влияют при текущем выборе.
  //   release_name/release_year — только для ЕР/альбома, не для сингла
  //   videoclips — только когда отмечен чекбокс «Есть видеоклип»
  //   smm — только когда отмечена «Маркетинговая кампания» (шаблон аванса)
  function isFieldHidden(field) {
    if (field.name === 'release_name' || field.name === 'release_year') {
      // release_type пустой (стартовое состояние) = «Сингл» (первый вариант)
      return !values.release_type || values.release_type === 'none';
    }
    if (field.name === 'videoclips') return !values.has_videoclip;
    if (field.name === 'smm') return !values.marketing;
    return false;
  }

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
          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Только админу: кнопка для проверки шаблонов, в рабочем потоке
                менеджера она бы только мешала (см. canFillDemoData). */}
            {canFillDemoData(user?.role) && (
              <Button variant="secondary" size="sm" onClick={fillDemo}>
                Тестовые данные
              </Button>
            )}
            <Button variant="secondary" size="sm" onClick={() => navigate(-1)}>
              ← Назад
            </Button>
          </div>
        </div>

        <div className="px-6 py-6">
          {groups.map((group) => {
            // Скрытые поля (сингл без релиза, видеоклип без галочки, SMM
            // без маркетинга) убираем целиком. Если в группе не осталось
            // ни одного видимого поля — не рисуем и её заголовок (так
            // прячется весь раздел «Видеоклипы», а не пустая шапка).
            const visible = group.fields.filter((f) => !isFieldHidden(f));
            if (visible.length === 0) return null;
            const textFields = visible.filter((f) => f.type !== 'list' && f.type !== 'flag');
            const flagFields = visible.filter((f) => f.type === 'flag');
            const listFields = visible.filter((f) => f.type === 'list');
            const nicknameOptions = schema.fields.find((x) => x.name === 'nickname')?.nickname_options;
            return (
              <div key={group.name} className="mb-8 last:mb-0">
                <div className="text-[11px] font-bold tracking-[0.08em] text-text-muted mb-[18px] uppercase">
                  {group.name}
                </div>

                {textFields.length > 0 && (
                  <div className="grid grid-cols-3 gap-5">
                    {textFields.map((f) => (
                      <FieldRenderer
                        key={f.name}
                        field={f}
                        value={values[f.name]}
                        onChange={(v) => setValue(f.name, v)}
                        // Номер договора при генерации по контрагенту берётся
                        // из карточки и не редактируется — визуально обычный
                        // input (см. design-tokens §6.1). f.locked — то же
                        // самое для c_date, когда дата договора уже
                        // зафиксирована в карточке (см. get_template_fields
                        // на бэкенде) — там уже готов и подставлен hint с
                        // объяснением, почему поле нередактируемо.
                        readOnly={
                          (f.name === 'contract' && f.maps_to === 'contragent.contract_number' && Boolean(contragentId)) ||
                          Boolean(f.locked)
                        }
                      />
                    ))}
                  </div>
                )}

                {flagFields.length > 0 && (
                  <div className="grid grid-cols-2 gap-4 mt-5">
                    {flagFields.map((f) => (
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

                {listFields.map((f) => (
                  <div key={f.name} className="mt-5">
                    <div className="text-xs text-text-secondary mb-2">{f.label}</div>
                    <EditableTable
                      columns={columnsFor(f).map((c) => ({
                        key: c.name,
                        label: c.label,
                        width: NARROW_COLUMNS[c.name],
                        // Галочки внутри строк: НЛ у трека, "группа" у исполнителя.
                        // Колонка исполнителя — combo: свободный ввод + подсказки
                        // из псевдонимов контрагента (можно выбрать ИЛИ вписать
                        // своё). Без псевдонимов combo без подсказок = обычный ввод.
                        type:
                          c.name === 'has_profanity' || c.name === 'is_group'
                            ? 'flag'
                            : c.name === 'performer' || c.name === 'nickname'
                              ? 'combo'
                              : 'text',
                        options: nicknameOptions,
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
            );
          })}

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
            {/* Единственная кнопка с акцентной заливкой во всём приложении —
                финальное действие генерации (см. design-tokens §6.1).
                Идёт первой, выбор формата — справа от неё. */}
            <Button variant="accent" size="sm" onClick={handleGenerate} disabled={busy}>
              {busy ? 'Формируем…' : 'Сформировать документ'}
            </Button>
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              className="bg-input-bg border border-border rounded-input px-3 py-2.5 text-sm text-text font-sans outline-none"
            >
              <option value="docx">Word (.docx)</option>
              <option value="pdf">PDF</option>
            </select>
            {notice && !error && <span className="text-[13px] text-text-muted">{notice}</span>}
            {error && <span className="text-[13px] text-accent">{error}</span>}
          </div>
        </div>
      </Card>
    </div>
  );
}
